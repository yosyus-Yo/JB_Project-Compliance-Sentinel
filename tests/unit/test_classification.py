"""M3 Classifier 단위 테스트.

대상: src/compliance_sentinel/classification.py
  - classify_input(text) -> InputType
    카테고리: advertisement / terms / contract / transaction_scenario / unknown

LLM 호출 없음 (rule-based keyword matching only).
"""
from __future__ import annotations

import pytest

from compliance_sentinel.classification import classify_input


class TestAdvertisementClassification:
    """광고 카테고리 keyword 매칭."""

    @pytest.mark.parametrize(
        "text",
        [
            "원금 보장 무위험 확정 수익 광고",
            "100% 승인 대출 캠페인",
            "이벤트 혜택 안내",
            "최저금리 적금 출시",
            "신규 예금 가입 안내",
        ],
    )
    def test_korean_advertisement_keywords(self, text):
        assert classify_input(text) == "advertisement"

    @pytest.mark.parametrize(
        "text",
        [
            "guaranteed profit for everyone",
            "zero risk return",
            "loan approved instantly",
            "best rate offer",
        ],
    )
    def test_english_advertisement_keywords(self, text):
        assert classify_input(text) == "advertisement"

    @pytest.mark.parametrize(
        "text",
        [
            "保证收益 안내",                # 중국어
            "lợi nhuận chắc chắn 안내",     # 베트남어
            "untung pasti 안내",            # 인도네시아어
            "全員 대상",                    # 일본어
        ],
    )
    def test_multilingual_advertisement_keywords(self, text):
        assert classify_input(text) == "advertisement"

    @pytest.mark.parametrize(
        "text",
        [
            # 상품 키워드 없는 압박형 다크패턴 문구 — advertisement로 분류되어야 마케팅 심의
            # (다크패턴 탐지)를 받는다. 이전엔 unknown으로 빠져 심의를 우회하던 결함(2026-07-04).
            "선착순 50명! 지금 신청 안 하면 후회합니다. 이미 3,240명이 가입했어요.",
            "마지막 기회! 놓치면 평생 후회",
            "지금 바로 서두르세요",
            "1,234명이 신청 중",
            "무료 증정 이벤트",
        ],
    )
    def test_pressure_dark_pattern_signals_classified_as_ad(self, text):
        assert classify_input(text) == "advertisement", (
            f"압박형 문구가 advertisement로 분류 안 됨 → 마케팅 심의 우회: {text!r}"
        )


class TestTermsClassification:
    @pytest.mark.parametrize(
        "text",
        [
            "약관 제14조 개인정보 제3자 제공",
            "본 약관은 회사가 제공하는 서비스 동의를 받습니다",
            "보유기간은 5년입니다",
        ],
    )
    def test_terms_keywords(self, text):
        assert classify_input(text) == "terms"


class TestContractClassification:
    @pytest.mark.parametrize(
        "text",
        [
            "본 계약서는 손해배상을 명시합니다",
            "계약 해지 시 위약금이 발생합니다",
        ],
    )
    def test_contract_keywords(self, text):
        assert classify_input(text) == "contract"


class TestTransactionScenario:
    @pytest.mark.parametrize(
        "text",
        [
            "AML 자금세탁 의심 거래 모니터링",
            "송금 대상 처리 필요",
            "입금 출금 한도 안내",
        ],
    )
    def test_transaction_keywords(self, text):
        assert classify_input(text) == "transaction_scenario"

    def test_조회_falls_to_terms_due_to_조_overlap(self):
        """'조회'의 '조'가 terms keyword('조')에 먼저 매칭됨 — 실제 함수 동작 확인.
        classification.py에서 advertisement → terms → contract → transaction 순서이며,
        terms 키워드에 '조'가 단독 등장."""
        # 함수 우선순위상 '조' 글자가 들어가면 terms 우선
        assert classify_input("입금 출금 한도 조회") == "terms"


class TestUnknownClassification:
    """매칭 안 되는 일반 텍스트 → unknown."""

    @pytest.mark.parametrize(
        "text",
        [
            "오늘 날씨가 좋습니다",
            "회의 시간을 알려주세요",
            "",
        ],
    )
    def test_unknown_fallback(self, text):
        assert classify_input(text) == "unknown"


class TestPriorityOrder:
    """여러 카테고리 keyword 동시 매칭 시 우선순위."""

    def test_advertisement_wins_over_terms_when_both_present(self):
        # advertisement 키워드가 함수 본문에서 가장 먼저 검사됨
        text = "약관 제14조 — 100% 승인 이벤트"
        result = classify_input(text)
        # advertisement 키워드 ("이벤트", "승인")가 본문 첫 줄에서 매칭
        assert result == "advertisement"

    def test_terms_wins_over_contract_when_no_ad(self):
        text = "약관 제2조에 따라 계약을 체결합니다"
        assert classify_input(text) == "terms"
