from __future__ import annotations

from .board import max_risk
from .models import BoardOpinion, Citation, Finding


def synthesize_opinion(
    text: str,
    opinions: dict[str, BoardOpinion],
    *,
    user_citations: list[Citation] | None = None,
) -> dict:
    findings: list[Finding] = []
    finding_id = 1
    seen: set[tuple[str, str]] = set()

    # 1. 사용자가 명시한 인용을 먼저 finding으로 등재 → verifier가 직접 검증 (AC-002)
    for citation in user_citations or []:
        key = (citation.law_name, citation.article_no)
        if key in seen:
            continue
        seen.add(key)
        findings.append(Finding(
            id=f"F-{finding_id:03d}",
            source_text=snippet(text),
            issue=f"사용자 입력이 {citation.law_name} 제{citation.article_no}조를 인용 — 실재성·원문 일치·적용 논리 검증 필요",
            law_name=citation.law_name,
            article_no=citation.article_no,
            citation_text=citation.citation_text,
            applicability_reason="사용자가 직접 인용한 조항이므로 verifier 통과 시에만 결론으로 사용합니다.",
            suggested_revision="존재하지 않거나 원문과 다른 인용이면 사용자에게 즉시 알리세요.",
        ))
        finding_id += 1

    for opinion in opinions.values():
        if opinion.risk_level == "LOW":
            continue
        for citation in opinion.citations:
            key = (citation.law_name, citation.article_no)
            if key in seen:
                continue
            seen.add(key)
            issue = issue_for(citation.law_name, text)
            findings.append(Finding(
                id=f"F-{finding_id:03d}",
                source_text=snippet(text),
                issue=issue,
                law_name=citation.law_name,
                article_no=citation.article_no,
                citation_text=citation.citation_text,
                applicability_reason=applicability_for(citation.law_name),
                suggested_revision=revision_for(citation.law_name),
            ))
            finding_id += 1

    if not findings:
        findings.append(Finding(
            id="F-001",
            source_text=snippet(text),
            issue="명확한 고위험 위반 신호는 낮지만 준법 담당자의 문맥 검토가 필요합니다.",
            law_name="금융소비자보호법",
            article_no="19",
            citation_text="금융상품판매업자등은 일반금융소비자에게 계약 체결을 권유하는 경우 금융상품의 중요한 사항을 설명하여야 한다.",
            applicability_reason="금융 문서의 중요사항 설명 누락 여부는 기본 점검 항목입니다.",
            suggested_revision="중요 조건, 비용, 위험, 해지 조건을 별도 항목으로 명확히 고지하세요.",
        ))

    return {
        "risk_level": max_risk(opinions),
        "summary": "6인 컴플라이언스 보드 검토 결과, 주요 법령 인용과 수정 필요 후보를 도출했습니다.",
        "findings": findings,
        "disclaimer": "본 결과는 법률 자문이 아닌 준법 검토 보조 및 리스크 탐지 결과입니다.",
    }


def snippet(text: str, limit: int = 240) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def issue_for(law_name: str, text: str) -> str:
    if "개인정보" in law_name:
        return "개인정보 제3자 제공 또는 동의 절차 명시성 부족 가능성"
    if "신용정보" in law_name:
        return "개인신용정보 제공·활용 동의 요건 검토 필요"
    if "금융소비자" in law_name:
        return "중요사항 설명의무 또는 소비자 오인 가능성 검토 필요"
    if "광고" in law_name:
        return "원금 보장·무위험·확정 수익 등 오인 광고 표현 가능성"
    if "전자금융" in law_name:
        return "전자금융 안전성·접근통제·보호대책 검토 필요"
    return "준법 리스크 검토 필요"


def applicability_for(law_name: str) -> str:
    if "개인정보" in law_name or "신용정보" in law_name:
        return "입력 문구에 개인정보/신용정보의 제공·활용 또는 동의와 관련된 표현이 포함되어 적용 가능성이 있습니다."
    if "금융소비자" in law_name:
        return "금융상품 권유·계약·광고 문구에서 중요사항 설명 여부와 연결됩니다."
    if "광고" in law_name:
        return "광고 문구가 소비자에게 보장/무위험으로 오인될 수 있는지 확인합니다."
    return "입력 문구의 업무 맥락에 따라 적용 가능성이 있습니다."


def revision_for(law_name: str) -> str:
    if "개인정보" in law_name or "신용정보" in law_name:
        return "제공받는 자, 제공 목적, 항목, 보유·이용 기간, 거부권 및 불이익을 분리해 명시하고 별도 동의를 받도록 수정하세요."
    if "금융소비자" in law_name:
        return "수수료, 위험, 해지 조건, 원금 손실 가능성 등 중요사항을 명확히 표시하세요."
    if "광고" in law_name:
        return "원금 보장·무위험·확정 수익 표현을 삭제하고 손실 가능성과 조건을 균형 있게 표시하세요."
    return "관련 통제 절차와 책임 주체를 명확히 표시하세요."
