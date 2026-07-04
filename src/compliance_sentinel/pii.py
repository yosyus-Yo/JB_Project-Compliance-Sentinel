from __future__ import annotations

import re

from .models import PIIFinding

# 한글 인접 시 Python `\b`가 풀리지 않는 문제(예: "com으로", "1234567과")를 회피.
# 영문/숫자/언더스코어 + ASCII '@' 등을 경계로 보고, 한글은 경계로 인정.
# ⚠️ 마침표(.)는 경계 문자집합에서 제외한다: 한국어 문어체는 문장을 마침표로 끝내므로
#    "...900101-1234567." 처럼 PII 뒤에 마침표가 오면 마스킹이 실패하던 치명 결함(2026-07-04)을
#    수정. 마침표를 delimiter로 인정하되, 영숫자/@/+/- 는 여전히 token 연속으로 보아 부분매칭·
#    8자리 오탐·이메일 오탐 방지는 유지된다.
_BOUNDARY_LEFT = r"(?:^|(?<=[^A-Za-z0-9_@+\-]))"
_BOUNDARY_RIGHT = r"(?=$|[^A-Za-z0-9_@+\-])"

PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("rrn", re.compile(_BOUNDARY_LEFT + r"\d{6}-[1-4]\d{6}" + _BOUNDARY_RIGHT)),
    # 신용카드: Visa/MC/JCB (4-4-4-4) + Amex (4-6-5). card를 account보다 먼저 매칭하여
    # 4-segment 카드번호가 3-segment account 패턴에 흡수되지 않도록 한다.
    ("card", re.compile(_BOUNDARY_LEFT + r"(?:\d{4}-\d{4}-\d{4}-\d{4}|\d{4}-\d{6}-\d{5})" + _BOUNDARY_RIGHT)),
    ("phone", re.compile(_BOUNDARY_LEFT + r"01[016789]-?\d{3,4}-?\d{4}" + _BOUNDARY_RIGHT)),
    ("email", re.compile(_BOUNDARY_LEFT + r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}" + _BOUNDARY_RIGHT)),
    ("account", re.compile(_BOUNDARY_LEFT + r"\d{2,6}-\d{2,6}-\d{2,8}" + _BOUNDARY_RIGHT)),
    ("name", re.compile(r"(?:고객명|성명|이름)\s*[:：]?\s*[가-힣]{2,4}")),
    ("name", re.compile(r"(?<![가-힣])(?:홍길동|김철수|김영희|이영희|박영수|최민수)(?![가-힣])")),
]

ACTIVE_HTML_PATTERN = re.compile(
    r"<\s*/?\s*(?:script|style|iframe|object|embed|svg|img|form|input|button|a|div|span)[^>]*>",
    re.IGNORECASE,
)


def detect_pii(text: str) -> list[PIIFinding]:
    findings: list[PIIFinding] = []
    occupied: list[range] = []
    for kind, pattern in PII_PATTERNS:
        for match in pattern.finditer(text):
            span = range(match.start(), match.end())
            if any(overlaps(span, used) for used in occupied):
                continue
            replacement = f"[{kind.upper()}_REDACTED_{len(findings) + 1}]"
            findings.append(PIIFinding(kind, match.group(0), match.start(), match.end(), replacement))
            occupied.append(span)
    return sorted(findings, key=lambda item: item.start)


def redact_pii(text: str) -> tuple[str, list[PIIFinding]]:
    findings = detect_pii(text)
    redacted = text
    for finding in reversed(findings):
        redacted = redacted[: finding.start] + finding.replacement + redacted[finding.end :]
    return redacted, findings


def neutralize_active_content(text: str) -> str:
    return ACTIVE_HTML_PATTERN.sub("[HTML_TAG_REDACTED]", text)


def overlaps(left: range, right: range) -> bool:
    return left.start < right.stop and right.start < left.stop
