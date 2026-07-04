from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

InputType = Literal["terms", "advertisement", "contract", "transaction_scenario", "unknown"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
Confidence = Literal["PERFECT", "VERIFIED", "PARTIAL", "FEEDBACK", "FAILED"]
Status = Literal["PASSED", "NEEDS_REVISION", "HUMAN_REVIEW_REQUIRED", "FAILED"]
VerifierStatus = Literal["PASS", "FAIL", "PARTIAL"]

# 자가교정 루프 최대 재시도 상한 (명세 "최대 3회 보드 재검토"). workflow._verify_with_retry가 참조.
# (원격 커밋 bbd8165가 workflow.py에 import만 추가하고 이 상수 정의를 누락 → 복구)
MAX_REVISE_RETRIES = 3


@dataclass(frozen=True)
class LawArticle:
    law_name: str
    article_no: str
    title: str
    text: str
    effective_date: str
    source_url: str
    keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PIIFinding:
    kind: str
    value: str
    start: int
    end: int
    replacement: str


@dataclass(frozen=True)
class Citation:
    law_name: str
    article_no: str
    citation_text: str
    source_url: str = ""


@dataclass
class Finding:
    id: str
    source_text: str
    issue: str
    law_name: str
    article_no: str
    citation_text: str
    applicability_reason: str
    suggested_revision: str
    verifier_status: VerifierStatus = "PARTIAL"
    # 위반 룰 식별/심각도/근거 — langgraph(advertisement) 경로 직렬화에서 누락되던 필드 복원.
    # 기본값 부여로 기존 Finding 생성처(약관/계약 경로 등) 호환 유지.
    rule_id: str = ""
    severity: str = "MEDIUM"
    evidence: str = ""


@dataclass(frozen=True)
class BoardOpinion:
    agent_id: str
    stance: str
    risk_level: RiskLevel
    rationale: str
    citations: list[Citation] = field(default_factory=list)


@dataclass(frozen=True)
class MinorityOpinion:
    """다수 의견과 다른 페르소나의 의견을 보존 (Error Cascade 방어, spec/error-cascade-defense.md)."""

    persona: str                # agent_id (e.g. "contrarian-agent")
    risk_level: RiskLevel       # 본 페르소나가 판정한 risk_level
    rationale: str              # 의견 본문
    why_minority: str           # "majority=LOW, 5 vs 1" 등 분리 이유


@dataclass(frozen=True)
class BoardDiagnostics:
    """Board 의견 분포 분석 결과 (Error Cascade 방어, spec/error-cascade-defense.md §5.1)."""

    risk_distribution: dict[str, int]                  # {"HIGH": 2, "MEDIUM": 3, "LOW": 1}
    majority_risk: RiskLevel                           # 가장 많이 등장한 risk
    disagreement_score: float                          # 0 (만장일치) ~ 1 (최대 충돌)
    minority_opinions: list[MinorityOpinion] = field(default_factory=list)
    requires_human_arbitration: bool = False           # trigger 3종
    contradiction_pairs: list[tuple[str, str]] = field(default_factory=list)
    audit_log_id: str = ""                             # state.audit_log_id 연결 (AC-ERR-008)


@dataclass
class AtomicClaim:
    id: str
    finding_id: str
    kind: Literal[
        "law_exists",
        "verbatim_match",
        "applicability",
        "effective_date_check",   # FR-006 C4 — 시행일/최신성 (2026-05-13 추가)
        "applicability_scope",    # FR-006 C5 — 적용 범위 (2026-05-13 추가)
    ]
    citation: Citation
    statement: str


@dataclass
class VerifierResult:
    claim_id: str
    status: VerifierStatus
    reason: str


@dataclass
class ComplianceState:
    input_text: str
    redacted_text: str = ""
    input_type: InputType = "unknown"
    pii_findings: list[PIIFinding] = field(default_factory=list)
    retrieved_context: list[LawArticle] = field(default_factory=list)
    user_cited_articles: list[Citation] = field(default_factory=list)
    board_opinions: dict[str, BoardOpinion] = field(default_factory=dict)
    board_diagnostics: BoardDiagnostics | None = None  # EC Phase B (spec/error-cascade-defense.md)
    ceo_draft: dict = field(default_factory=dict)
    atomic_claims: list[AtomicClaim] = field(default_factory=list)
    verifier_results: list[VerifierResult] = field(default_factory=list)
    routing_decision: dict = field(default_factory=dict)
    model_plan: dict = field(default_factory=dict)
    llm_calls: list[dict] = field(default_factory=list)
    cross_model_result: dict = field(default_factory=dict)
    short_term_memory: dict = field(default_factory=dict)
    long_term_memory: list[dict] = field(default_factory=list)
    rag_metadata: dict = field(default_factory=dict)
    retry_count: int = 0
    final_report: dict = field(default_factory=dict)
    audit_log_id: str = ""
    human_review_needed: bool = False
    trace: list[dict] = field(default_factory=list)

    def add_trace(self, node: str, **data: object) -> None:
        self.trace.append({"node": node, **data})


def to_plain(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_plain(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [to_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    return value
