from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from .content_standards import load_marketing_standards
from .marketing_models import Channel, Language, MarketingFinding, MarketingReview, ProductType, RevisionSuggestion
from .pii import neutralize_active_content, redact_pii
from .workflow_publishers import build_jira_payload, build_notion_payload, build_slack_payload

if TYPE_CHECKING:
    from .llm_client import LLMClient


CLAIM_TAXONOMY_PATTERNS: dict[str, list[str]] = {
    "subjective_puffery": ["든든", "스마트", "혁신", "편리", "최적", "안심 서비스"],
    "factual_numeric": [r"\b\d+(?:\.\d+)?%", r"연\s*\d+(?:\.\d+)?%", r"월\s*\d+(?:\.\d+)?%", r"\d+만\s*명"],
    "comparative_superlative": ["업계 최고", "국내 최고", "업계 최저", "최저 금리", "1위", "유일", "타사 대비", "best", "lowest", "only"],
    "implied_safety": ["걱정 없이", "부담 없이", "안심하고 투자", "손실 걱정", "safe alternative", "secure alternative"],
    "absolute_guarantee": ["100% 안전", "100% 보장", "절대 손실", "항상 수익", "무조건 혜택", "never lose", "always profitable"],
}

PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore (all )?(previous|above) instructions"),
    re.compile(r"(?i)disregard (all )?(previous|above)"),
    re.compile(r"(?i)(system|developer) prompt"),
    re.compile(r"(?i)you are now"),
    re.compile(r"(?i)switch to developer mode"),
]
SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\s*[:=]\s*[^\s]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
]
URL_PATTERN = re.compile(r"https?://[^\s)\]>\"']+")
SOURCE_ALLOWLIST_DOMAINS = {"law.go.kr", "open.law.go.kr", "fsc.go.kr", "fss.or.kr", "pipc.go.kr", "jbfg.com"}


def detect_language(text: str) -> Language:
    lowered = text.lower()
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if any(token in lowered for token in ["không", "lợi nhuận", "được", "rủi ro", "vay"]):
        return "vi"
    if any(token in lowered for token in ["untung", "tanpa risiko", "nasabah", "disetujui"]):
        return "id"
    if re.search(r"[a-zA-Z]", text) and any(token in lowered for token in ["guaranteed", "zero risk", "everyone", "return", "profit"]):
        return "en"
    if re.search(r"[가-힣]", text):
        return "ko"
    return "unknown"


def classify_channel(text: str) -> Channel:
    lowered = text.lower()
    if any(k in text for k in ["푸시", "앱푸시", "알림"]) or "push" in lowered:
        return "app_push"
    if any(k in text for k in ["배너", "banner"]):
        return "banner"
    if any(k in text for k in ["sns", "인스타", "페이스북", "해시태그", "#"]):
        return "sns"
    if any(k in text for k in ["이메일", "메일"]) or "email" in lowered:
        return "email"
    if any(k in text for k in ["랜딩", "landing"]):
        return "landing_page"
    if any(k in text for k in ["약관", "고지", "설명서"]):
        return "notice"
    return "banner"


def classify_product(text: str) -> ProductType:
    """상품 유형 분류 — 신호 점수 합산 방식 (최고 점수 선택).

    early-return 방식은 'JB 슈퍼적금'에 '승인'/'자동차'(footer copyright) 같은
    약신호가 섞이면 loan으로 오분류된다. 점수제로 명시적 상품명(+3)에 가중치를 두고,
    적금/대출 공통어('승인'/'입금')는 단독 분류 신호에서 제외한다.
    """
    lowered = text.lower()
    scores: dict[str, int] = {"deposit": 0, "loan": 0, "card": 0, "investment": 0, "insurance": 0}

    # 강신호: 명시적 상품명 (+3)
    if any(k in text for k in ["적금", "예금", "정기예금", "자유적금", "입출금통장"]):
        scores["deposit"] += 3
    if any(k in text for k in ["대출", "오토론", "캐피탈", "할부", "여신"]) or any(k in lowered for k in ["loan", "auto loan", "installment", "vay", "disetujui"]):
        scores["loan"] += 3
    if any(k in text for k in ["신용카드", "체크카드"]) or "카드" in text:
        scores["card"] += 3
    if any(k in text for k in ["펀드", "ETF", "주식", "투자상품"]):
        scores["investment"] += 3
    if "보험" in text:
        scores["insurance"] += 3

    # 약신호: 보조 키워드 (+1) — 단독으로는 분류 근거 불충분
    if any(k in text for k in ["금리", "우대금리", "예금자보호"]):
        scores["deposit"] += 1
    if any(k in text for k in ["신용점수", "신용등급", "심사", "상환"]):
        scores["loan"] += 1
    if any(k in text for k in ["캐시백", "포인트", "전월 실적"]):
        scores["card"] += 1
    if any(k in text for k in ["수익", "손실", "수익률"]) or any(k in lowered for k in ["return", "profit", "yield"]):
        scores["investment"] += 1

    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return "unknown"  # type: ignore[return-value]
    return best  # type: ignore[return-value]


def classify_content_type(product_type: ProductType) -> str:
    return {
        "deposit": "deposit_ad",
        "loan": "loan_ad",
        "card": "card_event",
        "investment": "investment_ad",
        "insurance": "insurance_ad",
    }.get(product_type, "generic_financial_ad")


def _severity_rank(severity: str) -> int:
    return {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}.get(severity, 0)


def _domain_allowed(url: str) -> bool:
    domain = urlparse(url).netloc.lower().split(":", 1)[0]
    return bool(domain) and any(domain == allowed or domain.endswith(f".{allowed}") for allowed in SOURCE_ALLOWLIST_DOMAINS)


def runtime_guard_findings(text: str, *, language: Language, channel: Channel, product_type: ProductType) -> tuple[list[MarketingFinding], dict]:
    findings: list[MarketingFinding] = []
    flags = {
        "prompt_injection_detected": False,
        "secret_like_token_detected": False,
        "non_allowlisted_url_count": 0,
        "blocked": False,
    }
    if any(pattern.search(text) for pattern in PROMPT_INJECTION_PATTERNS):
        flags["prompt_injection_detected"] = True
        findings.append(MarketingFinding(
            id="MF-GUARD-001",
            rule_id="RUNTIME_PROMPT_INJECTION_GUARD",
            severity="CRITICAL",
            evidence="prompt_injection_pattern",
            issue="실시간 심의 입력에 prompt injection 지시문이 포함되어 결과 신뢰성을 훼손할 수 있습니다.",
            rationale="준법 심의 hot path에서는 시스템/개발자 지시를 우회하려는 입력을 차단해야 합니다.",
            suggested_revision="심의 대상 콘텐츠만 남기고 모델 지시문·프롬프트 조작 문구를 제거한 뒤 재요청하세요.",
            language=language,
            channel=channel,
            product_type=product_type,
            verifier_status="FAIL",
            law_name="Runtime Guard",
            article_no="PROMPT-INJECTION",
            citation_text="실시간 입력은 prompt injection, secret, 비허용 URL 여부를 검사하고 위해성이 높으면 사람 검토 또는 차단으로 라우팅합니다.",
            source_text=text[:240],
            applicability_reason="사용자 입력에 모델 지시문 우회 패턴이 포함되어 심의 결과 오염 가능성이 있습니다.",
        ))
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        flags["secret_like_token_detected"] = True
        findings.append(MarketingFinding(
            id=f"MF-GUARD-{len(findings)+1:03d}",
            rule_id="RUNTIME_SECRET_GUARD",
            severity="CRITICAL",
            evidence="secret_like_token",
            issue="실시간 심의 입력에 secret/API token 형태 문자열이 포함되어 있습니다.",
            rationale="원문 secret은 trace/report/audit에 보존되면 안 되며, 즉시 제거 후 재요청해야 합니다.",
            suggested_revision="API key, token, password 등 비밀값을 삭제하고 필요한 경우 redacted placeholder만 사용하세요.",
            language=language,
            channel=channel,
            product_type=product_type,
            verifier_status="FAIL",
            law_name="Runtime Guard",
            article_no="SECRET-REDACTION",
            citation_text="PII/secret 원문은 심의·보고·감사 로그에 보존하지 않고 redaction 또는 차단합니다.",
            source_text=text[:240],
            applicability_reason="입력에 secret-like token이 포함되어 정보 유출 위험이 있습니다.",
        ))
    unsafe_urls = [url for url in URL_PATTERN.findall(text) if not _domain_allowed(url)]
    flags["non_allowlisted_url_count"] = len(unsafe_urls)
    if unsafe_urls:
        findings.append(MarketingFinding(
            id=f"MF-GUARD-{len(findings)+1:03d}",
            rule_id="RUNTIME_URL_ALLOWLIST_GUARD",
            severity="HIGH",
            evidence="non_allowlisted_url",
            issue="허용 도메인이 아닌 URL이 포함되어 외부 연결/출처 리스크가 있습니다.",
            rationale="금융 심의 입력의 외부 링크는 공식/허용 출처인지 확인해야 합니다.",
            suggested_revision="공식 출처 URL만 남기거나 링크를 제거하고 내부 검토자가 출처를 확인하세요.",
            language=language,
            channel=channel,
            product_type=product_type,
            verifier_status="PARTIAL",
            law_name="Runtime Guard",
            article_no="URL-ALLOWLIST",
            citation_text="외부 URL은 허용 도메인 또는 공식 출처인지 검사하고, 미확인 링크는 human review로 라우팅합니다.",
            source_text=text[:240],
            applicability_reason="비허용 도메인 URL이 포함되어 출처 신뢰성 확인이 필요합니다.",
        ))
    flags["blocked"] = any(f.severity == "CRITICAL" for f in findings)
    return findings, flags


def rule_based_review(text: str, *, language: Language, channel: Channel, product_type: ProductType) -> list[MarketingFinding]:
    standards = load_marketing_standards()
    findings: list[MarketingFinding] = []
    lowered = text.lower()
    matched_rules: set[str] = set()
    for rule in standards.get("forbidden_expressions", []):
        rid = rule.get("id", "UNKNOWN_RULE")
        if rid in matched_rules:
            continue
        for pattern in rule.get("patterns", []):
            if pattern.lower() not in lowered:
                continue
            # 룰의 매칭된 *모든* 표현을 각각 finding으로 승격 — 다국어 위반(같은 rule의 여러 언어
            # 예: ZERO_RISK의 'zero risk'+'không rủi ro'+'零风险')을 전부 탐지/감사 추적한다.
            # (이전: 룰당 1건 노이즈 억제 → 다국어 혼합 콘텐츠에서 첫 언어 외 누락)
            # source_text를 입력 앞부분(text[:240])이 아니라 '매칭된 표현 주변'으로 잡아
            # 긴 입력에서도 위반 위치를 정확히 인용한다 (이전: 모든 finding이 앞 240자로 동일).
            idx = lowered.find(pattern.lower())
            ctx_start = max(0, idx - 30)
            ctx_end = min(len(text), idx + len(pattern) + 60)
            ctx = " ".join(text[ctx_start:ctx_end].split())
            src = f"{'…' if ctx_start > 0 else ''}{ctx}{'…' if ctx_end < len(text) else ''}"
            rationale = rule.get("rationale", "소비자 오인 가능성이 있습니다.")
            findings.append(MarketingFinding(
                id=f"MF-{len(findings)+1:03d}",
                rule_id=rule.get("id", "UNKNOWN_RULE"),
                severity=rule.get("severity", "MEDIUM"),
                evidence=pattern,
                # issue는 룰별 구체 사유(rationale)로 채워 '왜 위반인지'를 명확히 한다.
                issue=f"'{pattern}': {rationale}",
                rationale=rationale,
                suggested_revision=rule.get("suggested_revision", "조건과 제한사항을 명확히 고지하세요."),
                language=language,
                channel=channel,
                product_type=product_type,
                source_text=src,
                # 실제 법령·조문을 룰에서 매핑 (이전: 기본값 "금융광고 심의 기준"/"CONTENT-RULE").
                law_name=rule.get("law_name", "금융광고 심의 기준"),
                article_no=rule.get("article_no", rule.get("id", "CONTENT-RULE")),
                verifier_status="FAIL" if rule.get("severity") == "CRITICAL" else "PARTIAL",
            ))
            matched_rules.add(rid)
    return findings


def classify_claim_taxonomy(text: str) -> list[dict[str, str]]:
    """마케팅 문구를 법무 검토형 claim taxonomy로 분해한다.

    Claude for Legal의 marketing-claims-review 패턴을 금융광고에 맞춰 축소 적용한다.
    taxonomy 자체는 근거 메타데이터이고, 고위험 claim만 finding으로 승격한다.
    """
    lowered = text.lower()
    claims: list[dict[str, str]] = []
    for claim_type, patterns in CLAIM_TAXONOMY_PATTERNS.items():
        for pattern in patterns:
            matched = re.search(pattern, text, flags=re.IGNORECASE) if pattern.startswith("\\b") or "\\s" in pattern else pattern.lower() in lowered
            if matched:
                evidence = matched.group(0) if hasattr(matched, "group") else pattern
                claims.append({
                    "type": claim_type,
                    "evidence": evidence,
                    "substantiation_required": "true" if claim_type != "subjective_puffery" else "false",
                })
                break
    return claims


def add_claim_taxonomy_findings(
    text: str,
    findings: list[MarketingFinding],
    *,
    language: Language,
    channel: Channel,
    product_type: ProductType,
) -> list[MarketingFinding]:
    claims = classify_claim_taxonomy(text)
    existing_evidence = {f.evidence for f in findings}
    for claim in claims:
        claim_type = claim["type"]
        evidence = claim["evidence"]
        if evidence in existing_evidence or claim_type not in {"comparative_superlative", "implied_safety", "absolute_guarantee"}:
            continue
        severity = "HIGH" if claim_type == "absolute_guarantee" else "MEDIUM"
        findings.append(MarketingFinding(
            id=f"MF-{len(findings)+1:03d}",
            rule_id=f"CLAIM_TAXONOMY_{claim_type.upper()}",
            severity=severity,
            evidence=evidence,
            issue=f"{claim_type} 유형의 마케팅 주장은 실증 자료 또는 제한 조건 없이 사용 시 오인 리스크가 있습니다.",
            rationale="비교·암시·절대 표현은 소비자가 객관적 사실 또는 보장을 약속받은 것으로 이해할 수 있어 출처와 조건 확인이 필요합니다.",
            suggested_revision="측정 기준, 적용 조건, 기간, 예외를 함께 제시하거나 검증 가능한 중립 표현으로 낮추세요.",
            language=language,
            channel=channel,
            product_type=product_type,
            source_text=text[:240],
            verifier_status="PARTIAL",
            law_name="금융광고 내부 심의 기준",
            article_no="CLAIM-SUBSTANTIATION",
            citation_text="비교·정량·보장성 주장은 소비자가 오인하지 않도록 실증 근거와 적용 조건을 함께 표시해야 합니다.",
            applicability_reason="대고객 금융 마케팅 콘텐츠의 주장 유형별 실증·제한조건 검토에 적용됩니다.",
        ))
        existing_evidence.add(evidence)
    return findings


def required_disclosure_gaps(text: str, product_type: ProductType) -> list[str]:
    """상품 유형별 필수 고지 누락 항목을 탐지한다.

    PDF 지정주제 2의 "콘텐츠 유형별 심의 기준 구조화" 요구를 rule layer에 반영한다.
    실제 운영에서는 계열사 내부 광고심의 기준/상품설명서 필수 고지 DB로 교체한다.
    """
    if product_type == "unknown":
        return []
    standards = load_marketing_standards()
    required = standards.get("required_disclosures", {}).get(product_type, [])
    if not required:
        return []
    normalized = text.replace(" ", "").lower()
    gaps: list[str] = []
    for disclosure in required:
        key = str(disclosure).replace(" ", "").lower()
        if key and key not in normalized:
            gaps.append(str(disclosure))
    return gaps


def add_required_disclosure_findings(
    text: str,
    findings: list[MarketingFinding],
    *,
    language: Language,
    channel: Channel,
    product_type: ProductType,
) -> list[MarketingFinding]:
    gaps = required_disclosure_gaps(text, product_type)
    if not gaps:
        return findings
    # 명백한 금융상품 홍보 문구에 대해서만 필수고지 누락을 finding으로 올린다.
    if product_type == "unknown":
        return findings
    findings.append(MarketingFinding(
        id=f"MF-{len(findings)+1:03d}",
        rule_id="MISSING_REQUIRED_DISCLOSURE",
        severity="MEDIUM",
        evidence=", ".join(gaps[:4]),
        issue=f"{product_type} 콘텐츠의 필수 고지 항목이 누락되었거나 불충분합니다.",
        rationale="금융상품 광고는 혜택뿐 아니라 조건·한도·위험·비용을 균형 있게 표시해야 합니다.",
        suggested_revision="누락 고지 항목을 본문 또는 랜딩페이지 상단 고지 영역에 명확히 추가하세요.",
        language=language,
        channel=channel,
        product_type=product_type,
        source_text=text[:240],
        verifier_status="PARTIAL",
        law_name="금융광고 내부 심의 기준",
        article_no="DISCLOSURE-REQUIRED",
        citation_text="상품 유형별 필수 고지 항목(조건·한도·비용·위험)은 소비자가 오인하지 않도록 광고 본문 또는 연결 화면에서 명확히 제공해야 합니다.",
        applicability_reason="금융상품 광고의 혜택 표현과 함께 필수 조건·위험 고지가 필요한지 검토합니다.",
    ))
    return findings


# 펀드 운용실적 표시 기간 검사 (협회 집합투자증권 투자광고 지침 제8조)
# 기간별 수익률 표시: "최근 6개월 +9.8%", "3년 누적 +41.7%", "1년 14.2%" 등
_PERF_RETURN_RE = re.compile(r"\d+\s*(?:개월|년)\s*(?:누적\s*)?[+\-]?\s*\d+(?:\.\d+)?\s*%")
# 장기(3년/5년) 수익률 표시 → 설정이후 수익률 동반 표시 의무 발생 (제8조1항3호)
_PERF_LONGTERM_RE = re.compile(r"(?:3|5)\s*년\s*(?:누적\s*)?[+\-]?\s*\d|설정\s*후\s*[35]\s*년")
# 설정일(또는 설립일)부터 기준일까지의 수익률 표시 여부
_PERF_SINCE_INCEPTION_RE = re.compile(
    r"설정일\s*(?:또는\s*설립일\s*)?부터|설립일\s*부터|설정\s*이후\s*수익률|"
    r"설정일부터\s*기준일|설정\s*이후\s*[+\-]?\s*\d|설정\s*이래\s*수익률|설정\s*이래\s*[+\-]?\s*\d"
)
# 펀드/투자 운용실적 광고 신호
_FUND_CONTEXT_RE = re.compile(r"펀드|집합투자|투자신탁|신탁|운용실적|수익률")


def add_performance_period_findings(
    text: str,
    findings: list[MarketingFinding],
    *,
    language: Language,
    channel: Channel,
    product_type: ProductType,
) -> list[MarketingFinding]:
    """펀드 운용실적 표시 기간 규정 위반 검사 (deterministic).

    협회 「집합투자증권 투자광고 지침」 제8조 제1항 제3호: 설정 후 3년 경과 펀드는
    과거 1년·3년 수익률과 '설정일(또는 설립일)부터 기준일까지의 수익률'을 함께 표시해야 한다.
    → 장기(3년/5년) 수익률을 표시하면서 설정이후 수익률을 누락하면 표시방법 부적정.

    화이트리스트 hard값(6개월=표준/비표준 등)은 규정 원문 위임(운용실적공시규정) 미확인이라
    의도적으로 배제하고, 규정상 가장 명확·방어가능한 '설정이후 누락'만 플래그한다.
    """
    # 펀드/투자 운용실적 광고가 아니면 미적용 (예금/대출/카드/보험 오탐 방지)
    if product_type not in ("investment",) and not _FUND_CONTEXT_RE.search(text):
        return findings
    # 기간별 수익률 표시가 실제로 있어야 적용 (운용실적 미표시 광고는 대상 아님)
    if not _PERF_RETURN_RE.search(text):
        return findings
    has_longterm = bool(_PERF_LONGTERM_RE.search(text))
    has_since_inception = bool(_PERF_SINCE_INCEPTION_RE.search(text))
    if has_longterm and not has_since_inception:
        findings.append(MarketingFinding(
            id=f"MF-{len(findings)+1:03d}",
            rule_id="PERFORMANCE_PERIOD_INADEQUATE",
            severity="MEDIUM",
            evidence="장기(3년/5년) 수익률 표시 + 설정일(또는 설립일)부터 기준일까지의 수익률 누락",
            issue="펀드 운용실적 표시 기간이 부적정합니다 — 설정 후 3년 경과 펀드는 1년·3년 수익률과 함께 '설정일(또는 설립일)부터 기준일까지의 수익률'을 표시해야 합니다.",
            rationale="유리한 기간만 선택해 표시하거나 설정이후 장기 성과를 누락하면 투자자가 실제 운용성과를 오인할 수 있습니다. (협회 집합투자증권 투자광고 지침 제8조 제1항 제3호)",
            suggested_revision="운용실적에 '설정일(또는 설립일)부터 기준일까지의 수익률'을 1년·3년 수익률과 동일 기준으로 함께 표시하세요.",
            language=language,
            channel=channel,
            product_type=product_type,
            source_text=text[:240],
            verifier_status="PARTIAL",
            law_name="금융투자협회 집합투자증권 투자광고 지침",
            article_no="제8조제1항제3호",
            citation_text="기준일로부터 과거 1년 및 3년 수익률과 설정일(또는 설립일)부터 기준일까지의 수익률을 함께 표시하여야 한다.",
            applicability_reason="펀드 운용실적(기간별 수익률)을 표시하는 광고에 적용됩니다.",
        ))
    return findings


# ───────── 다크패턴 텍스트 검사 (금융위 2026.4 시행 대비, negative lookahead로 오탐 방지) ─────────
# F5 fix: "N명이 가입" 직후 부정 결과어(거절/불가/취소/해지/철회/실패/거부/중단)가 오면 제외.
#   → "500명이 가입 거절" 같은 내부 보고 문구 오탐 차단.
_DARK_SOCIAL_PROOF_RE = re.compile(
    r"\d[\d,]*\s*명\s*(?:이|의)?\s*(?:가입|신청|선택|구매)"
    r"(?!\s*\S{0,4}(?:거절|불가|취소|해지|철회|실패|거부|중단|불가능|반려|보류))"
    r"|실시간\s*(?:신청|가입)\s*(?:중|급증)"
    r"|방금\s*(?:가입|신청)\s*(?:했|하셨|완료)"
    r"|(?:지금|현재)\s*\d[\d,]*\s*명\s*(?:이|의)?\s*보고\s*있"
)
# F6 fix: "지금 안 하면"은 감정 결과어(손해/후회/놓치/손실/마지막 등)가 근처에 있을 때만 발동.
#   → "지금 안 하면 안 되는 필수 고지" 같은 의무 고지 문구 오탐 차단.
_DARK_EMOTION_CONDITIONAL_RE = re.compile(
    r"(?:지금|오늘)\s*안\s*하면\s*\S{0,18}(?:손해|후회|놓치|손실|기회를\s*잃|혜택이\s*사라|마지막|끝)"
    r"|안\s*하면\s*\S{0,6}후회"
)
# 그 자체로 소외감·불안을 자극하는 표현은 무조건 발동 (조건 불필요).
_DARK_EMOTION_CORE_RE = re.compile(
    r"나만\s*손해|당신만\s*(?:모르|못\s*받|못받|빼고|소외)|남들\s*다\s*하는데|당신만\s*몰라"
)


def add_dark_pattern_findings(
    text: str,
    findings: list[MarketingFinding],
    *,
    language: Language,
    channel: Channel,
    product_type: ProductType,
) -> list[MarketingFinding]:
    """다크패턴(소비자 활동 알림·감정적 압박) 텍스트 검사 — 정규식 + negative lookahead.

    금융위 「온라인 금융상품 판매 다크패턴 가이드라인」(2026.4 시행) 압박형 대응.
    yaml 부분문자열 매칭(F5/F6 오탐)을 정규식으로 전환하여:
      - "N명이 가입 거절"(내부 보고) 등 부정 맥락 오탐 차단
      - "지금 안 하면 안 되는 필수 고지"(의무 고지) 등 사실 고지 오탐 차단
    """
    def _append(rule_id: str, evidence: str, article: str, rationale: str, revision: str) -> None:
        findings.append(MarketingFinding(
            id=f"MF-{len(findings)+1:03d}",
            rule_id=rule_id,
            severity="MEDIUM",
            evidence=evidence,
            issue=f"다크패턴(압박형): {rationale}",
            rationale=rationale,
            suggested_revision=revision,
            language=language,
            channel=channel,
            product_type=product_type,
            source_text=text[:240],
            verifier_status="PARTIAL",
            law_name="온라인 금융상품 판매 다크패턴 가이드라인",
            article_no=article,
            citation_text="소비자의 비합리적 의사결정을 유도하는 압박형 화면·문구 구성을 금지합니다. (2026.4 시행)",
            applicability_reason="소비자 대상 금융상품 광고의 압박형 표현에 적용됩니다.",
        ))

    m = _DARK_SOCIAL_PROOF_RE.search(text)
    if m:
        _append(
            "DARK_PATTERN_SOCIAL_PROOF", m.group(0).strip(), "압박형-소비자 활동 알림",
            "다른 소비자의 가입·신청 수를 표시해 의사결정을 압박하는 표현(소비자 활동 알림)입니다.",
            "타 소비자의 가입 수·실시간 신청 표시 등 의사결정을 압박하는 사회적 증거 표현을 제거하세요.",
        )
    me = _DARK_EMOTION_CORE_RE.search(text) or _DARK_EMOTION_CONDITIONAL_RE.search(text)
    if me:
        _append(
            "DARK_PATTERN_EMOTIONAL_PRESSURE", me.group(0).strip(), "압박형-감정적 언어 사용",
            "불안·소외감 등 감정을 자극해 특정 행동을 압박하는 표현(감정적 언어 사용)입니다.",
            "소외감·불안을 자극하는 감정적 압박 표현을 제거하고 상품 사실 정보 중심으로 안내하세요.",
        )
    return findings


def generate_revisions(text: str, findings: list[MarketingFinding], product_type: ProductType) -> list[RevisionSuggestion]:
    """Finding별로 다른 권고 문구 생성.

    우선순위:
      1) finding.suggested_revision (rule_id별 specific 문구, content_standards.py에서 정의)
      2) rule_id 카테고리별 specific base 매핑 (CLAIM_TAXONOMY_*, MISSING_REQUIRED_DISCLOSURE, RUNTIME_* 등)
      3) product_type별 default base (최종 fallback)

    동일 finding이라도 evidence(위반 표현)에 따라 다른 권고가 나오도록 보장.
    """
    revisions: list[RevisionSuggestion] = []
    if not findings:
        return revisions

    # Tier 3 fallback: product_type별 default
    product_base = {
        "deposit": "조건 충족 시 최고 금리를 제공하며, 우대금리 조건·가입 한도·세전/세후 여부·중도해지 조건은 상품설명서를 확인해 주세요.",
        "loan": "대출 가능 여부와 한도·금리는 심사 결과에 따라 달라질 수 있으며, 상환 조건과 신용도 영향을 확인해 주세요.",
        "investment": "투자 상품은 원금 손실 가능성이 있으며, 수익률은 시장 상황에 따라 변동될 수 있습니다.",
    }.get(product_type, "혜택과 조건은 대상·기간·한도에 따라 달라질 수 있으므로 상세 내용을 확인해 주세요.")

    # Tier 2: rule_id 카테고리별 specific base (suggested_revision이 없을 때만 사용)
    rule_category_base = {
        "CLAIM_TAXONOMY_ABSOLUTE_GUARANTEE": "보장·확정·100% 표현을 제거하고 심사 결과·조건·한도가 결과에 따라 달라질 수 있음을 명시하세요.",
        "CLAIM_TAXONOMY_COMPARATIVE_SUPERLATIVE": "최저/최고/최대 같은 비교·정량 주장에는 적용 조건, 기준 시점, 비교 대상 범위를 함께 표시하세요.",
        "CLAIM_TAXONOMY_IMPLIED_SAFETY": "안전·무위험·원금보장 암시 표현을 제거하고 손실·변동 가능성을 균형 있게 안내하세요.",
        "MISSING_REQUIRED_DISCLOSURE": "혜택뿐 아니라 조건·한도·위험·비용을 균형 있게 표시하고 누락된 필수 고지 항목을 본문 또는 고지 영역에 추가하세요.",
        "MEMORY_LEARNED_CRITICAL_PHRASE": "과거 반복 위반 사례로 학습된 표현입니다. 보장·무제한·무심사 뉘앙스를 제거하고 사실 기반으로 다시 작성하세요.",
        "RAG_SOURCE_GUIDANCE_MATCH": "ingest된 심의 기준 문서에서 위험 표현으로 분류된 문구입니다. 조건·심사 기준·한도를 명확히 표시한 안전 문구로 수정하세요.",
        "RUNTIME_PROMPT_INJECTION_GUARD": "심의 대상 콘텐츠만 남기고 모델 지시문·프롬프트 조작 문구를 제거한 뒤 재요청하세요.",
        "RUNTIME_SECRET_GUARD": "API key, token, password 등 비밀값을 삭제하고 필요한 경우 redacted placeholder만 사용하세요.",
        "RUNTIME_URL_ALLOWLIST_GUARD": "JB 그룹 공식 도메인 외 URL은 사전 검증 후 사용하거나 별도 안내 절차를 따르세요.",
    }

    for finding in findings:
        # Tier 1: finding 자체의 suggested_revision (rule별로 가장 specific)
        if finding.suggested_revision and finding.suggested_revision.strip():
            revised = finding.suggested_revision.strip()
        else:
            # Tier 2: rule_id 카테고리 매핑
            revised = rule_category_base.get(finding.rule_id, "")
            # Tier 3: product_type fallback
            if not revised:
                revised = product_base
        revisions.append(RevisionSuggestion(
            finding_id=finding.id,
            original=finding.evidence,
            revised=revised,
            reason=finding.rationale,
        ))
    return revisions


def generate_marketing_rewrite(
    text: str,
    findings: list[MarketingFinding],
    *,
    product_type: ProductType,
    channel: Channel,
    language: Language,
    llm_client: "LLMClient",
    model: str | None = None,
    role: str = "marketing_rewriter",
) -> dict[str, Any] | None:
    """LLM이 원본 마케팅 카피를 위반 표현 제거 + 필수 고지 추가하여 직접 rewrite.

    role: system prompt + 주입 스킬 선택 (기본 marketing_rewriter, ad_copy_proposer로 제안 에이전트 스킬 활성화).

    반환 형식:
      {
        "rewritten": "한국어 수정 카피",
        "removed_terms": ["원본 위반 표현 1", ...],
        "added_notices": ["추가된 안내 1", ...],
        "raw_response": "<LLM 원본 출력>",
        "model": "gpt-5.4-mini",
        "deterministic_fallback": False,
      }
      None — findings 부재 또는 LLM 호출 실패 시 (caller가 fallback 처리)

    Safety:
      - llm_client.deterministic=True (LLM 비활성) → None 반환
      - LLM 호출 실패/budget 차단 → None 반환
      - 파싱 실패 → raw_response만 채워서 반환 (UI는 raw로 표시 가능)
    """
    if not findings or not text.strip():
        return None
    if llm_client.deterministic:
        return None

    # 모델 선택 — rewrite는 창작/카피라이팅이라 deep 모델로 품질 우선.
    # (심의 매콜이 아니라 '수정 원고 생성' 버튼 1콜이므로 비용 영향 작음)
    chosen_model = model or os.environ.get("CS_MODEL_REWRITE") or os.environ.get("CS_MODEL_DEEP", "gpt-5.5")

    # LLM 입력 JSON 구성 (system_prompt가 정의한 형식)
    payload = {
        "original_text": text,
        "product_type": product_type,
        "channel": channel,
        "language": language,
        "findings": [
            {
                "id": f.id,
                "rule_id": f.rule_id,
                "severity": f.severity,
                "evidence": f.evidence,
                "issue": f.issue,
                "suggested_revision": f.suggested_revision,
            }
            for f in findings
        ],
    }
    user_text = json.dumps(payload, ensure_ascii=False)

    # gpt-5 reasoning 모델은 max_tokens가 강제 32000 상향되어 무효 → effort가 실질 비용 레버.
    # CS_REWRITE_EFFORT로 reasoning 깊이 조정 (default medium, low 시 reasoning 토큰 감소 → 비용/지연 절감).
    rewrite_effort = os.environ.get("CS_REWRITE_EFFORT", "medium")
    try:
        result = llm_client.call(
            role=role,
            user_text=user_text,
            model=chosen_model,
            effort=rewrite_effort,
            max_tokens=1024,
            estimated_cost_usd=0.02,
        )
    except Exception as exc:  # noqa: BLE001 — LLM은 silent fallback
        return {
            "rewritten": None,
            "removed_terms": [],
            "added_notices": [],
            "raw_response": "",
            "model": chosen_model,
            "deterministic_fallback": True,
            "error": f"llm_call_exception: {type(exc).__name__}",
        }

    if result.deterministic_fallback or not (result.text or "").strip():
        return {
            "rewritten": None,
            "removed_terms": [],
            "added_notices": [],
            "raw_response": result.text or "",
            "model": chosen_model,
            "deterministic_fallback": True,
            "error": getattr(result, "error", None),
        }

    parsed = _parse_marketing_rewrite_output(result.text)
    parsed["raw_response"] = result.text
    parsed["model"] = chosen_model
    parsed["deterministic_fallback"] = False
    return parsed


def _parse_marketing_rewrite_output(raw: str) -> dict[str, Any]:
    """[수정안] / [삭제된 표현] / [추가된 필수 고지] 3-block 파서.

    파싱 실패 시 → rewritten=None, raw_response만 유지 (UI는 raw로 보여줌).
    """
    rewritten: str | None = None
    removed: list[str] = []
    added: list[str] = []
    section: str | None = None
    rewritten_lines: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("[수정안]"):
            section = "rewrite"
            continue
        if s.startswith("[삭제된 표현]"):
            if rewritten_lines:
                rewritten = "\n".join(rewritten_lines).strip()
            section = "removed"
            continue
        if s.startswith("[추가된 필수 고지]"):
            section = "added"
            continue
        if section == "rewrite":
            rewritten_lines.append(line)
        elif section == "removed":
            if s.startswith("-"):
                removed.append(s.lstrip("-").strip())
        elif section == "added":
            if s.startswith("-"):
                added.append(s.lstrip("-").strip())
    if rewritten is None and rewritten_lines:
        rewritten = "\n".join(rewritten_lines).strip()
    return {
        "rewritten": rewritten,
        "removed_terms": removed,
        "added_notices": added,
    }


VALID_RISK_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def llm_detect_risk_findings(
    text: str,
    existing_findings: list[MarketingFinding],
    *,
    language: Language,
    channel: Channel,
    product_type: ProductType,
    llm_client: "LLMClient",
    model: str | None = None,
) -> list[MarketingFinding]:
    """LLM 기반 맥락형 위험표현 1차 스캔 (방안 C).

    정적 규칙 사전이 놓치는 맥락형 과장(비현실적 수익률, N배, 무제한, 긴급성 등)을
    미니 모델로 감지하여 finding으로 승격한다.

    Safety:
      - llm_client.deterministic=True → [] 반환 (기존 동작 보존)
      - LLM 호출 실패/budget 차단/파싱 실패 → [] 반환 (silent fallback)
      - 원문 미등장 또는 이미 flagged된 표현은 제외 (hallucination/중복 차단)
    """
    if not text.strip() or llm_client.deterministic:
        return []

    chosen_model = model or os.environ.get("CS_RISK_SCAN_MODEL", "gpt-5.4-mini")
    flagged = sorted({f.evidence for f in existing_findings if f.evidence})
    payload = {
        "original_text": text,
        "product_type": product_type,
        "already_flagged": flagged,
    }
    user_text = json.dumps(payload, ensure_ascii=False)

    try:
        result = llm_client.call(
            role="marketing_risk_scanner",
            user_text=user_text,
            model=chosen_model,
            effort="low",
            max_tokens=512,
            estimated_cost_usd=0.005,
        )
    except Exception:  # noqa: BLE001 — LLM은 silent fallback
        return []

    if result.deterministic_fallback or not (result.text or "").strip():
        return []

    parsed = _parse_risk_scan_output(result.text)
    findings: list[MarketingFinding] = []
    existing_evidence = {f.evidence for f in existing_findings}
    lowered = text.lower()
    base_index = len(existing_findings)
    for item in parsed:
        evidence = item["evidence"]
        severity = item["severity"]
        # hallucination/중복 차단: 원문 미포함 또는 이미 감지된 표현 제외
        if not evidence or evidence in existing_evidence or evidence.lower() not in lowered:
            continue
        findings.append(MarketingFinding(
            id=f"MF-{base_index + len(findings) + 1:03d}",
            rule_id="LLM_CONTEXTUAL_RISK_SCAN",
            severity=severity,
            evidence=evidence,
            issue=f"'{evidence}' 표현은 맥락상 소비자 오인·과장 리스크가 있습니다 (LLM 1차 스캔).",
            rationale=item["reason"] or "맥락형 과장·비현실적 약속·긴급성 조성 등은 금융광고에서 오인을 유발할 수 있습니다.",
            suggested_revision="비현실적 수익·무제한·긴급성 표현을 제거하고 조건·한도·근거를 사실 기반으로 표시하세요.",
            language=language,
            channel=channel,
            product_type=product_type,
            source_text=text[:240],
            verifier_status="FAIL" if severity == "CRITICAL" else "PARTIAL",
            law_name="금융광고 내부 심의 기준",
            article_no="LLM-CONTEXTUAL-SCAN",
            citation_text="비현실적 수익·무제한·긴급성·단정적 부 약속 등 맥락형 과장 표현은 소비자 오인을 유발하므로 사실 기반으로 수정해야 합니다.",
            applicability_reason="정적 규칙 사전이 놓치는 맥락형 마케팅 과장 표현 탐지에 적용됩니다.",
        ))
        existing_evidence.add(evidence)
    return findings


def _parse_risk_scan_output(raw: str) -> list[dict[str, str]]:
    """[위험표현] 블록 파서. 각 줄 형식: - "표현" | SEVERITY | 사유

    파싱 실패한 줄은 건너뛴다. "(없음)" → 빈 리스트.
    """
    items: list[dict[str, str]] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s.startswith("-"):
            continue
        body = s.lstrip("-").strip()
        if not body or body == "(없음)":
            continue
        parts = [p.strip() for p in body.split("|")]
        if len(parts) < 2:
            continue
        evidence = parts[0].strip().strip('"').strip("'").strip()
        severity = parts[1].strip().upper()
        reason = parts[2].strip() if len(parts) >= 3 else ""
        if severity not in VALID_RISK_SEVERITIES:
            severity = "MEDIUM"
        if evidence:
            items.append({"evidence": evidence, "severity": severity, "reason": reason})
    return items


def decide_approval(findings: list[MarketingFinding], language: Language) -> str:
    if any(f.severity == "CRITICAL" for f in findings):
        return "REJECTED"
    if any(f.severity == "HIGH" for f in findings):
        return "HUMAN_REVIEW_REQUIRED" if language != "ko" else "APPROVE_WITH_CHANGES"
    if findings:
        return "APPROVE_WITH_CHANGES"
    return "APPROVED"


def risk_level(findings: list[MarketingFinding]) -> str:
    if not findings:
        return "LOW"
    highest = max((_severity_rank(f.severity) for f in findings), default=0)
    return {0: "LOW", 1: "MEDIUM", 2: "HIGH", 3: "CRITICAL"}[highest]


def review_marketing_content(raw_content: str) -> MarketingReview:
    redacted, _ = redact_pii(raw_content)
    redacted = neutralize_active_content(redacted)
    language = detect_language(redacted)
    channel = classify_channel(redacted)
    product_type = classify_product(redacted)
    content_type = classify_content_type(product_type)
    guard_findings, guard_flags = runtime_guard_findings(redacted, language=language, channel=channel, product_type=product_type)
    findings = guard_findings + rule_based_review(redacted, language=language, channel=channel, product_type=product_type)
    findings = add_claim_taxonomy_findings(
        redacted,
        findings,
        language=language,
        channel=channel,
        product_type=product_type,
    )
    findings = add_required_disclosure_findings(
        redacted,
        findings,
        language=language,
        channel=channel,
        product_type=product_type,
    )
    findings = add_performance_period_findings(
        redacted,
        findings,
        language=language,
        channel=channel,
        product_type=product_type,
    )
    findings = add_dark_pattern_findings(
        redacted,
        findings,
        language=language,
        channel=channel,
        product_type=product_type,
    )
    revisions = generate_revisions(redacted, findings, product_type)
    approval = decide_approval(findings, language)
    risk = risk_level(findings)
    exports = {
        "slack": build_slack_payload(approval_status=approval, risk_level=risk, findings=findings, revisions=revisions),
        "notion": build_notion_payload(approval_status=approval, risk_level=risk, findings=findings, revisions=revisions),
        "jira": build_jira_payload(approval_status=approval, risk_level=risk, findings=findings, revisions=revisions),
    }
    return MarketingReview(
        raw_content=raw_content,
        redacted_content=redacted,
        language=language,
        channel=channel,
        content_type=content_type,
        product_type=product_type,
        findings=findings,
        revision_suggestions=revisions,
        approval_status=approval,
        workflow_exports=exports,
        evaluation_metadata={
            "review_mode": "deterministic_rule_plus_optional_llm",
            "multilingual": language != "ko",
            "finding_count": len(findings),
            "claim_taxonomy": classify_claim_taxonomy(redacted),
            "required_disclosure_gaps": required_disclosure_gaps(redacted, product_type),
            "runtime_guard": guard_flags,
        },
    )
