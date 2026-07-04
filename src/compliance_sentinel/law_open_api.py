"""법령정보센터(law.go.kr) Open API adapter — offline-first.

환경변수 `LAW_OPEN_API_KEY`가 있으면 실제 API를 호출하고, 없으면 None 반환하여
caller(LawKnowledgeBase)가 로컬 캐시 KB로 fallback하도록 한다.

API 스펙 1차 출처:
- https://open.law.go.kr/LSO/openApi/guideList.do
- https://open.law.go.kr/LSO/openApi/guideResult.do

WARNING — 본 모듈은 *오프라인 MVP* 단계에서는 호출되지 않는다.
사용자가 LAW_OPEN_API_KEY를 명시적으로 환경에 설정한 경우에만 활성화된다.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

from .agent_shield_bridge import resilient_tool_call

API_BASE = "https://www.law.go.kr/DRF/lawService.do"
API_SEARCH = "https://www.law.go.kr/DRF/lawSearch.do"
DEFAULT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class LawApiArticle:
    """법령정보센터에서 받은 단일 조문 원문."""
    law_name: str
    article_no: str
    text: str
    effective_date: str
    source_url: str


class LawOpenApiClient:
    def __init__(self, api_key: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.api_key = api_key or os.environ.get("LAW_OPEN_API_KEY")
        self.timeout = timeout
        self._mst_cache: dict[str, dict[str, str]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def search_law(self, law_name: str) -> Optional[dict[str, str]]:
        """Resolve a human law name to law.go.kr MST metadata.

        lawService.do expects `MST` (법령일련번호), not a free-form law name.
        This search step keeps runtime callers simple while retaining official
        law.go.kr as source of truth. API key/OC is never returned to callers.
        """
        if not self.enabled:
            return None
        cache_key = _normalize_law_name(law_name)
        if cache_key in self._mst_cache:
            return self._mst_cache[cache_key]
        params = {
            "OC": self.api_key,
            "target": "law",
            "query": law_name,
            "type": "JSON",
        }
        url = f"{API_SEARCH}?{urllib.parse.urlencode(params)}"
        def _fetch_search():
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))

        try:
            # 오류회복(가이드 제2장): 외부 read API → retry+timeout+circuit, 실패 시 None fallback.
            payload = resilient_tool_call(
                _fetch_search, tool_name="law_open_api_search",
                idempotent=True, timeout_s=self.timeout, max_attempts=2,
            )
        except Exception:
            return None
        rows = ((payload.get("LawSearch") or {}).get("law") or []) if isinstance(payload, dict) else []
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or not rows:
            return None
        normalized_target = _normalize_law_name(law_name)

        def score(row: dict[str, Any]) -> tuple[int, str]:
            title = str(row.get("법령명한글") or row.get("법령명") or "")
            normalized_title = _normalize_law_name(title)
            exact = int(normalized_title == normalized_target)
            contains = int(normalized_target in normalized_title or normalized_title in normalized_target)
            # If caller asks for a base law, do not let a newer 시행령/시행규칙 win.
            wants_subordinate = any(suffix in law_name for suffix in ["시행령", "시행규칙"])
            subordinate_penalty = -5 if (not wants_subordinate and any(suffix in title for suffix in ["시행령", "시행규칙"])) else 0
            base_law_bonus = 3 if (not wants_subordinate and not any(suffix in title for suffix in ["시행령", "시행규칙"])) else 0
            # 시행 중/최신 시행일 우선. 시행일자는 YYYYMMDD string이라 lexical sort 가능.
            return (exact * 10 + contains + base_law_bonus + subordinate_penalty, str(row.get("시행일자") or ""))

        best = max((r for r in rows if isinstance(r, dict)), key=score, default=None)
        if not best:
            return None
        meta = {
            "mst": str(best.get("법령일련번호") or best.get("MST") or ""),
            "law_name": str(best.get("법령명한글") or law_name),
            "law_id": str(best.get("법령ID") or ""),
            "effective_date": _normalize_date(str(best.get("시행일자") or "")),
            "source_url": _official_law_url(str(best.get("법령명한글") or law_name), ""),
        }
        if not meta["mst"]:
            return None
        self._mst_cache[cache_key] = meta
        return meta

    def resolve_public_url(self, law_name: str, article_no: str = "") -> str:
        """공개 URL 결정 — 정확한 lsInfoP 우선, 실패 시 검색 URL fallback.

        - LAW_OPEN_API_KEY 활성 + search_law 성공 → lsInfoP.do?lsiSeq=<mst> (정확 조문)
        - search 실패 (자율규제/감독표준 등 law.go.kr 미등록) → lsSc.do?query=<name> (검색)
        - 캐싱: search_law 내부 `_mst_cache` 재사용
        """
        if self.enabled:
            try:
                meta = self.search_law(law_name)
                if meta and meta.get("mst"):
                    return _lsInfoP_url(
                        meta["mst"],
                        article_no=article_no,
                        effective_date=meta.get("effective_date", ""),
                    )
            except Exception:
                pass
        return _lsSc_search_url(law_name)

    def fetch_article(self, law_name: str, article_no: str) -> Optional[LawApiArticle]:
        """Fetch a single official article by law name + article number.

        Flow: lawSearch(query=law_name) → MST → lawService(MST) → recursive
        article parser. Any external/API failure returns None so callers keep the
        deterministic local KB fallback.
        """
        if not self.enabled:
            return None
        meta = self.search_law(law_name)
        if not meta:
            return None
        params = {
            "OC": self.api_key,
            "target": "law",
            "MST": meta["mst"],
            "type": "JSON",
        }
        url = f"{API_BASE}?{urllib.parse.urlencode(params)}"
        def _fetch_article():
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")

        try:
            # 오류회복(가이드 제2장): 외부 read API → retry+timeout+circuit, 실패 시 None fallback.
            body = resilient_tool_call(
                _fetch_article, tool_name="law_open_api_fetch",
                idempotent=True, timeout_s=self.timeout, max_attempts=2,
            )
        except Exception:
            # 네트워크/타임아웃/SSL 등 모든 외부 오류는 silent fallback
            # (caller가 None → 로컬 KB로 fallback)
            return None
        return _parse_article_response(
            body,
            law_name=meta.get("law_name") or law_name,
            article_no=article_no,
            source_url=_official_law_url(meta.get("law_name") or law_name, article_no),
            fallback_effective_date=meta.get("effective_date", ""),
        )


def _parse_article_response(
    body: str,
    *,
    law_name: str,
    article_no: str,
    source_url: str,
    fallback_effective_date: str = "",
) -> Optional[LawApiArticle]:
    """법령정보센터 JSON 응답에서 단일 조문을 best-effort 파싱한다.

    law.go.kr 응답은 endpoint/target에 따라 `법령`, `조문`, `조문단위`, `조문내용`,
    `시행일자` 등의 위치가 달라질 수 있다. 이 함수는 recursive scan으로 article_no와
    일치하는 조문 후보를 찾고, 원문/시행일을 추출한다. 실제 운영에서는 이 함수를 기준으로
    계열사별 canonical cache에 저장하면 된다.
    """
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None

    normalized_target = _normalize_article_no(article_no)
    parsed_law_name = _first_payload_value(payload, ["법령명한글", "법령명", "law_name"]) or law_name
    for node in _walk_dicts(payload):
        node_article_no = _first_value(node, ["조문번호", "조문번호문자열", "article_no", "JO", "조번호"])
        if not node_article_no or _normalize_article_no(str(node_article_no)) != normalized_target:
            continue
        # law.go.kr also encodes chapter/section headings as `조문번호=N` with
        # `조문여부=전문`; skip those and keep actual article nodes.
        article_kind = str(_first_value(node, ["조문여부", "article_kind"]) or "")
        if article_kind and article_kind != "조문":
            continue
        text = _article_text(node)
        if not text:
            continue
        effective_date = _first_value(node, ["조문시행일자", "시행일자", "시행일", "공포일자", "effective_date"]) or fallback_effective_date
        return LawApiArticle(
            law_name=str(parsed_law_name),
            article_no=article_no,
            text=_clean_text(str(text)),
            effective_date=_normalize_date(str(effective_date)),
            source_url=source_url,
        )
    return None


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _first_value(node: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in node and node[key] not in (None, ""):
            return node[key]
    return None


def _first_payload_value(value: Any, keys: list[str]) -> Any:
    for node in _walk_dicts(value):
        found = _first_value(node, keys)
        if found not in (None, ""):
            return found
    return None


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _normalize_law_name(value: str) -> str:
    return "".join(value.replace("ㆍ", "·").lower().split())


def _normalize_article_no(value: str) -> str:
    normalized = str(value).replace("제", "").replace("조", "").replace("의", "-")
    normalized = normalized.strip().lower()
    return "".join(ch for ch in normalized if ch.isdigit() or ch == "-").strip("-") or _digits(value)


def _official_law_url(law_name: str, article_no: str) -> str:
    """Deprecated: 본 패턴(`/법령/<name>/<제N조>`)은 law.go.kr에서 "오류 페이지" 반환.
    호환을 위해 유지하되, 신규 코드는 `_lsInfoP_url` (정확) 또는 `_lsSc_search_url` (fallback) 사용.
    """
    quoted_law = urllib.parse.quote(str(law_name), safe="")
    if article_no:
        quoted_article = urllib.parse.quote(f"제{article_no}조", safe="")
        return f"https://www.law.go.kr/법령/{quoted_law}/{quoted_article}"
    return f"https://www.law.go.kr/법령/{quoted_law}"


def _lsInfoP_url(mst: str, article_no: str = "", effective_date: str = "") -> str:
    """정확한 법령 페이지 URL — lsiSeq(법령일련번호)로 직접 이동.

    예: https://www.law.go.kr/lsInfoP.do?lsiSeq=259548
    조문 anchor가 가능하면 `#%EC%A0%9C{N}%EC%A1%B0` 형식 추가.
    """
    base = f"https://www.law.go.kr/lsInfoP.do?lsiSeq={urllib.parse.quote(str(mst), safe='')}"
    if article_no:
        article_clean = _normalize_article_no(article_no)
        if article_clean and article_clean.isdigit():
            # law.go.kr 페이지 내 조문 anchor (best-effort, 페이지 구조 의존)
            base += f"#%EC%A0%9C{article_clean}%EC%A1%B0"
    return base


def _lsSc_search_url(law_name: str) -> str:
    """검색 URL fallback — 정확한 lsiSeq 모를 때 검색 결과 페이지로 이동.

    예: https://www.law.go.kr/lsSc.do?menuId=1&query=은행연합회%20자율규제
    자율규제/감독 표준처럼 law.go.kr 검색 가능한 외부 기준에 사용.
    """
    quoted = urllib.parse.quote(str(law_name), safe="")
    return f"https://www.law.go.kr/lsSc.do?menuId=1&query={quoted}"


def _article_text(node: dict[str, Any]) -> str:
    """Compose article heading + clauses/items from a law.go.kr 조문 node."""
    parts: list[str] = []
    for key in ["조문내용", "조문내용문자열", "내용", "text"]:
        value = node.get(key)
        if value:
            parts.append(str(value))
            break
    for child in _walk_dicts(node):
        if child is node:
            continue
        for key in ["항내용", "호내용", "목내용"]:
            value = child.get(key)
            if value:
                parts.append(str(value))
    return "\n".join(parts)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_date(value: str) -> str:
    digits = _digits(value)
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return value


def from_env() -> Optional[LawOpenApiClient]:
    """편의 팩토리. LAW_OPEN_API_KEY가 환경에 있으면 client, 없으면 None."""
    if not os.environ.get("LAW_OPEN_API_KEY"):
        return None
    return LawOpenApiClient()
