"""Short/long-term memory + compliance RAG integration.

This module connects the existing `.cs-brain` long-term Brain and the optional
Qdrant+BGE-M3 retriever to the runtime workflow. It follows the AI-research-SKILLs
patterns used by this project:

- 15-rag: keyword fallback + optional dense retriever + RRF-style merge.
- 28-agent-memory: scoped, redacted session memory and long-term pattern recall.
- 36-self-evolving-learning-system: capture successful runtime outcomes into
  pending Brain patterns without overwriting readonly domain knowledge.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import cs_brain
from .knowledge_base import LawKnowledgeBase
from .models import ComplianceState, LawArticle
from .qdrant_retriever import QdrantRetriever, availability_report as qdrant_availability_report
from .retriever import retrieve_context as keyword_retrieve_context

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOCUMENT_RAG_PATH = PROJECT_ROOT / "data" / "knowledge_rag" / "financial_marketing_corpus.jsonl"


@dataclass(frozen=True)
class RAGBundle:
    law_articles: list[LawArticle]
    memory_hits: list[dict]
    metadata: dict


PROMPT_INJECTION_MEMORY_RE = re.compile(
    r"(?i)(ignore\s+(all\s+)?previous\s+instructions|disregard\s+(all\s+)?instructions|reveal\s+system\s+prompt|developer\s+message|new\s+instructions\s*:|act\s+as\s+DAN|you\s+are\s+now|<\|im_start\|>|\[INST\])"
)
URL_MEMORY_RE = re.compile(r"https?://[^\s'\"]+")


def _safe_snippet(value: str, limit: int = 220) -> str:
    """Return a single-line snippet suitable for audit/memory metadata.

    Runtime memory stores untrusted user input as evidence, not instructions.
    Prompt-injection phrases and URLs are neutralized before they enter the
    long-lived Brain staging area so security scanners and future agents do not
    treat red-team text as active instructions.
    """

    snippet = " ".join(value.split())
    snippet = PROMPT_INJECTION_MEMORY_RE.sub("[prompt-injection-redacted]", snippet)
    snippet = URL_MEMORY_RE.sub("[url-redacted]", snippet)
    return snippet[:limit]


def _article_key(article: LawArticle) -> tuple[str, str, str]:
    return (article.law_name, article.article_no, article.source_url)


def _rrf_merge(
    keyword_results: list[LawArticle],
    dense_results: list[LawArticle],
    *,
    limit: int,
    k: int = 60,
) -> list[LawArticle]:
    """Reciprocal Rank Fusion for keyword + dense law retrieval.

    The implementation is dependency-free and deterministic. It keeps original
    `LawArticle` objects and only fuses rankings when the dense retriever is
    actually enabled; otherwise callers use the keyword path directly.
    """

    article_by_key: dict[tuple[str, str, str], LawArticle] = {}
    scores: dict[tuple[str, str, str], float] = {}
    for results, weight in ((keyword_results, 0.45), (dense_results, 0.55)):
        for rank, article in enumerate(results, start=1):
            key = _article_key(article)
            article_by_key.setdefault(key, article)
            scores[key] = scores.get(key, 0.0) + weight * (1.0 / (k + rank))
    ranked = sorted(scores, key=lambda key: scores[key], reverse=True)
    return [article_by_key[key] for key in ranked[:limit]]


class ComplianceMemoryRAG:
    """Runtime memory/RAG adapter for Compliance Sentinel.

    Short-term memory is stored on `ComplianceState` for the current request.
    Long-term memory is read from `.cs-brain/project_brain.yaml` via BM25 search
    and new lessons are appended to `.cs-brain/pending_patterns.yaml`.
    """

    def __init__(
        self,
        *,
        kb: Optional[LawKnowledgeBase] = None,
        brain_path: Path = cs_brain.PROJECT_BRAIN,
        pending_path: Path = cs_brain.PENDING_PATTERNS,
        document_rag_path: Path | None = None,
        top_k_memory: int = 3,
        top_k_laws: int = 5,
    ) -> None:
        self.kb = kb or LawKnowledgeBase.from_json()
        self.brain_path = brain_path
        self.pending_path = pending_path
        env_rag_path = os.environ.get("CS_DOCUMENT_RAG_PATH")
        self.document_rag_path = document_rag_path or (Path(env_rag_path) if env_rag_path else DEFAULT_DOCUMENT_RAG_PATH)
        self.top_k_memory = top_k_memory
        self.top_k_laws = top_k_laws
        self.qdrant = QdrantRetriever(kb=self.kb)
        self._retrieve_cache: dict[tuple[str, int, str, int], tuple[list[LawArticle], list[dict], dict]] = {}

    def recall(self, state: ComplianceState, *, query_text: str | None = None) -> list[dict]:
        """Populate short-term and long-term memory fields on the state."""

        query = query_text or state.redacted_text or state.input_text
        hits: list[dict] = []
        history_hint = "(not-run)"
        try:
            results = cs_brain.search(query, top_k=self.top_k_memory, brain_path=self.brain_path)
            hits = [
                {
                    "pattern_id": r.pattern_id,
                    "score": r.score,
                    "context": r.context,
                    "content_snippet": r.content_snippet,
                    "status": r.status,
                    "readonly": r.readonly,
                }
                for r in results
            ]
            history_hint = cs_brain.analyze_history(query).hint_for_route
        except Exception as exc:  # defensive: memory must not break compliance review
            state.rag_metadata["memory_recall_error"] = f"{type(exc).__name__}:{str(exc)[:160]}"

        state.long_term_memory = hits
        state.short_term_memory.update({
            "query_snippet": _safe_snippet(query),
            "input_type": state.input_type,
            "memory_hit_count": len(hits),
            "recalled_pattern_ids": [hit["pattern_id"] for hit in hits],
            "history_hint": history_hint,
        })
        state.add_trace(
            "memory_recall",
            layer="long_term",
            hits=len(hits),
            pattern_ids=[hit["pattern_id"] for hit in hits],
        )
        return hits

    def retrieve_context(self, state: ComplianceState, *, query_text: str | None = None) -> RAGBundle:
        """Retrieve law context with keyword fallback and optional Qdrant dense path."""

        query = query_text or state.redacted_text or state.input_text
        try:
            rag_stat = self.document_rag_path.stat()
            rag_version = hash((rag_stat.st_mtime_ns, rag_stat.st_size))
        except FileNotFoundError:
            rag_version = 0
        backend_hint = "qdrant" if self.qdrant.enabled else "keyword"
        cache_key = (hashlib.sha256(query.encode("utf-8")).hexdigest()[:16], self.top_k_laws, backend_hint, rag_version)
        cached = self._retrieve_cache.get(cache_key)
        if cached:
            law_articles, document_chunks, cached_metadata = cached
            backend = str(cached_metadata.get("law_backend", backend_hint))
            state.rag_metadata["rag_cache_hit"] = True
        else:
            keyword_results = keyword_retrieve_context(query, self.kb, limit=self.top_k_laws)
            if self.qdrant.enabled:
                dense_results = self.qdrant.retrieve(query, limit=self.top_k_laws)
                law_articles = _rrf_merge(keyword_results, dense_results, limit=self.top_k_laws)
                backend = "hybrid_keyword_qdrant_rrf"
            else:
                law_articles = keyword_results
                backend = "keyword_fallback"
            from .knowledge_ingest import search_document_rag  # lazy import keeps `python -m ...knowledge_ingest` warning-free
            document_chunks = search_document_rag(query, rag_path=self.document_rag_path, limit=3)
            state.rag_metadata["rag_cache_hit"] = False
        state.short_term_memory["document_rag_chunks"] = [
            {"id": row.get("id"), "source": row.get("source"), "text_snippet": _safe_snippet(str(row.get("text", "")), 700), "score": row.get("score")}
            for row in document_chunks
        ]

        metadata = {
            "rag_pipeline": "law_keyword_or_qdrant_plus_brain_memory",
            "law_backend": backend,
            "qdrant_status": qdrant_availability_report(),
            "law_count": len(law_articles),
            "kb_coverage": self.kb.coverage_report(),
            "retrieved_law_provenance": [
                {
                    "law_name": article.law_name,
                    "article_no": article.article_no,
                    "effective_date": article.effective_date,
                    "source_url": _resolve_public_source_url(article),
                }
                for article in law_articles
            ],
            "document_rag_count": len(document_chunks),
            "memory_hit_count": len(state.long_term_memory),
            "ai_research_skill_patterns": [
                "15-rag: hybrid search + fallback",
                "28-agent-memory: scoped short/long-term memory",
                "36-self-evolving-learning-system: Brain capture",
            ],
        }
        self._retrieve_cache[cache_key] = (list(law_articles), [dict(row) for row in document_chunks], dict(metadata))
        state.rag_metadata.update(metadata)
        state.add_trace(
            "rag_retrieve_context",
            backend=backend,
            laws=[f"{article.law_name} 제{article.article_no}조" for article in law_articles],
            memory_hits=len(state.long_term_memory),
            document_chunks=len(document_chunks),
        )
        return RAGBundle(law_articles=law_articles, memory_hits=state.long_term_memory, metadata=metadata)

    def capture_outcome(self, state: ComplianceState) -> None:
        """Append a redacted runtime lesson to pending Brain patterns.

        Disable with `CS_MEMORY_CAPTURE=0` for deterministic tests or demos that
        must not write local runtime artifacts.
        """

        if os.environ.get("CS_MEMORY_CAPTURE", "1") == "0":
            state.add_trace("memory_capture", enabled=False, reason="CS_MEMORY_CAPTURE=0")
            return
        if not state.final_report:
            state.add_trace("memory_capture", enabled=False, reason="missing_final_report")
            return

        status = state.final_report.get("status", "UNKNOWN")
        risk = state.final_report.get("risk_level", "UNKNOWN")
        confidence = state.final_report.get("confidence", "UNKNOWN")
        should_capture, reason = _should_capture_outcome(state, status=str(status), risk=str(risk), confidence=str(confidence))
        if not should_capture:
            state.add_trace("memory_capture", enabled=False, reason=reason)
            return
        finding_objs = state.final_report.get("findings", []) or []
        law_refs = [f"{a.law_name} 제{a.article_no}조" for a in state.retrieved_context[:5]]
        pattern_ids = [hit.get("pattern_id") for hit in state.long_term_memory]
        classification = "failure" if status == "FAILED" else "success"
        context = f"{state.input_type} review outcome: {status}/{risk}/{confidence}"
        digest = _outcome_digest(state)
        # 실제 위반 매핑(표현→rule(severity))으로 content를 구성해 BM25 회상 품질을
        # 높인다. findings는 MarketingFinding/Finding 객체 (dict fallback 안전).
        # digest=는 끝에 유지 — _pending_contains_digest 중복 감지 키.
        violations = [_finding_signature(fobj) for fobj in finding_objs[:5]]
        # 품질 게이트(A): 위반·근거 법령·회상 패턴이 모두 없으면 학습 가치가 없어
        # 캡처하지 않는다. _should_capture_outcome의 risk/status noise 게이트와 별개로
        # content 자체의 학습가치를 검증한다.
        if not finding_objs and not law_refs and not pattern_ids:
            state.add_trace("memory_capture", enabled=False, reason="no_learnable_content")
            return
        runtime_confidence = _compute_outcome_confidence(confidence_grade=str(confidence), risk=str(risk))
        content = (
            f"위반={violations}; 근거={law_refs}; 판정={status}/{risk}/{confidence}; "
            f"회상={pattern_ids}; query='{_safe_snippet(state.redacted_text or state.input_text, 160)}'; "
            f"digest={digest}"
        )
        if _pending_contains_digest(self.pending_path, digest):
            state.add_trace("memory_capture", enabled=False, reason="duplicate_pending_digest", digest=digest)
            return
        try:
            pattern = cs_brain.capture(
                classification=classification,
                context=context,
                content=content,
                confidence=runtime_confidence,
                severity="critical" if risk == "CRITICAL" else "info",
                scenario_type="integration",
                readonly=True,
                tags=["runtime-memory", "rag", state.input_type, str(risk).lower(), "needs-approval"],
                pending_path=self.pending_path,
            )
            state.add_trace("memory_capture", enabled=True, pending_pattern_id=pattern.id, reason=reason, digest=digest)
        except Exception as exc:  # defensive: learning must not block the review
            state.add_trace("memory_capture", enabled=False, error=f"{type(exc).__name__}:{str(exc)[:160]}")

    def capture_process_outcome(self, state: ComplianceState, *, measured_latency_ms: float | None = None) -> None:
        """심의 *과정*(시스템 운영) 패턴을 자동 학습한다.

        결과 패턴(capture_outcome)은 법적 판단이라 HITL(needs-approval)을 거치는 반면,
        과정 패턴은 지연시간/RAG 효율/라우팅 신뢰도 같은 시스템 메트릭이라 틀려도 성능
        문제뿐 → 사람 개입 없이 자동 학습한다. SEAS 다요소 score(0.40/0.25/0.20/0.15) 차용.
        tag=["process","auto-learn"] (needs-approval 없음) → merge auto_only가 자동 승격.

        ``measured_latency_ms``: LLM cost tracker가 latency를 설정하지 않는 deterministic
        경로용 wall-clock fallback. per_node_cost를 오염시키지 않기 위해 인자로 전달받는다
        (LLM 경로의 실측 latency가 있으면 그쪽이 우선).
        """
        if os.environ.get("CS_MEMORY_CAPTURE", "1") == "0":
            return
        if not state.final_report:
            return
        totals = (state.final_report.get("per_node_cost") or {}).get("totals") or {}
        latency_ms = totals.get("latency_ms")
        # deterministic 경로(LLM 미사용)는 per_node_cost latency 미설정 → wall-clock fallback 사용
        if latency_ms is None:
            latency_ms = measured_latency_ms
        # 여전히 측정값이 없으면 과정 학습 skip (실측 데이터 필수)
        if latency_ms is None:
            state.add_trace("process_capture", enabled=False, reason="no_measured_latency")
            return
        signals = _process_signals(
            latency_ms=float(latency_ms),
            rag_cache_hit=state.rag_metadata.get("rag_cache_hit"),
            domain_conf=str(state.routing_decision.get("domain_confidence", "")),
            retry_count=int(state.retry_count or 0),
        )
        sig_digest = hashlib.sha256(signals["content"].encode("utf-8")).hexdigest()[:16]
        if _pending_contains_digest(self.pending_path, sig_digest):
            state.add_trace("process_capture", enabled=False, reason="duplicate_process_digest")
            return
        content = f"{signals['content']}; digest={sig_digest}"
        try:
            pattern = cs_brain.capture(
                classification=signals["classification"],
                context=f"{state.input_type} process metrics: {signals['classification']}",
                content=content,
                confidence=signals["confidence"],
                severity="info",
                scenario_type="testing",
                readonly=False,
                tags=["process", "system-metric", "auto-learn", state.input_type],
                pending_path=self.pending_path,
            )
            state.add_trace("process_capture", enabled=True, pending_pattern_id=pattern.id,
                            classification=signals["classification"], confidence=signals["confidence"])
        except Exception as exc:  # defensive: 과정 학습 실패가 심의를 막지 않음
            state.add_trace("process_capture", enabled=False, error=f"{type(exc).__name__}:{str(exc)[:160]}")


def _risk_rank(risk: str) -> int:
    return {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}.get(risk, 0)


# 검증 등급 → confidence 사다리 (SEAS confidence-ladder 대응).
# merge min_confidence=0.75 게이트와 연동: FEEDBACK/FAILED 등급은 0.75 미달로
# 자동 승격에서 제외되어 pending에 잔류한다. 0.82 고정이던 기존 값은 게이트를
# 항상 통과시켜 품질 필터를 무력화했다 (LP-CS 학습 기준 강화, 2026-06-09).
_CONFIDENCE_LADDER = {
    "PERFECT": 0.95,
    "VERIFIED": 0.88,
    "PARTIAL": 0.72,
    "FEEDBACK": 0.60,
    "FAILED": 0.45,
}


def _compute_outcome_confidence(*, confidence_grade: str, risk: str) -> float:
    """심의 검증 등급 + risk로 학습 패턴 confidence를 차등 산정.

    - 검증 등급(PERFECT~FAILED)을 사다리로 매핑 (미지값은 보수적 0.78)
    - CRITICAL 위반은 탐지 확실성이 높아 소폭 가산, LOW는 소폭 감산
    - 결과는 merge 품질 게이트(min_confidence=0.75)의 입력이 된다
    """
    base = _CONFIDENCE_LADDER.get(str(confidence_grade).upper(), 0.78)
    rank = _risk_rank(str(risk).upper())
    if rank >= 3:  # CRITICAL
        base = min(0.97, base + 0.03)
    elif rank == 0:  # LOW
        base = max(0.50, base - 0.05)
    return round(base, 3)


def _finding_field(fobj: Any, name: str) -> str:
    """MarketingFinding/Finding 객체 또는 dict에서 필드 안전 추출."""
    if isinstance(fobj, dict):
        return str(fobj.get(name, "") or "")
    return str(getattr(fobj, name, "") or "")


def _finding_signature(fobj: Any) -> str:
    """finding을 재사용 가능한 위반 시그니처(표현→rule(severity))로 직렬화.

    redact된 source_text 일부 + rule_id + severity. 다음 유사 심의에서 BM25로
    "이 표현을 이렇게 판정했다"를 직접 회상하기 위함 (digest 메타 대비 회상가치↑).
    """
    rid = _finding_field(fobj, "rule_id")
    sev = _finding_field(fobj, "severity")
    src = _finding_field(fobj, "source_text")
    src_short = _safe_snippet(src, 30) if src else ""
    return f"{src_short}→{rid}({sev})"


def _process_signals(
    *,
    latency_ms: float,
    rag_cache_hit: Any,
    domain_conf: str,
    retry_count: int,
    latency_threshold_ms: float = 15000.0,
) -> dict:
    """과정 메트릭을 SEAS 다요소 가중(0.40/0.25/0.20/0.15)으로 score + 분류.

    SEAS calculatePendingScore의 다요소 가중 사상을 과정 패턴에 차용 (단일 confidence
    보다 견고). 각 요소가 issue를 발생시키면 분류가 success→warning→failure로 강등된다.
    """
    issues: list[str] = []

    # latency (0.40) — 예상시간 초과
    if latency_ms > latency_threshold_ms:
        issues.append(f"latency_exceeded({latency_ms:.0f}ms)")
        latency_factor = 0.40
    else:
        latency_factor = 0.92

    # RAG (0.25) — cache miss는 비효율이나 정상 범위 (None=미측정도 보수적 처리)
    rag_factor = 0.92 if rag_cache_hit else 0.62

    # routing confidence (0.20)
    routing_factor = {"HIGH": 0.95, "MEDIUM": 0.80, "LOW": 0.55}.get(domain_conf.upper(), 0.70)
    if routing_factor < 0.60:
        issues.append(f"routing_low_conf({domain_conf})")

    # retry/loopback (0.15) — 과다 재시도는 수렴 실패
    if retry_count >= 3:
        issues.append(f"max_retry({retry_count})")
        retry_factor = 0.40
    elif retry_count > 0:
        retry_factor = max(0.50, 0.92 - retry_count * 0.15)
    else:
        retry_factor = 0.92

    # health_score = SEAS 다요소 가중(건강도). classification(success/warning/failure) 결정용.
    health = round(
        latency_factor * 0.40 + rag_factor * 0.25 + routing_factor * 0.20 + retry_factor * 0.15,
        3,
    )
    if issues and health < 0.65:
        classification = "failure"
    elif issues:
        classification = "warning"
    else:
        classification = "success"
    # confidence = 측정 *신뢰도* (건강도와 분리). 실패 패턴도 명확히 측정됐으면 학습 가치가
    # 높으므로 confidence를 낮추지 않는다 — 그렇지 않으면 실패 과정 패턴이 merge 게이트(0.75)
    # 에서 걸러지는 역효과. measured latency가 있는 한 baseline 0.85, routing 미측정 시만 감산.
    confidence = 0.85 if domain_conf.upper() in ("HIGH", "MEDIUM", "LOW") else 0.78
    content = (
        f"latency={latency_ms:.0f}ms; rag_cache_hit={rag_cache_hit}; routing_conf={domain_conf or 'NA'}; "
        f"retry={retry_count}; health={health}; issues={issues or '없음'}"
    )
    return {"classification": classification, "confidence": confidence, "content": content,
            "issues": issues, "health": health}


def _should_capture_outcome(state: ComplianceState, *, status: str, risk: str, confidence: str) -> tuple[bool, str]:
    """Quality gate for self-evolving memory capture.

    Clean LOW/MEDIUM pass outcomes are skipped by default to avoid pending Brain
    growth. Set `CS_MEMORY_CAPTURE_LOW_RISK=1` to capture every run.
    """

    if os.environ.get("CS_MEMORY_CAPTURE_LOW_RISK") == "1":
        return True, "low_risk_capture_enabled"
    if status in {"FAILED", "HUMAN_REVIEW_REQUIRED"}:
        return True, "review_required_or_failed"
    if _risk_rank(risk) >= 2:
        return True, "high_risk_or_above"
    if confidence in {"FAILED", "PARTIAL", "FEEDBACK"}:
        return True, "non_final_confidence"
    if state.long_term_memory:
        return True, "memory_was_applied"
    if state.short_term_memory.get("document_rag_chunks"):
        return True, "document_rag_was_applied"
    return False, "low_signal_clean_outcome"


def _outcome_digest(state: ComplianceState) -> str:
    payload = "|".join([
        state.input_type,
        str(state.final_report.get("status")),
        str(state.final_report.get("risk_level")),
        str(state.final_report.get("confidence")),
        _safe_snippet(state.redacted_text or state.input_text, 180),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _pending_contains_digest(path: Path, digest: str) -> bool:
    try:
        pending = cs_brain._load_yaml(path) or {}
    except Exception:
        return False
    for pattern in pending.get("pending_patterns") or []:
        if f"digest={digest}" in str(pattern.get("content", "")):
            return True
    return False


_LAW_API_CLIENT_SINGLETON = None  # lazy LawOpenApiClient (mst 캐시 재사용)


def _get_law_api_client():
    """LAW_OPEN_API_KEY 활성 시 module-level singleton 반환 (mst 캐시 공유)."""
    global _LAW_API_CLIENT_SINGLETON
    if _LAW_API_CLIENT_SINGLETON is not None:
        return _LAW_API_CLIENT_SINGLETON
    if not os.environ.get("LAW_OPEN_API_KEY"):
        return None
    try:
        from .law_open_api import LawOpenApiClient
        _LAW_API_CLIENT_SINGLETON = LawOpenApiClient()
        return _LAW_API_CLIENT_SINGLETON
    except Exception:
        return None


def _resolve_public_source_url(article) -> str:
    """retrieved_law_provenance에 노출할 공개 URL 결정 (옵션 C: lsInfoP 우선 + 검색 fallback).

    - 외부 http(s) URL → 그대로
    - JB 내부 기준 (jb-internal/, law_name 'JB ' prefix) → local:// 유지 (UI가 "내부 기준" 라벨 처리)
    - 공식 외부 기준 (local://verified-review-standards/ 등) + LAW_OPEN_API_KEY 활성:
        1. LawOpenApiClient.resolve_public_url(law_name, article_no) 호출
        2. search 성공 → lsInfoP.do?lsiSeq=<mst> (정확한 법령 페이지) ⭐
        3. search 실패 (자율규제/감독표준 등 law.go.kr 미등록) → lsSc.do?query=<name> (검색 fallback)
        4. 캐싱: client 내부 _mst_cache 재사용 (반복 호출 시 cheap)
    - LAW_OPEN_API_KEY 없음 → 원본 유지
    """
    url = getattr(article, "source_url", "") or ""
    if url.startswith(("http://", "https://")):
        return url
    # JB 내부 기준은 외부 검색 무의미 → local:// 유지 (UI의 "내부 기준" 분기로 처리)
    law_name = getattr(article, "law_name", "") or ""
    if "jb-internal" in url or law_name.startswith("JB "):
        return url
    # 공식 외부 기준 + API key 활성 → 옵션 C (lsInfoP 정확 fetch + 검색 fallback)
    if url.startswith("local://"):
        client = _get_law_api_client()
        if client is not None and client.enabled:
            try:
                article_no = getattr(article, "article_no", "") or ""
                return client.resolve_public_url(law_name, article_no)
            except Exception:
                # API 실패는 silent — 원본 local:// 유지
                pass
    return url
