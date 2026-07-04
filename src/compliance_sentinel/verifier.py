from __future__ import annotations

from .knowledge_base import LawKnowledgeBase
from .models import AtomicClaim, Citation, Finding, VerifierResult


def extract_atomic_claims(findings: list[Finding]) -> list[AtomicClaim]:
    """FR-006 5 claims 분해 — existence/verbatim/applicability/effective_date/scope.

    2026-05-13 확장: C4 effective_date_check + C5 applicability_scope 추가하여
    spec.md §4 FR-006의 5 검증 항목과 1:1 정합.
    """
    claims: list[AtomicClaim] = []
    for finding in findings:
        citation = Citation(finding.law_name, finding.article_no, finding.citation_text)
        claims.extend([
            AtomicClaim(f"{finding.id}-C1", finding.id, "law_exists", citation, f"{finding.law_name} 제{finding.article_no}조 존재"),
            AtomicClaim(f"{finding.id}-C2", finding.id, "verbatim_match", citation, "인용문이 원문과 일치"),
            AtomicClaim(f"{finding.id}-C3", finding.id, "applicability", citation, finding.applicability_reason),
            AtomicClaim(f"{finding.id}-C4", finding.id, "effective_date_check", citation, f"{finding.law_name} 시행일 유효성"),
            AtomicClaim(f"{finding.id}-C5", finding.id, "applicability_scope", citation, finding.source_text),
        ])
    return claims


_USER_CITATION_MARKER = "(사용자 인용)"


def verify_claims(claims: list[AtomicClaim], kb: LawKnowledgeBase) -> list[VerifierResult]:
    results: list[VerifierResult] = []
    for claim in claims:
        article = kb.get_article(claim.citation.law_name, claim.citation.article_no)
        if claim.kind == "law_exists":
            if article:
                results.append(VerifierResult(claim.id, "PASS", "법령명과 조항이 지식베이스에 존재합니다."))
            else:
                results.append(VerifierResult(claim.id, "FAIL", "법령명 또는 조항 번호를 찾을 수 없습니다."))
        elif claim.kind == "verbatim_match":
            # 사용자 인용은 마커("(사용자 인용)") 포함 → 별도 처리 (revise 단계에서 원문으로 보정됨)
            is_user_citation = _USER_CITATION_MARKER in claim.citation.citation_text
            if not article:
                # law_exists에서 이미 FAIL 처리되므로 verbatim은 FAIL만 누적해도 무방
                results.append(VerifierResult(claim.id, "FAIL", "원문 조항이 없어 verbatim 비교 불가."))
            elif is_user_citation:
                # 사용자 인용은 verbatim text를 보유하지 않으므로 verbatim 검증을 면제하고 revise 단계에 원문 보정 위임
                results.append(VerifierResult(claim.id, "PARTIAL", "사용자 인용 — revise 단계에서 원문으로 보정 필요."))
            elif normalize_text(claim.citation.citation_text) == normalize_text(article.text):
                results.append(VerifierResult(claim.id, "PASS", "인용문이 원문과 일치합니다."))
            elif normalize_text(claim.citation.citation_text) in normalize_text(article.text) or normalize_text(article.text) in normalize_text(claim.citation.citation_text):
                results.append(VerifierResult(claim.id, "PARTIAL", "인용문이 원문 일부와만 일치합니다."))
            else:
                results.append(VerifierResult(claim.id, "FAIL", "인용문이 원문과 일치하지 않습니다."))
        elif claim.kind == "applicability":
            if article and has_applicability_signal(claim.statement):
                results.append(VerifierResult(claim.id, "PASS", "적용 논리 설명이 포함되어 있습니다."))
            else:
                results.append(VerifierResult(claim.id, "PARTIAL", "적용 논리는 인간 준법 검토가 필요합니다."))
        elif claim.kind == "effective_date_check":
            # FR-006 C4: 법령 시행일이 ISO date 형식 + 현재 이전이면 PASS
            if not article:
                results.append(VerifierResult(claim.id, "FAIL", "법령 부재로 시행일 검증 불가."))
            elif is_effective_date_valid(article.effective_date):
                results.append(VerifierResult(claim.id, "PASS", f"시행일 {article.effective_date} 유효."))
            else:
                results.append(VerifierResult(claim.id, "PARTIAL", f"시행일 {article.effective_date!r} 형식/시점 확인 필요."))
        elif claim.kind == "applicability_scope":
            # FR-006 C5: article.keywords 또는 law_name 토큰이 source_text에 1개+ overlap → PASS
            if not article:
                results.append(VerifierResult(claim.id, "FAIL", "법령 부재로 적용 범위 검증 불가."))
            elif has_scope_overlap(article, claim.statement):
                results.append(VerifierResult(claim.id, "PASS", "법령 keywords가 입력 문맥에 적용 가능."))
            else:
                results.append(VerifierResult(claim.id, "PARTIAL", "적용 범위 매칭이 약함 — 인간 준법 검토 권장."))
    return results


def apply_verifier_results(findings: list[Finding], results: list[VerifierResult]) -> None:
    by_finding: dict[str, list[VerifierResult]] = {}
    for result in results:
        finding_id = result.claim_id.split("-C", 1)[0]
        by_finding.setdefault(finding_id, []).append(result)
    for finding in findings:
        statuses = [result.status for result in by_finding.get(finding.id, [])]
        if statuses and all(status == "PASS" for status in statuses):
            finding.verifier_status = "PASS"
        elif any(status == "FAIL" for status in statuses):
            finding.verifier_status = "FAIL"
        else:
            finding.verifier_status = "PARTIAL"


def has_failures(results: list[VerifierResult]) -> bool:
    return any(result.status == "FAIL" for result in results)


def normalize_text(value: str) -> str:
    return "".join(value.split())


def has_applicability_signal(value: str) -> bool:
    return any(token in value for token in ["적용", "가능", "입력", "문구", "검토", "연결"])


def is_effective_date_valid(effective_date: str) -> bool:
    """FR-006 C4: 시행일이 ISO date(YYYY-MM-DD) 형식이고 현재 시점 이전이면 True.

    빈 문자열 또는 형식 오류는 False. 미래 일자(시행 예정)는 False (PARTIAL 처리됨).
    """
    if not effective_date or len(effective_date) < 8:
        return False
    try:
        # ISO date 또는 YYYY-MM-DD 형식 허용
        from datetime import datetime
        parsed = datetime.fromisoformat(effective_date.replace("Z", "+00:00")) if "T" in effective_date or "Z" in effective_date else datetime.strptime(effective_date[:10], "%Y-%m-%d")
        return parsed <= datetime.now()
    except (ValueError, TypeError):
        return False


def has_scope_overlap(article, source_text: str) -> bool:
    """FR-006 C5: 법령의 keywords 또는 law_name이 source_text에 1개+ 포함되면 True.

    finding.source_text가 입력 문맥의 snippet — 여기에 법령 주제어가 나오면 적용 가능 판단.
    """
    if not source_text:
        return False
    # law_name 자체가 source_text에 등장하면 명시적 인용 → PASS
    if article.law_name and article.law_name in source_text:
        return True
    # 또는 article.keywords 중 1개+ 등장
    for keyword in (article.keywords or []):
        if keyword and keyword in source_text:
            return True
    # 또는 law_name의 핵심 부분 (예: "개인정보보호법" → "개인정보") substring 매칭
    if article.law_name:
        core_token = article.law_name[:4] if len(article.law_name) >= 4 else article.law_name
        if core_token in source_text:
            return True
    return False
