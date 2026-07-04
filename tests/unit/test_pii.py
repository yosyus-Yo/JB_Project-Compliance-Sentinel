"""M2 PII Guard 단위 테스트.

대상: src/compliance_sentinel/pii.py
  - PII_PATTERNS (rrn / card / phone / email / account)
  - detect_pii(text) -> list[PIIFinding]
  - redact_pii(text) -> (redacted_text, findings)

Bug #1 회귀 방지: 카드번호 4-4-4-4가 3-segment account에 흡수되지 않도록 card 우선 매칭.
"""
from __future__ import annotations

import pytest

from compliance_sentinel.pii import PII_PATTERNS, detect_pii, redact_pii


class TestPIIPatterns:
    """기본 5종 PII 패턴 인식."""

    def test_rrn_detection(self):
        text = "주민번호 900101-1234567 확인"
        findings = detect_pii(text)
        assert len(findings) == 1
        assert findings[0].kind == "rrn"
        assert findings[0].value == "900101-1234567"

    def test_phone_detection(self):
        text = "연락처 010-1234-5678 입니다"
        findings = detect_pii(text)
        assert len(findings) == 1
        assert findings[0].kind == "phone"
        assert findings[0].value == "010-1234-5678"

    def test_email_detection(self):
        text = "이메일 user@example.com 송부"
        findings = detect_pii(text)
        assert len(findings) == 1
        assert findings[0].kind == "email"
        assert findings[0].value == "user@example.com"

    def test_account_detection(self):
        text = "계좌 123-456-789012 송금"
        findings = detect_pii(text)
        assert len(findings) == 1
        assert findings[0].kind == "account"

    def test_no_pii_returns_empty(self):
        findings = detect_pii("일반 텍스트입니다")
        assert findings == []


class TestCardPattern:
    """Bug #1 회귀 방지 — card가 account보다 먼저 매칭되어야 함."""

    def test_visa_card_4_4_4_4(self):
        text = "카드 4111-1111-1111-1111"
        findings = detect_pii(text)
        assert len(findings) == 1
        assert findings[0].kind == "card", "4-4-4-4 카드번호는 account로 흡수되면 안 됨"
        assert findings[0].value == "4111-1111-1111-1111"

    def test_amex_card_4_6_5(self):
        text = "Amex 3742-454556-37000"
        findings = detect_pii(text)
        assert len(findings) == 1
        assert findings[0].kind == "card"

    def test_card_not_swallowed_by_account(self):
        """4-4-4-4가 3-segment account 패턴에 흡수되지 않는지 직접 검증."""
        text = "1234-5678-9012-3456"
        findings = detect_pii(text)
        assert len(findings) == 1
        # account는 \d{2,6}-\d{2,6}-\d{2,8}이라 처음 3 segment만 잡으면 잘못
        assert findings[0].kind == "card"
        assert findings[0].end == len(text)  # 전체 길이 매칭


class TestRedactPii:
    """redact_pii — 마스킹 + 인덱스 + 다중 PII 처리."""

    def test_single_pii_replacement(self):
        text = "주민번호 900101-1234567"
        redacted, findings = redact_pii(text)
        assert "[RRN_REDACTED_1]" in redacted
        assert "900101-1234567" not in redacted
        assert len(findings) == 1

    def test_multiple_pii_numbered(self):
        text = "홍길동 900101-1234567 010-1234-5678 user@example.com"
        redacted, findings = redact_pii(text)
        # name(홍길동) PII 패턴 추가로 findings 4건 (name/rrn/phone/email)
        assert len(findings) == 4
        assert "[RRN_REDACTED_1]" in redacted
        assert "[PHONE_REDACTED_2]" in redacted
        assert "[EMAIL_REDACTED_3]" in redacted
        assert "[NAME_REDACTED_4]" in redacted
        # 원본 PII 절대 노출 안 됨
        assert "홍길동" not in redacted
        assert "900101-1234567" not in redacted
        assert "010-1234-5678" not in redacted
        assert "user@example.com" not in redacted

    def test_empty_text_returns_empty(self):
        redacted, findings = redact_pii("")
        assert redacted == ""
        assert findings == []

    def test_no_pii_returns_unchanged(self):
        text = "일반 약관입니다"
        redacted, findings = redact_pii(text)
        assert redacted == text
        assert findings == []


class TestKoreanBoundary:
    """한글 어미 인접 시에도 PII 정확 인식 (LP-CS PII 한글 경계 fix)."""

    @pytest.mark.parametrize(
        "text,raw_pii",
        [
            ("문의는 010-1234-5678로 연락주세요.", "010-1234-5678"),
            ("주민번호 900101-1234567과 함께 보냈습니다.", "900101-1234567"),
            ("연락처 user@example.com으로 알려주세요.", "user@example.com"),
            ("계좌 123-456-789012로 송금하세요.", "123-456-789012"),
        ],
    )
    def test_korean_postposition_does_not_break_match(self, text, raw_pii):
        redacted, findings = redact_pii(text)
        assert len(findings) >= 1, f"한글 인접 PII 미탐지: {text!r}"
        assert raw_pii not in redacted, f"한글 인접 PII 마스킹 실패: {text!r}"


class TestTrailingPunctuationBoundary:
    """Bug #2 회귀 방지 (2026-07-04): PII가 마침표 등 문장부호로 끝나면 마스킹 실패하던 치명 결함.

    원인: 경계 정규식이 마침표(.)를 word-continuation 문자로 취급 → 한국어 문어체 문장 끝
    "...900101-1234567." 에서 RRN/전화/카드가 마스킹되지 않고 감사로그에 평문 저장됨.
    """

    @pytest.mark.parametrize(
        "text, raw_pii",
        [
            ("고객 주민번호는 900101-1234567.", "900101-1234567"),
            ("연락처 010-1234-5678.", "010-1234-5678"),
            ("카드 1234-5678-9012-3456.", "1234-5678-9012-3456"),
            ("문의 test@example.com.", "test@example.com"),
            ("계좌 123-456-7890.", "123-456-7890"),
            # 마침표 + 뒤 문장 이어짐
            ("주민번호 900101-1234567. 확인 바랍니다.", "900101-1234567"),
            # 다른 문장부호도 정상 (기존 동작 보존 확인)
            ("주민번호(900101-1234567), 확인", "900101-1234567"),
        ],
    )
    def test_pii_masked_before_sentence_ending_period(self, text, raw_pii):
        redacted, findings = redact_pii(text)
        assert len(findings) >= 1, f"문장부호 종료 PII 미탐지: {text!r}"
        assert raw_pii not in redacted, f"문장부호 종료 PII 마스킹 실패(평문 잔존): {text!r}"

    def test_period_does_not_cause_email_false_positive_as_rrn(self):
        # 이메일 뒤 마침표가 RRN 등으로 오탐되지 않아야 (경계 완화의 부작용 방지)
        redacted, findings = redact_pii("메일 a@b.com.")
        kinds = {f.kind for f in findings}
        assert "email" in kinds
        assert "rrn" not in kinds and "account" not in kinds

    def test_alphanumeric_boundary_still_prevents_partial_match(self):
        # 영숫자 인접 시 부분매칭 방지는 유지되어야 (8자리 뒤 숫자 → RRN 오탐 방지)
        _, findings = redact_pii("코드900101-12345678끝")
        assert all(f.value != "900101-1234567" for f in findings)


class TestPatternRegistry:
    """PII_PATTERNS 구조 검증 — 향후 패턴 추가 시 회귀 방지."""

    def test_card_before_account_in_registry(self):
        """card 정규식이 account보다 먼저 와야 first-match wins 보장됨."""
        kinds = [kind for kind, _ in PII_PATTERNS]
        assert "card" in kinds
        assert "account" in kinds
        assert kinds.index("card") < kinds.index("account")

    def test_all_6_kinds_registered(self):
        kinds = {kind for kind, _ in PII_PATTERNS}
        assert kinds == {"rrn", "card", "phone", "email", "account", "name"}
