"""사용자 입력 텍스트에서 명시적 법령 인용을 추출.

목적: prompt injection / hallucinated citation 시도를 verifier에 직접 주입하기 위함.
AC-002 "가짜 법령 조항 인용을 verifier가 실패 처리한다" 회복용.
"""
from __future__ import annotations

import re

from .models import Citation

# 법령명 단서. 본 MVP는 KB 6건 + 자주 등장하는 한국 금융 법령으로 화이트리스트화.
# Production에서는 KB 동기화 또는 LLM-based NER 권장.
KNOWN_LAW_TOKENS: list[str] = [
    "개인정보보호법",
    "신용정보의 이용 및 보호에 관한 법률",
    "신용정보법",
    "금융소비자보호법",
    "금융소비자 보호에 관한 법률",
    "전자금융거래법",
    "전자금융감독규정",
    "자본시장법",
    "자본시장과 금융투자업에 관한 법률",
    "금융광고 가이드라인",
]

# 별칭 → canonical mapping
LAW_ALIASES: dict[str, str] = {
    "신용정보법": "신용정보의 이용 및 보호에 관한 법률",
    "금융소비자 보호에 관한 법률": "금융소비자보호법",
    "자본시장과 금융투자업에 관한 법률": "자본시장법",
}

# "제N조" 또는 "제N조 제M항" 패턴
_ARTICLE_RE = re.compile(r"제\s*(\d+)\s*조(?:\s*제\s*(\d+)\s*항)?")


def extract_explicit_citations(text: str) -> list[Citation]:
    """사용자 입력에서 (법령명, 조항 번호) 쌍을 추출.

    같은 문장 내에서 법령명과 조항이 인접하면 페어링한다.
    조항만 있고 법령명이 멀거나 부재하면 무시 (false positive 회피).
    """
    citations: list[Citation] = []
    seen: set[tuple[str, str]] = set()

    for law_match in _law_iter(text):
        law_canonical = LAW_ALIASES.get(law_match.law, law_match.law)
        # 법령명 뒤 80자 윈도우 내에서 가장 가까운 조항 찾기
        window_end = min(len(text), law_match.end + 80)
        window = text[law_match.end:window_end]
        article_match = _ARTICLE_RE.search(window)
        if not article_match:
            continue
        article_no = article_match.group(1)
        key = (law_canonical, article_no)
        if key in seen:
            continue
        seen.add(key)
        citations.append(Citation(
            law_name=law_canonical,
            article_no=article_no,
            citation_text=f"{law_canonical} 제{article_no}조 (사용자 인용)",
            source_url="user_input://",
        ))
    return citations


class _LawMatch:
    __slots__ = ("law", "end")

    def __init__(self, law: str, end: int) -> None:
        self.law = law
        self.end = end


def _law_iter(text: str):
    # 긴 토큰 우선 (substring 충돌 방지) — 예: "금융소비자 보호에 관한 법률"이 "금융소비자보호법"보다 먼저 매칭 시도
    for token in sorted(KNOWN_LAW_TOKENS, key=len, reverse=True):
        start = 0
        while True:
            idx = text.find(token, start)
            if idx < 0:
                break
            yield _LawMatch(token, idx + len(token))
            start = idx + len(token)
