from __future__ import annotations

import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .law_open_api import LawOpenApiClient, from_env
from .models import LawArticle

DEFAULT_LAWS_PATH = Path(__file__).resolve().parents[2] / "data" / "laws.json"
DEFAULT_JB_TERMS_PATH = Path(__file__).resolve().parents[2] / "data" / "jb_terms.json"
STALE_AFTER_DAYS = 730


@lru_cache(maxsize=8)
def _load_articles_cached(path_str: str, mtime_ns: int, size: int) -> tuple[LawArticle, ...]:
    """Load immutable LawArticle rows with file-stat cache invalidation.

    Batch/reusable-agent workflows repeatedly instantiate KB-backed agents. Caching
    parsed JSON by (path, mtime, size) removes repeated disk + JSON parse overhead
    while still invalidating automatically when data/laws.json or jb_terms.json
    changes.
    """
    _ = (mtime_ns, size)  # part of cache key; not otherwise needed
    rows = json.loads(Path(path_str).read_text(encoding="utf-8"))
    return tuple(LawArticle(**row) for row in rows)


def _load_articles(path: str | Path) -> list[LawArticle]:
    p = Path(path)
    stat = p.stat()
    return list(_load_articles_cached(str(p), stat.st_mtime_ns, stat.st_size))


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def article_provenance(article: LawArticle, *, as_of: date | None = None) -> dict:
    """Return source/freshness metadata required by the JB PDF compliance use case."""
    as_of = as_of or date.today()
    effective = _parse_date(article.effective_date)
    age_days = (as_of - effective).days if effective else None
    is_local = article.source_url.startswith("local://")
    is_official = any(domain in article.source_url for domain in ["law.go.kr", "fsc.go.kr", "fss.or.kr", "pipc.go.kr"])
    is_placeholder = "placeholder" in article.text.lower() or "Phase C" in article.text
    status_verified = bool(effective and (is_local or is_official) and not is_placeholder)
    freshness_status = "unknown"
    if age_days is not None:
        freshness_status = "fresh" if age_days <= STALE_AFTER_DAYS else "stale_review_required"
    return {
        "law_name": article.law_name,
        "article_no": article.article_no,
        "title": article.title,
        "source_url": article.source_url,
        "effective_date": article.effective_date,
        "source_type": "internal_standard" if is_local else "official_or_external",
        "status_verified": status_verified,
        "freshness_status": freshness_status,
        "age_days": age_days,
    }


class LawKnowledgeBase:
    def __init__(
        self,
        articles: list[LawArticle],
        *,
        api_client: Optional[LawOpenApiClient] = None,
    ) -> None:
        self.articles = articles
        self._article_lookup = {
            (normalize(article.law_name), normalize_article_no(article.article_no)): article
            for article in articles
        }
        self._search_rows = [
            (
                article,
                tokenize(" ".join([article.law_name, article.article_no, article.title, article.text, *article.keywords])),
                normalize(" ".join([article.law_name, article.article_no, article.title, article.text, *article.keywords])),
            )
            for article in articles
        ]
        self._coverage_cache: dict[str, dict] = {}
        # offline-first: env에 LAW_OPEN_API_KEY가 있으면 production 모드, 없으면 None
        self.api_client = api_client if api_client is not None else from_env()

    @classmethod
    def from_json(
        cls,
        path: str | Path = DEFAULT_LAWS_PATH,
        *,
        jb_terms_path: str | Path | None = DEFAULT_JB_TERMS_PATH,
    ) -> "LawKnowledgeBase":
        articles = _load_articles(path)
        # JB 계열사 약관 샘플(있을 경우)을 함께 적재 — 평가② 사업 연계성 가시화
        if jb_terms_path and Path(jb_terms_path).exists():
            articles.extend(_load_articles(jb_terms_path))
        return cls(articles)

    def get_article(self, law_name: str, article_no: str) -> LawArticle | None:
        normalized_law = normalize(law_name)
        normalized_article = normalize_article_no(article_no)
        cached = self._article_lookup.get((normalized_law, normalized_article))
        if cached:
            return cached
        # 로컬 캐시 미스 → API client가 있으면 한 번 시도, 실패 시 None
        if self.api_client and self.api_client.enabled:
            fetched = self.api_client.fetch_article(law_name, article_no)
            if fetched:
                article = LawArticle(
                    law_name=fetched.law_name,
                    article_no=fetched.article_no,
                    title=f"{fetched.law_name} 제{fetched.article_no}조",
                    text=fetched.text,
                    effective_date=fetched.effective_date,
                    source_url=fetched.source_url,
                    keywords=[],
                )
                self.articles.append(article)  # 캐시 적재
                self._article_lookup[(normalize(article.law_name), normalize_article_no(article.article_no))] = article
                self._search_rows.append((
                    article,
                    tokenize(" ".join([article.law_name, article.article_no, article.title, article.text, *article.keywords])),
                    normalize(" ".join([article.law_name, article.article_no, article.title, article.text, *article.keywords])),
                ))
                self._coverage_cache.clear()
                return article
        return None

    def coverage_report(self, *, as_of: date | None = None) -> dict:
        """Summarize corpus readiness for PDF 요구사항: 최신 규제 + 내부 기준 자동 추적."""
        as_of = as_of or date.today()
        cache_key = as_of.isoformat()
        if cache_key in self._coverage_cache:
            return dict(self._coverage_cache[cache_key])
        provenance = [article_provenance(article, as_of=as_of) for article in self.articles]
        law_names = sorted({article.law_name for article in self.articles})
        source_types = {row["source_type"] for row in provenance}
        stale = [row for row in provenance if row["freshness_status"] == "stale_review_required"]
        unverified = [row for row in provenance if not row["status_verified"]]
        placeholder_count = sum(1 for article in self.articles if "placeholder" in article.text.lower() or "Phase C" in article.text)
        official_text_count = sum(1 for article in self.articles if "official_text" in article.keywords)
        report = {
            "article_count": len(self.articles),
            "unique_law_count": len(law_names),
            "law_names": law_names,
            "source_types": sorted(source_types),
            "official_or_external_count": sum(1 for row in provenance if row["source_type"] == "official_or_external"),
            "internal_standard_count": sum(1 for row in provenance if row["source_type"] == "internal_standard"),
            "stale_count": len(stale),
            "unverified_count": len(unverified),
            "placeholder_count": placeholder_count,
            "official_text_count": official_text_count,
            "expansion_target": "100+ official law/internal-standard articles before production; 0 placeholder articles for production_ready",
            "production_ready": len(self.articles) >= 100 and not stale and not unverified and placeholder_count == 0,
            "top_freshness_issues": stale[:5],
        }
        self._coverage_cache[cache_key] = dict(report)
        return report

    def search(self, query: str, *, limit: int = 5) -> list[LawArticle]:
        query_tokens = tokenize(query)
        scored: list[tuple[float, LawArticle]] = []
        normalized_query = normalize(query)
        for article, hay_tokens, _normalized_haystack in self._search_rows:
            exact_bonus = 2.0 if normalize(article.law_name) in normalized_query else 0.0
            article_bonus = 1.5 if normalize_article_no(article.article_no) and normalize_article_no(article.article_no) in normalized_query else 0.0
            overlap = len(query_tokens & hay_tokens)
            keyword_hits = sum(1 for keyword in article.keywords if normalize(keyword) in normalized_query)
            score = exact_bonus + article_bonus + overlap + 1.2 * keyword_hits
            if score > 0:
                scored.append((score, article))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [article for _score, article in scored[:limit]]


def normalize(value: str) -> str:
    return "".join(value.lower().split())


def normalize_article_no(value: str) -> str:
    return normalize(value).replace("제", "").replace("조", "")


def tokenize(value: str) -> set[str]:
    normalized = value.lower().replace("·", " ").replace("/", " ")
    for char in ",.()[]{}:;\"'\n\t":
        normalized = normalized.replace(char, " ")
    return {token.strip() for token in normalized.split() if len(token.strip()) >= 2}
