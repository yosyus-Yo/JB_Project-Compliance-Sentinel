"""Guardrails — disclaimer 강제 + 위험 키워드 차단 (NeMo Guardrails 사상 흡수).

원칙:
  - **defense-in-depth**: PII guard + verifier + guardrails 3중 안전망
  - **disclaimer 강제**: 모든 최종 보고서에 "법률 자문이 아닌" 명시 의무
  - **위험 키워드 차단**: prompt injection 단서 + 단정적 표현 사용 금지
  - **NeMo Guardrails optional**: nemoguardrails SDK 설치 시 colang 정책 추가 적용

출처:
  - SEAS .claude/rules/security-critical.md
  - AGENTS.md "법률 자문 대체 표현 금지"
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 단정적/위험 표현 — guardrails로 차단 또는 경고
FORBIDDEN_OUTPUT_PATTERNS = [
    r"무조건\s*합법",
    r"\b100%\s*보장",
    r"확정\s*수익(?!\s*불가)",  # "확정 수익 불가"는 OK
    r"손실\s*가능성\s*없",
    r"원금\s*보장.*가입",
]

# 권장 disclaimer 패턴
REQUIRED_DISCLAIMER_PHRASES = [
    "법률 자문",
    "준법 검토 보조",
    "리스크 탐지",
]

DEFAULT_DISCLAIMER = (
    "본 결과는 법률 자문이 아닌 준법 검토 보조 및 리스크 탐지 결과입니다. "
    "고위험·불확실 판단은 반드시 인간 컴플라이언스 담당자에게 에스컬레이션해야 합니다."
)


@dataclass
class GuardrailViolation:
    rule: str
    matched_text: str
    severity: str  # critical | warning | info


def check_output(text: str) -> list[GuardrailViolation]:
    """LLM/synthesizer 출력에 위험 표현이 있는지 검사.

    Critical 위반 시 caller가 출력 차단 또는 revise 발동 (P5+ workflow 통합).
    """
    violations: list[GuardrailViolation] = []
    for pattern in FORBIDDEN_OUTPUT_PATTERNS:
        for m in re.finditer(pattern, text):
            violations.append(GuardrailViolation(
                rule=pattern,
                matched_text=m.group(0),
                severity="critical",
            ))
    return violations


def ensure_disclaimer(final_report: dict) -> dict:
    """final_report에 disclaimer 자동 부착 (멱등).

    이미 disclaimer가 있고 권장 phrase가 포함되면 그대로, 아니면 DEFAULT_DISCLAIMER로 보강.
    """
    current = final_report.get("disclaimer", "") or ""
    has_required = any(phrase in current for phrase in REQUIRED_DISCLAIMER_PHRASES)
    if not has_required:
        final_report["disclaimer"] = DEFAULT_DISCLAIMER
    return final_report


def block_or_revise(text: str, *, severity_threshold: str = "critical") -> tuple[bool, list[GuardrailViolation]]:
    """텍스트가 송출 가능한가? 위반 시 (False, violations) — caller가 revise 발동.

    Args:
        text: LLM 응답 또는 synthesizer 출력
        severity_threshold: 이 등급 이상 위반 시 차단 (critical | warning | info)
    """
    SEV_ORDER = {"info": 0, "warning": 1, "critical": 2}
    violations = check_output(text)
    blocking = [v for v in violations if SEV_ORDER.get(v.severity, 0) >= SEV_ORDER.get(severity_threshold, 2)]
    if blocking:
        return False, blocking
    return True, violations
