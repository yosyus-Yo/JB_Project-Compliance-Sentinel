from __future__ import annotations

from .knowledge_base import LawKnowledgeBase
from .models import LawArticle

KEYWORD_EXPANSIONS = {
    "개인정보": ["개인정보보호법", "제3자", "동의", "보유", "개인정보보호 내부 통제 기준", "마스킹"],
    "신용정보": ["신용정보", "개인신용정보", "동의"],
    "광고": ["금융광고", "오인", "원금 보장", "무위험", "필수 고지", "혜택·위험 균형 표시"],
    "마케팅": ["금융광고", "필수 고지", "다국어", "로컬라이징", "승인 상태"],
    "다국어": ["외국어", "로컬라이징", "금지 표현", "MULTILINGUAL-LOCALIZATION"],
    "약관": ["금융소비자보호법", "설명의무", "중요한 사항", "준법심의 업무 기준"],
    "승인": ["human review", "최종 승인", "HITL-APPROVAL"],
    "감사": ["감사 로그", "입력 해시", "AUDIT-TRACE"],
    "보안": ["전자금융", "접근통제", "보호대책", "개인정보 최소화"],
}


def retrieve_context(text: str, kb: LawKnowledgeBase, *, limit: int = 5) -> list[LawArticle]:
    expanded = [text]
    for key, terms in KEYWORD_EXPANSIONS.items():
        if key in text:
            expanded.extend(terms)
    return kb.search(" ".join(expanded), limit=limit)
