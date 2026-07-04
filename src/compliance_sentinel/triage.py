"""Pre-board reviewability triage gate.

인사/잡담/테스트 같은 비심의 입력을 6인 컴플라이언스 보드 앞단에서 걸러
'심의 대상 아님(NOT_APPLICABLE)'으로 차단한다.

설계 원칙 — 보수적(conservative) fail-safe:
  컴플라이언스에서는 false negative(걸러야 할 위반을 미심의)가 false positive(잡담을 오심의)보다
  훨씬 위험하다. 따라서 '애매하면 심의를 진행'한다. 명백한 잡담만 차단한다.

2층 구조:
  Layer 1 (결정론, 무료/즉시): 금융·심의 신호가 있으면 즉시 reviewable,
    명백한 인사/테스트/잡담은 junk, 그 외는 uncertain.
  Layer 2 (nano LLM, 선택): Layer 1이 junk/uncertain일 때만 1회 호출해 최종 판정.
    LLM 미설정/실패 시 → junk만 차단, uncertain은 fail-safe로 심의.

환경변수:
  CS_ENABLE_TRIAGE=0  → 게이트 완전 비활성 (항상 reviewable)
  CS_TRIAGE_LLM=0     → Layer 2 nano LLM 호출 비활성 (Layer 1 결정론만)
  CS_MODEL_SHALLOW    → Layer 2에 쓸 nano 모델 (기본 gpt-5.4-nano)
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from .classification import classify_input

_DecLayer = Literal["reviewable", "junk", "uncertain"]

# 명백한 비심의 토큰 (공백 제거·소문자화 후 완전일치 또는 짧은 입력 내 매칭).
_GREETING_TOKENS = {
    "안녕", "안녕하세요", "안녕하십니까", "반가워", "반갑습니다", "ㅎㅇ", "하이",
    "좋은아침", "좋은하루", "hi", "hello", "hey", "헬로", "여보세요",
}
_TEST_TOKENS = {
    "test", "테스트", "asdf", "ㅁㄴㅇㄹ", "ㅋㅋ", "ㅋㅋㅋ", "ㅎㅎ", "aaa", "aaaa",
    "1234", "12345", "...", "ttt", "abc", "123",
}
# 금융 신호가 전혀 없을 때 잡담으로 보는 일상 키워드.
_CHITCHAT_HINTS = (
    "맛집", "점심", "저녁", "메뉴", "날씨", "커피", "노래", "영화", "게임",
    "근처", "추천 좀", "뭐 먹", "심심", "놀자", "농담",
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", (text or "")).lower()


def _has_financial_signal(text: str) -> bool:
    """금융·마케팅·약관 심의가 필요할 법한 신호 존재 여부 (보수적: 넓게 인정)."""
    if classify_input(text) != "unknown":
        return True
    hints = (
        "금리", "대출", "카드", "보험", "펀드", "적금", "예금", "한도", "수수료",
        "우대", "가입", "약관", "광고", "출시", "이벤트", "혜택", "수익", "투자",
        "원금", "보장", "최저", "최고", "무료", "할인", "캐시백", "포인트",
        "%", "원)", "만원", "억원", "연 ", "월 ",
    )
    return any(h in (text or "") for h in hints)


def _deterministic_triage(text: str) -> _DecLayer:
    norm = _norm(text)
    if not norm:
        return "junk"
    if _has_financial_signal(text):
        return "reviewable"
    # 짧은 입력에서만 잡담/인사/테스트로 단정 (긴 글은 LLM/심의로 넘김).
    short = len(norm) <= 24
    if short:
        if norm in _GREETING_TOKENS or norm in _TEST_TOKENS:
            return "junk"
        if any(norm == t or norm.startswith(t) for t in _GREETING_TOKENS | _TEST_TOKENS):
            return "junk"
        if len(norm) <= 3:
            return "junk"
    if any(h in (text or "") for h in _CHITCHAT_HINTS) and len(norm) <= 40:
        return "junk"
    return "uncertain"


@dataclass(frozen=True)
class TriageResult:
    reviewable: bool
    reason: str
    layer: str          # "deterministic" | "llm" | "fail_safe" | "disabled"
    confidence: float


_TRIAGE_SYSTEM_ROLE = "triage"
_TRIAGE_USER_TEMPLATE = (
    "다음 입력이 금융 마케팅/약관 준법 '심의 대상'인지 판정하세요.\n"
    "심의 대상: 금융상품 광고문구, 약관/계약 조항, 거래 시나리오 등 준법 검토가 필요한 콘텐츠.\n"
    "심의 대상 아님: 단순 인사, 잡담, 테스트 문자열, 무관한 일상 질문 등.\n"
    "애매하면 반드시 reviewable=true 로 판정하세요 (보수적).\n"
    'JSON만 출력: {{"reviewable": true|false, "confidence": 0.0~1.0, "reason": "한 줄"}}\n\n'
    "입력:\n{text}"
)


def _llm_triage(text: str, client: Any | None) -> tuple[bool, float, str] | None:
    """Layer 2 nano 판정. (reviewable, confidence, reason) 또는 None(미가용)."""
    try:
        if client is None:
            from .llm_client import LLMClient

            client = LLMClient()
        if getattr(client, "deterministic", False):
            return None
        model = os.environ.get("CS_MODEL_SHALLOW", "gpt-5.4-nano")
        result = client.call(
            _TRIAGE_SYSTEM_ROLE,
            _TRIAGE_USER_TEMPLATE.format(text=(text or "")[:2000]),
            model=model,
            max_tokens=400,
            estimated_cost_usd=0.005,
            response_format={"type": "json_object"},
        )
        if getattr(result, "deterministic_fallback", False) or not getattr(result, "text", ""):
            return None
        data = json.loads(result.text)
        reviewable = bool(data.get("reviewable", True))
        conf = float(data.get("confidence", 0.5))
        reason = str(data.get("reason", ""))[:200].strip()
        # 보수적: 저신뢰 비심의 판정은 fail-safe로 심의 진행.
        if not reviewable and conf < 0.6:
            return (True, conf, f"저신뢰 비심의 판정 → fail-safe 심의 ({reason})")
        return (reviewable, conf, reason or ("심의 대상" if reviewable else "심의 대상 아님"))
    except Exception:
        return None


def triage_input(text: str, *, llm_client: Any | None = None) -> TriageResult:
    """입력이 심의 대상인지 판정. 보수적 fail-safe."""
    if os.environ.get("CS_ENABLE_TRIAGE", "1") == "0":
        return TriageResult(True, "triage 비활성", "disabled", 1.0)

    l1 = _deterministic_triage(text)
    if l1 == "reviewable":
        return TriageResult(True, "금융·심의성 콘텐츠 신호 감지", "deterministic", 1.0)

    # junk/uncertain → Layer 2 nano 판정 (가용 시 최종 결정).
    if os.environ.get("CS_TRIAGE_LLM", "1") != "0":
        verdict = _llm_triage(text, llm_client)
        if verdict is not None:
            reviewable, conf, reason = verdict
            return TriageResult(reviewable, reason, "llm", conf)

    # LLM 미가용 — 결정론 결과로 폴백.
    if l1 == "junk":
        return TriageResult(False, "명백한 비심의 입력(인사/잡담/테스트)", "deterministic", 0.9)
    return TriageResult(True, "fail-safe: 판정 불확실 → 심의 진행", "fail_safe", 0.5)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_not_applicable_report(
    input_text: str,
    triage: TriageResult,
    *,
    review_request_id: str | None = None,
) -> dict:
    """비심의 입력용 NOT_APPLICABLE 최종 리포트. 보드/검증을 실행하지 않는다."""
    rid = review_request_id or ""
    return {
        "review_type": "not_applicable",
        "approval_status": "NOT_APPLICABLE",
        "risk_level": "NONE",
        "confidence": "HIGH",
        "confidence_score": round(float(triage.confidence), 2),
        "language": "ko",
        "channel": "N/A",
        "product_type": "non_reviewable",
        "summary": (
            f"심의 대상이 아닙니다 — {triage.reason}. "
            "금융 광고/약관 등 준법 심의가 필요한 콘텐츠를 입력해 주세요."
        ),
        "findings": [],
        "evidence": [],
        "revision_suggestions": [],
        "revision_included": False,
        "board_diagnostics": {"triage_blocked": True, "board_skipped": True},
        "verifier_result": {"status": "PASSED", "notes": "triage: 6인 보드 미실행"},
        "audit_log_id": rid,
        "review_request_id": rid,
        "input_completeness": {"reviewable": False, "triage_layer": triage.layer},
        "raw_content": input_text,
        "redacted_content": input_text,
        "timestamp": _utc_now_iso(),
        "triage": {
            "reviewable": triage.reviewable,
            "reason": triage.reason,
            "layer": triage.layer,
            "confidence": triage.confidence,
        },
    }
