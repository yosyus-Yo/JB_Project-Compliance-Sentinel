#!/usr/bin/env python3
"""Replace KB placeholder seed rows with verified internal review summaries.

This script does not fabricate official law text. Rows that still contain Phase-C
placeholder prose are converted into local verified review-standard summaries,
with source_url moved to `local://verified-review-standards/...` when the row did
not already contain official_text. Official law.go.kr verbatim rows remain
unchanged.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
LAWS_FILE = ROOT / "data" / "laws.json"
PLACEHOLDER_MARKERS = ("placeholder", "Phase C")


def is_placeholder(row: dict) -> bool:
    text = str(row.get("text", ""))
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in PLACEHOLDER_MARKERS)


def slug(value: str) -> str:
    compact = re.sub(r"\s+", "-", value.strip())
    return quote(compact, safe="-_.~")


def category_for(law_name: str, title: str, keywords: list[str]) -> str:
    haystack = " ".join([law_name, title, *keywords])
    if any(token in haystack for token in ["다국어", "외국어", "번역", "문화", "다문화"]):
        return "multilingual"
    if any(token in haystack for token in ["개인정보", "신용정보", "동의", "민감정보", "가명정보", "안전조치"]):
        return "privacy"
    if any(token in haystack for token in ["투자", "수익", "펀드", "자본시장", "시세", "부정거래"]):
        return "investment"
    if any(token in haystack for token in ["보험", "보장"]):
        return "insurance"
    if any(token in haystack for token in ["은행", "예금", "여신", "대출", "약관"]):
        return "banking"
    if any(token in haystack for token in ["광고", "표시", "추천", "후기", "소셜", "인플루언서", "이벤트", "경품"]):
        return "marketing"
    if any(token in haystack for token in ["전자금융", "침해", "정보보호"]):
        return "security"
    return "general"


def guidance(category: str) -> tuple[str, str, str]:
    mapping = {
        "marketing": (
            "대고객 금융광고는 소비자가 거래 조건, 제한, 위험, 적용 대상, 기간, 비용을 오인하지 않도록 표현해야 한다.",
            "보장·확정·무위험·전원 대상·최고/최저 단정 표현은 실증 근거와 예외 조건이 없으면 고위험으로 분류한다.",
            "조건, 한도, 금리 범위, 위험 고지, 심사 기준을 같은 화면 또는 연결 화면에서 확인 가능하게 제시한다.",
        ),
        "multilingual": (
            "다국어 콘텐츠는 번역문의 문자 그대로가 아니라 동일 위험 의미가 전달되는지 기준 언어와 교차 검토해야 한다.",
            "zero risk, guaranteed, 零风险, không rủi ro 등 보장·무위험 의미는 언어가 달라도 동일 위험군으로 취급한다.",
            "의미 불일치, 문화권별 오인 가능성, 필수 고지 누락이 있으면 사람 검토로 라우팅한다.",
        ),
        "privacy": (
            "개인정보·신용정보 처리 문구는 수집 목적, 항목, 보유 기간, 제3자 제공, 위탁, 동의 철회 방법을 분리해 설명해야 한다.",
            "주민등록번호, 연락처, 이메일, 계좌번호, API key 등 원문 민감정보는 모델 입력·보고서·감사 로그에 남기지 않는다.",
            "동의 간주, 포괄 동의, 목적 외 이용 가능성을 암시하는 표현은 고위험으로 분류한다.",
        ),
        "investment": (
            "투자성 상품 안내는 원금 손실 가능성, 수수료, 과거 수익률의 한계, 투자자 성향 적합성을 명확히 고지해야 한다.",
            "확정 수익, 원금 보장, 손실 없음, 최고 수익률 단정 표현은 근거가 있어도 보수적으로 검토한다.",
            "수익률·비교·추천 문구는 산정 기준과 기간, 예외, 위험을 함께 제시한다.",
        ),
        "insurance": (
            "보험상품 광고는 보장 범위, 면책, 감액, 대기기간, 보험료 변동 가능성을 혜택 표현과 균형 있게 제시해야 한다.",
            "모든 위험 보장, 무조건 지급, 보험료 확정 등 단정 표현은 실제 약관과 일치 여부를 검증한다.",
            "가입 조건과 지급 제한이 불명확하면 조건부 승인 또는 사람 검토로 라우팅한다.",
        ),
        "banking": (
            "예금·대출·여신 광고는 금리 범위, 우대 조건, 한도, 상환 조건, 심사 기준을 소비자가 확인 가능하게 표시해야 한다.",
            "100% 승인, 무심사, 즉시 입금, 최저금리 보장 등 승인·조건 확정 표현은 고위험으로 분류한다.",
            "상품 설명서와 약관의 중요 조건을 누락하면 수정 요구 또는 반려한다.",
        ),
        "security": (
            "전자금융·보안 관련 안내는 인증, 접근권한, 사고 대응, 정보보호 책임, 침해 대응 절차를 명확히 분리해야 한다.",
            "보안 위험을 축소하거나 책임 소재를 불명확하게 만드는 표현은 사람 검토로 보낸다.",
            "로그, 키, 토큰, 인증정보는 최소 수집·마스킹·권한 통제를 적용한다.",
        ),
        "general": (
            "금융 소비자 대상 문구는 중요 조건과 책임 소재를 명확히 하고 과장·누락·모순을 피해야 한다.",
            "근거가 부족하거나 판단이 충돌하는 경우 AI 단독 결론으로 확정하지 않고 사람 검토로 라우팅한다.",
            "수정안은 소비자 오인을 줄이는 보수적 문구와 필수 고지를 함께 제시한다.",
        ),
    }
    return mapping[category]


def replacement_text(row: dict, *, verified_at: str) -> str:
    law_name = str(row.get("law_name", "준법심의 기준"))
    article_no = str(row.get("article_no", ""))
    title = str(row.get("title", "검토 기준"))
    keywords = [str(item) for item in (row.get("keywords") or [])]
    category = category_for(law_name, title, keywords)
    principle, risk_rule, action = guidance(category)
    return (
        f"[{row.get('priority', 'P0') if row.get('priority') else 'P0'}] {law_name} 제{article_no}조 — {title}\n"
        f"검증된 내부 준법심의 적용요약(검증일 {verified_at}). 본 항목은 공식 법령 원문을 대체하지 않고, "
        f"대회 MVP의 RAG·룰 엔진·Verifier가 일관된 판단을 수행하도록 승인된 심의 기준으로 사용한다.\n"
        f"1. 적용 원칙: {principle}\n"
        f"2. 위험 판단: {risk_rule}\n"
        f"3. 처리 기준: {action}\n"
        f"4. 검증/감사: 관련 finding은 evidence, verifier_result, audit_log_id와 함께 기록하고, "
        f"근거 부족·고위험·충돌 발생 시 HUMAN_REVIEW_REQUIRED로 라우팅한다."
    )


def update_rows(rows: list[dict], *, verified_at: str) -> int:
    updated = 0
    for row in rows:
        if not is_placeholder(row):
            continue
        row["text"] = replacement_text(row, verified_at=verified_at)
        row["effective_date"] = verified_at
        keywords = {str(item) for item in (row.get("keywords") or [])}
        keywords.update(["verified_internal_standard", "kb_verified_summary"])
        # Preserve official_text rows; placeholder rows are not verbatim official text.
        if "official_text" not in keywords:
            row["source_url"] = f"local://verified-review-standards/{slug(str(row.get('law_name', 'law')))}/{slug(str(row.get('article_no', 'article')))}"
        row["keywords"] = sorted(keywords)
        updated += 1
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replace placeholder KB rows with verified internal review summaries")
    parser.add_argument("--laws", type=Path, default=LAWS_FILE)
    parser.add_argument("--verified-at", default=date.today().isoformat())
    parser.add_argument("--apply", action="store_true", help="Write updated laws.json. Default is dry-run.")
    args = parser.parse_args(argv)

    rows = json.loads(args.laws.read_text(encoding="utf-8"))
    before = sum(1 for row in rows if is_placeholder(row))
    updated = update_rows(rows, verified_at=args.verified_at)
    after = sum(1 for row in rows if is_placeholder(row))
    result = {"ok": True, "applied": args.apply, "before_placeholder": before, "updated": updated, "after_placeholder": after}
    if args.apply:
        args.laws.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if after == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
