from __future__ import annotations

from collections import Counter

from .models import BoardDiagnostics, BoardOpinion, Citation, LawArticle, MinorityOpinion, RiskLevel

_RISK_ORDER: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
_CONTRADICTION_GAP = 2  # risk_level 차이 ≥ 2 → 직접 모순 (LOW↔HIGH, MEDIUM↔CRITICAL, LOW↔CRITICAL)
_ARBITRATION_THRESHOLD = 0.5
_CONTRARIAN_AGENT_ID = "contrarian-agent"
_LLM_ROLE_TO_AGENT_ID = {
    "legal_counsel": "legal-counsel",
    "pipa_expert": "pipa-credit-info-expert",
    "consumer_protection": "consumer-protection-expert",
    "operational_risk": "aml-operational-risk-expert",
    "business_practicality": "business-practicality-expert",
    "contrarian": "contrarian-agent",
}


def run_compliance_board(text: str, context: list[LawArticle]) -> dict[str, BoardOpinion]:
    citations = [Citation(a.law_name, a.article_no, a.text, a.source_url) for a in context]
    return {
        "legal-counsel": legal_counsel(text, citations),
        "pipa-credit-info-expert": pipa_expert(text, citations),
        "consumer-protection-expert": consumer_expert(text, citations),
        "aml-operational-risk-expert": operational_risk(text, citations),
        "business-practicality-expert": business_practicality(text, citations),
        "contrarian-agent": contrarian(text, citations),
    }


def legal_counsel(text: str, citations: list[Citation]) -> BoardOpinion:
    risk = "MEDIUM" if any(k in text for k in ["약관", "계약", "동의", "중요한 사항"]) else "LOW"
    return BoardOpinion("legal-counsel", "법령·약관 구조 검토", risk, "법령 근거와 약관 문구의 명시성을 확인해야 합니다.", citations)


def pipa_expert(text: str, citations: list[Citation]) -> BoardOpinion:
    privacy_terms = ["개인정보", "개인신용정보", "신용정보", "민감정보", "고유식별", "제3자", "보유기간"]
    sensitive = any(k in text for k in privacy_terms) or ("동의" in text and any(k in text for k in ["개인", "신용", "제공", "마케팅 활용"]))
    return BoardOpinion(
        "pipa-credit-info-expert",
        "개인정보·신용정보 리스크 검토",
        "HIGH" if sensitive else "LOW",
        "개인정보 또는 개인신용정보 제공·활용은 명시적 동의와 목적·보유기간 고지가 핵심입니다." if sensitive else "명확한 개인정보 처리 리스크는 낮습니다.",
        [c for c in citations if c.law_name in ["개인정보보호법", "신용정보의 이용 및 보호에 관한 법률"]],
    )


def consumer_expert(text: str, citations: list[Citation]) -> BoardOpinion:
    high_terms = [
        "원금 보장", "무위험", "확정 수익", "중요한 사항", "설명",
        "100% 승인", "무조건 승인", "당일 무조건 승인", "승인 보장", "누구나 승인",
        "한도 무제한", "신용점수 무관", "심사 없이", "즉시 승인",
    ]
    risky = any(k in text for k in high_terms)
    return BoardOpinion(
        "consumer-protection-expert",
        "금융소비자 보호 및 광고 리스크 검토",
        "HIGH" if risky else "MEDIUM" if "광고" in text else "LOW",
        "소비자가 수익·위험·승인 가능성·조건을 오인할 표현이나 중요사항 설명 누락 여부를 검토해야 합니다." if risky else "소비자 보호 관점의 추가 검토가 필요합니다.",
        [c for c in citations if c.law_name in ["금융소비자보호법", "금융광고 가이드라인"]],
    )


def operational_risk(text: str, citations: list[Citation]) -> BoardOpinion:
    high_terms = ["인증 없이", "보안 인증 없이", "확인 생략", "AML 확인 생략", "심사 없이", "권한 우회"]
    medium_terms = ["접근", "권한", "거래", "보안", "시스템", "AML", "자금세탁", "즉시 거래"]
    high = any(k in text for k in high_terms)
    risky = high or any(k in text for k in medium_terms)
    return BoardOpinion(
        "aml-operational-risk-expert",
        "운영리스크·전자금융 안전성 검토",
        "HIGH" if high else "MEDIUM" if risky else "LOW",
        "접근통제, 거래 모니터링, 인증·심사 절차, 시스템 보호대책 여부를 확인해야 합니다." if risky else "운영리스크 직접 신호는 제한적입니다.",
        [c for c in citations if c.law_name in ["전자금융거래법", "전자금융감독규정"]],
    )


def business_practicality(text: str, citations: list[Citation]) -> BoardOpinion:
    return BoardOpinion(
        "business-practicality-expert",
        "실무 적용성 검토",
        "MEDIUM",
        "위반 가능성을 표시하되, 실제 업무 적용 전 준법 담당자의 최종 검토가 필요합니다.",
        citations[:2],
    )


def contrarian(text: str, citations: list[Citation]) -> BoardOpinion:
    return BoardOpinion(
        "contrarian-agent",
        "반대 의견 및 오판 가능성 검토",
        "MEDIUM",
        "문구 일부만으로 단정하면 과잉 판단일 수 있으므로 동의서·고지문·전체 약관 맥락을 함께 확인해야 합니다.",
        citations[:1],
    )


def apply_llm_advisory_to_board(
    opinions: dict[str, BoardOpinion],
    llm_calls: list[dict],
    *,
    enabled: bool = False,
) -> dict[str, BoardOpinion]:
    """Optionally let live LLM board verdicts influence persona risk levels.

    Deterministic rule opinions remain the default and the system never stores raw
    LLM text. Only parsed `risk_level` signals from successful advisory calls are
    folded into matching personas when the caller explicitly enables this path.
    """
    if not enabled:
        return opinions
    updated = dict(opinions)
    for call in llm_calls:
        if not call.get("called") or call.get("deterministic_fallback"):
            continue
        role = str(call.get("role", ""))
        risk = str(call.get("risk_level", ""))
        if risk not in _RISK_ORDER:
            continue
        agent_id = _LLM_ROLE_TO_AGENT_ID.get(role)
        if not agent_id or agent_id not in updated:
            continue
        previous = updated[agent_id]
        updated[agent_id] = BoardOpinion(
            agent_id=previous.agent_id,
            stance=previous.stance,
            risk_level=risk,  # type: ignore[arg-type]
            rationale=(
                f"LLM advisory parsed verdict applied without storing raw text "
                f"(role={role}, model={call.get('model')}, previous_rule_risk={previous.risk_level}). "
                f"Deterministic rationale: {previous.rationale}"
            ),
            citations=previous.citations,
        )
    return updated


def max_risk(opinions: dict[str, BoardOpinion]) -> RiskLevel:
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    return max((opinion.risk_level for opinion in opinions.values()), key=lambda r: order[r])


def diagnose_board(opinions: dict[str, BoardOpinion], *, audit_log_id: str = "") -> BoardDiagnostics:
    """Board 의견 분포를 분석하여 정보 손실 없이 충돌을 가시화한다.

    spec/error-cascade-defense.md §5 / EC-005~EC-008 / AC-ERR-001~008 구현.
    LLM 재호출 없이 deterministic 분기로 산출.
    """
    if not opinions:
        return BoardDiagnostics(
            risk_distribution={},
            majority_risk="LOW",
            disagreement_score=0.0,
            minority_opinions=[],
            requires_human_arbitration=False,
            contradiction_pairs=[],
            audit_log_id=audit_log_id,
        )

    risk_levels = [op.risk_level for op in opinions.values()]
    n = len(risk_levels)
    distribution = dict(Counter(risk_levels))

    # majority_risk — Counter.most_common은 동률 시 첫 등장 순서. 안정적 산출 위해 risk_order 보조 정렬
    max_count = max(distribution.values())
    candidates = [r for r, c in distribution.items() if c == max_count]
    # 동률이면 더 보수적인(높은 위험) 쪽 선택 — "준법 보조" 원칙
    majority_risk: RiskLevel = max(candidates, key=lambda r: _RISK_ORDER[r])

    # EC-006: disagreement_score = 1 - (max_count / N)
    disagreement_score = round(1.0 - (max_count / n), 4)

    # EC-003: minority_opinions — 다수 risk 와 다른 모든 페르소나
    minorities: list[MinorityOpinion] = [
        MinorityOpinion(
            persona=agent_id,
            risk_level=op.risk_level,
            rationale=op.rationale,
            why_minority=f"majority={majority_risk}, {max_count} vs {n - max_count}",
        )
        for agent_id, op in opinions.items()
        if op.risk_level != majority_risk
    ]

    # EC-008: contradiction_pairs — risk_level 차이 ≥ 2
    agent_ids = list(opinions.keys())
    contradictions: list[tuple[str, str]] = []
    for i in range(len(agent_ids)):
        for j in range(i + 1, len(agent_ids)):
            a, b = agent_ids[i], agent_ids[j]
            gap = abs(_RISK_ORDER[opinions[a].risk_level] - _RISK_ORDER[opinions[b].risk_level])
            if gap >= _CONTRADICTION_GAP:
                contradictions.append((a, b))

    # EC-007: requires_human_arbitration — 3 trigger
    levels_set = set(risk_levels)
    extreme_split = ("HIGH" in levels_set or "CRITICAL" in levels_set) and "LOW" in levels_set
    high_disagreement = disagreement_score >= _ARBITRATION_THRESHOLD
    contrarian_op = opinions.get(_CONTRARIAN_AGENT_ID)
    contrarian_warns = bool(
        contrarian_op
        and majority_risk in ("LOW", "MEDIUM")
        and _RISK_ORDER[contrarian_op.risk_level] > _RISK_ORDER[majority_risk]
    )
    requires_arbitration = extreme_split or high_disagreement or contrarian_warns

    return BoardDiagnostics(
        risk_distribution=distribution,
        majority_risk=majority_risk,
        disagreement_score=disagreement_score,
        minority_opinions=minorities,
        requires_human_arbitration=requires_arbitration,
        contradiction_pairs=contradictions,
        audit_log_id=audit_log_id,
    )
