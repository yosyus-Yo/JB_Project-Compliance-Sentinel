from __future__ import annotations

import asyncio
import json
import os
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel
except Exception:  # pragma: no cover - optional dependency fallback
    FastAPI = None  # type: ignore
    HTTPException = Exception  # type: ignore
    StreamingResponse = None  # type: ignore
    BaseModel = object  # type: ignore

from .agent_shield_bridge import enforce_input_guard
from .engine import analyze_batch_with_engine, analyze_with_engine, astream_review_events

WORKER_CONTRACT_VERSION = "2026-05-31-review-runtime-v2"


def _secret_state(name: str) -> dict[str, Any]:
    return {"present": bool(os.environ.get(name)), "source": "environment" if os.environ.get(name) else "unset"}


def _provider_credentials() -> dict[str, dict[str, Any]]:
    return {
        "openai": {**_secret_state("OPENAI_API_KEY"), "provider": "openai", "purpose": "primary_live_llm"},
        "openrouter": {**_secret_state("OPENROUTER_API_KEY"), "provider": "openrouter", "purpose": "independent_critic_or_openai_compatible_route"},
        "law_open_api": {**_secret_state("LAW_OPEN_API_KEY"), "provider": "law.go.kr", "purpose": "korean_statute_open_api"},
        "anthropic": {**_secret_state("ANTHROPIC_API_KEY"), "provider": "anthropic", "purpose": "direct_anthropic_route"},
        "google": {
            "present": bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")),
            "source": "environment" if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") else "unset",
            "provider": "google",
            "purpose": "gemini_route",
        },
    }

if FastAPI is not None:
    app = FastAPI(title="Compliance Sentinel Python Worker API", version="0.3.0")

    class AnalyzeRequest(BaseModel):
        text: str | None = None
        content: str | None = None
        metadata: dict[str, Any] | None = None
        language: str | None = None
        channel: str | None = None
        product_type: str | None = None
        target_audience: str | None = None
        prefer_langgraph: bool | None = None
        # 입력 시 "수정 제안 생성" 토글. True면 수정 원고/제안 생성, False(기본)면 심의만.
        include_revision: bool | None = None

    class FeedbackRequest(BaseModel):
        # 심의 리포트 상단 👍/👎 피드백. verdict: "good"(정확) | "bad"(오탐/오심)
        content: str | None = None
        verdict: str | None = None
        review_id: str | None = None

    class BatchAnalyzeRequest(BaseModel):
        items: list[str] | None = None
        metadata: dict[str, Any] | None = None
        prefer_langgraph: bool | None = None
        reuse_agents: bool | None = None

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "app": "compliance-sentinel-python-worker",
            "contract_version": WORKER_CONTRACT_VERSION,
            "pid": os.getpid(),
            "agent_reuse": os.environ.get("CS_DISABLE_AGENT_REUSE") != "1",
            "provider_credentials": _provider_credentials(),
            "runtime": {
                "live_profile": os.environ.get("CS_LIVE_REVIEW_PROFILE", "turbo"),
                "live_effort": os.environ.get("CS_LIVE_REVIEW_EFFORT", "profile_default"),
                "llm_runtime": os.environ.get("CS_ENABLE_LLM_RUNTIME", "0"),
                "llm_parallelism": os.environ.get("CS_LLM_PARALLELISM", "8"),
                "models": {
                    "shallow": os.environ.get("CS_MODEL_SHALLOW", "gpt-5.4-nano"),
                    "standard": os.environ.get("CS_MODEL_STANDARD", "gpt-5.4-mini"),
                    "deep": os.environ.get("CS_MODEL_DEEP", "gpt-5.5"),
                    "critic": os.environ.get("CS_MODEL_CRITIC", "gpt-5.5"),
                },
            },
        }

    @app.post("/analyze")
    def analyze(request: AnalyzeRequest) -> dict:
        return _analyze_request(request)

    @app.post("/review")
    def review(request: AnalyzeRequest) -> dict:
        return _analyze_request(request)

    @app.post("/review/stream")
    def review_stream(request: AnalyzeRequest):
        text = str(request.content if request.content is not None else request.text or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="text is required")
        return StreamingResponse(
            _sse_review_events(text, include_revision=bool(request.include_revision)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/rewrite")
    def rewrite(request: AnalyzeRequest) -> dict:
        """수정 광고 원고만 on-demand 생성 (심의 재실행 없이 원문 룰스캔 → rewrite).

        프론트 '수정 광고 원고 생성' 버튼 클릭 시 호출. 원문을 deterministic 룰로
        재스캔해 findings를 복원한 뒤 generate_marketing_rewrite(ad_copy_proposer) 1콜.
        그래프 내 호출과 입력(원문+findings+메타)이 동일하므로 품질 동일.
        """
        text = str(request.content if request.content is not None else request.text or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="text is required")
        return _rewrite_request(text)

    @app.post("/feedback")
    def feedback(request: FeedbackRequest) -> dict:
        """심의 리포트 👍/👎 사용자 피드백 → 자동 학습 루프에 '사람 검증' 신호 주입.

        good → success 패턴(confidence 0.95)으로 캡처 → merge 시 우선 승급(강화).
        bad  → failure 패턴으로 캡처 → 회피 학습(오탐 재발 방지).
        confidence 0.95(사람 검증)는 자동캡처 0.82보다 높아 merge 게이트(≥0.75) 우선 통과.
        """
        verdict = (request.verdict or "").strip().lower()
        if verdict not in ("good", "bad"):
            raise HTTPException(status_code=422, detail="verdict must be 'good' or 'bad'")
        text = str(request.content or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="content is required")
        return _feedback_request(text, verdict, request.review_id)

    @app.post("/batch")
    def batch_review(request: BatchAnalyzeRequest) -> dict:
        items = [str(item).strip() for item in (request.items or []) if str(item).strip()]
        if not items:
            raise HTTPException(status_code=422, detail="items are required")
        prefer_langgraph = request.prefer_langgraph
        if prefer_langgraph is None:
            prefer_langgraph = os.environ.get("USE_LANGGRAPH") == "1"
        reuse_agents = request.reuse_agents
        if reuse_agents is None:
            reuse_agents = True
        batch = analyze_batch_with_engine(
            items,
            prefer_langgraph=prefer_langgraph,
            reuse_agents=reuse_agents,
        )
        metadata = dict(request.metadata or {})
        results = []
        for result in batch.results:
            response = dict(result.state.final_report)
            response.setdefault("input_completeness", {})["provided_metadata"] = metadata
            response["execution_engine"] = result.engine
            if result.fallback_reason:
                response["engine_fallback_reason"] = result.fallback_reason
            response["bridge_runtime"] = {
                "mode": "fastapi-worker-batch",
                "pid": os.getpid(),
                "agent_reuse": reuse_agents,
            }
            results.append(response)
        return {
            "results": results,
            "batch": {
                "item_count": batch.item_count,
                "elapsed_seconds": batch.elapsed_seconds,
                "reused_agents": batch.reused_agents,
                "engine": batch.engine,
            },
        }

    async def _sse_review_events(text: str, *, include_revision: bool = False):
        """Yield SSE frames for the realtime review loader (T2).

        Emits one ``data:`` frame per node progress event produced by
        ``astream_review_events`` and a terminal ``event: result`` frame carrying
        the final report. When LangGraph is disabled the stream falls back to the
        deterministic invoke path and emits only the terminal result frame, so
        the compliance verdict is preserved regardless of streaming availability.
        """

        def _frame(payload: dict, event: str | None = None) -> str:
            data = json.dumps(payload, ensure_ascii=False)
            prefix = f"event: {event}\n" if event else ""
            return f"{prefix}data: {data}\n\n"

        # Secure-by-default: the streaming entrypoint must pass the same AgentShield
        # input guard as the non-stream paths (engine + legacy module helpers). The
        # LangGraph astream path bypasses analyze_with_engine, so without this the
        # default React UI (USE_LANGGRAPH=1 + /review/stream) would skip the guard.
        # A high-confidence injection is rejected before astream starts and the
        # schema-valid REJECTED report is emitted as the terminal result frame.
        blocked = enforce_input_guard(text)
        if blocked is not None:
            yield _frame(blocked, event="result")
            return

        try:
            async for ev in astream_review_events(text, include_revision=include_revision):
                if ev.get("status") == "result":
                    yield _frame(ev.get("result") or {}, event="result")
                else:
                    yield _frame(ev)
                # 스트리밍 flush: sync 그래프 노드(예: 15초 보드)가 이벤트루프를
                # 블록하기 전에 방금 방출한 프레임을 소켓으로 내보낼 기회를 준다.
                # 이게 없으면 앞 노드의 complete 프레임이 다음 느린 노드가 끝날
                # 때까지 버퍼에 갇혀 로더가 실제보다 늦게 넘어간다 (측정: step3 2.2s→8s).
                await asyncio.sleep(0)
        except RuntimeError:
            # LangGraph disabled/not installed → deterministic fallback (T5 contract).
            result = analyze_with_engine(text, prefer_langgraph=False, include_revision=include_revision)
            yield _frame(result.state.final_report or {}, event="result")
        except Exception as exc:  # pragma: no cover - defensive streaming guard
            yield _frame({"error": type(exc).__name__, "detail": str(exc)}, event="error")

    def _analyze_request(request: AnalyzeRequest) -> dict:
        text = str(request.content if request.content is not None else request.text or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="text is required")
        prefer_langgraph = request.prefer_langgraph
        if prefer_langgraph is None:
            prefer_langgraph = os.environ.get("USE_LANGGRAPH") == "1"
        result = analyze_with_engine(text, prefer_langgraph=prefer_langgraph, include_revision=bool(request.include_revision))
        response = dict(result.state.final_report)
        metadata = dict(request.metadata or {})
        for key in ("language", "channel", "product_type", "target_audience"):
            value = getattr(request, key)
            if value is not None:
                metadata[key] = value
        response.setdefault("input_completeness", {})["provided_metadata"] = {
            "language": metadata.get("language"),
            "channel": metadata.get("channel"),
            "product_type": metadata.get("product_type"),
            "target_audience": metadata.get("target_audience"),
        }
        response["execution_engine"] = result.engine
        if result.fallback_reason:
            response["engine_fallback_reason"] = result.fallback_reason
        response["bridge_runtime"] = {
            "mode": "fastapi-worker",
            "pid": os.getpid(),
            "agent_reuse": os.environ.get("CS_DISABLE_AGENT_REUSE") != "1",
        }
        return response

    def _rewrite_request(text: str) -> dict:
        """원문 → PII 마스킹 → 룰 재스캔(findings 복원) → rewrite 1콜.

        deterministic 룰이라 findings는 원래 심의와 동일 → rewrite 입력 동일 → 품질 동일.
        LLM 비활성(deterministic) 시 generate_marketing_rewrite가 None 반환.
        """
        from .pii import redact_pii
        from .llm_client import LLMClient
        from .budget_guard import from_env as budget_guard_from_env
        from .marketing_reviewer import review_marketing_content, generate_marketing_rewrite

        # Secure-by-default: the rewrite entrypoint feeds the original text into an
        # LLM (generate_marketing_rewrite), so it must pass the same AgentShield
        # input guard as the analysis entrypoints — a high-confidence injection is
        # rejected before any LLM call.
        blocked = enforce_input_guard(text)
        if blocked is not None:
            return {"rewrite": None, "blocked": True, "final_report": blocked, "findings_count": 0}

        redacted, _ = redact_pii(text)
        review = review_marketing_content(redacted)
        client = LLMClient(budget_guard=budget_guard_from_env())
        rewrite_result = generate_marketing_rewrite(
            redacted,
            review.findings,
            product_type=review.product_type,
            channel=review.channel,
            language=review.language,
            llm_client=client,
            role="ad_copy_proposer",
        )
        return {"rewrite": rewrite_result, "findings_count": len(review.findings)}

    def _feedback_request(text: str, verdict: str, review_id: str | None) -> dict:
        """👍/👎 피드백을 cs_brain 패턴으로 캡처 (사람 검증 신호)."""
        from .pii import redact_pii
        from . import cs_brain

        # Guard the learning-capture surface: a high-confidence injection in the
        # feedback text must not be persisted into cs_brain (memory poisoning).
        blocked = enforce_input_guard(text)
        if blocked is not None:
            return {"captured": False, "blocked": True, "final_report": blocked}

        redacted, _ = redact_pii(text)
        good = verdict == "good"
        classification = "success" if good else "failure"
        context = (
            "사용자 피드백: 심의 결과가 정확함(👍)" if good
            else "사용자 피드백: 심의 결과가 부정확함(👎 오탐/오심)"
        )
        content = (
            f"human_feedback={verdict}; review_id={review_id or '-'}; "
            f"query='{redacted[:160]}'"
        )
        pattern = cs_brain.capture(
            classification=classification,
            context=context,
            content=content,
            confidence=0.95,  # 사람 검증 → 자동캡처(0.82)보다 높아 merge 게이트 우선 통과
            severity="info" if good else "warning",
            scenario_type="integration",
            readonly=True,
            tags=["human-feedback", "thumbs-up" if good else "thumbs-down", "verified", verdict],
        )
        golden_case_id = None
        if not good:  # 👎 = 사람이 오심으로 검증 → 골든 회귀셋에 환류 (가이드: 골든셋 정체 방지)
            try:
                from .golden_regression import capture_production_failure

                golden_case_id = capture_production_failure(text, flagged_by="human_feedback")
            except Exception:
                golden_case_id = None
        return {
            "captured": True, "pattern_id": pattern.id, "classification": classification,
            "verdict": verdict, "golden_case_id": golden_case_id,
        }
else:
    app = None


def main() -> None:
    if app is None:
        raise RuntimeError("FastAPI/uvicorn dependencies are not installed. Install with `pip install -e .[api]`.")
    try:
        import uvicorn
    except Exception as exc:  # pragma: no cover - optional dependency fallback
        raise RuntimeError("uvicorn is not installed. Install with `pip install -e .[api]`.") from exc

    uvicorn.run(
        "compliance_sentinel.api:app",
        host=os.environ.get("CS_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("CS_API_PORT", "8765")),
        log_level=os.environ.get("CS_API_LOG_LEVEL", "warning"),
    )
