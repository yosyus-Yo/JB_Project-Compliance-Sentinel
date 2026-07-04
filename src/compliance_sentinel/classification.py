from __future__ import annotations

from .models import InputType


def classify_input(text: str) -> InputType:
    lowered = text.lower()
    if any(token in text for token in ["광고", "이벤트", "혜택", "원금", "수익", "캠페인", "배너", "앱푸시", "푸시", "대출", "승인", "금리", "적금", "예금", "零风险", "保证收益", "所有客户", "không rủi ro", "lợi nhuận", "được duyệt", "元本保証", "必ず利益", "全員", "tanpa risiko", "untung pasti", "disetujui"]):
        return "advertisement"
    # 보험/펀드/카드 마케팅 광고 신호 (상품 특화 키워드 — 약관에는 드문 위반/홍보 표현 위주)
    if any(token in text for token in [
        # 보험
        "보험", "보장", "무심사", "환급금", "종신", "실손", "무배당", "보험료", "면책",
        # 펀드/투자
        "펀드", "수익률", "투자", "신탁", "운용", "자산", "증권", "포트폴리오",
        # 카드
        "카드", "캐시백", "할부", "적립", "포인트", "연회비",
    ]):
        return "advertisement"
    if any(token in lowered for token in ["guaranteed", "zero risk", "return", "profit", "everyone", "loan", "approved", "rate"]):
        return "advertisement"
    if any(token in text for token in ["약관", "제", "조", "동의", "제3자", "보유기간"]):
        return "terms"
    if any(token in text for token in ["계약", "계약서", "해지", "손해배상"]):
        return "contract"
    if any(token in text for token in ["거래", "송금", "입금", "출금", "자금세탁", "aml"]) or "aml" in lowered:
        return "transaction_scenario"
    return "unknown"
