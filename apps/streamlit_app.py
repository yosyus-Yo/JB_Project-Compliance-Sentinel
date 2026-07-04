"""Streamlit UI for Compliance Sentinel.

Run:
  PYTHONPATH=src streamlit run apps/streamlit_app.py
"""
from __future__ import annotations

import html
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compliance_sentinel.env_bootstrap import load_env_file  # noqa: E402

load_env_file()  # .env의 ANTHROPIC_API_KEY / CS_ENABLE_LLM_RUNTIME 주입 (compliance_sentinel 사용 전)

from compliance_sentinel.engine import analyze_with_engine, clear_agent_cache  # noqa: E402
from compliance_sentinel.knowledge_ingest import ingest_document  # noqa: E402
from compliance_sentinel.reporting import render_markdown  # noqa: E402
from compliance_sentinel.ui_settings import (  # noqa: E402
    FLAG_FIELDS,
    MODEL_FIELDS,
    ROUTING_FIELDS,
    SECRET_FIELDS,
    apply_settings_to_environment,
    default_settings,
    delete_encrypted_settings,
    has_encrypted_settings,
    load_encrypted_settings,
    model_route_summary_from_env,
    runtime_route_summary_from_env,
    save_encrypted_settings,
    secret_status,
)

SAMPLES = {
    "고위험 적금 광고": "JB 슈퍼적금 출시! 누구나 연 8% 확정 수익, 원금 보장!",
    "가짜 법령 인용": "이 약관은 개인정보보호법 제999조와 신용정보법 제32조를 위반합니다.",
    "정상 인용 + 위험 표현": "본 광고는 금융소비자보호법 제19조의 설명의무를 충족합니다. 원금 보장 무위험 확정 수익.",
    "캐피탈 할부 광고": "신차 할부 0%부터, 무심사 가능! 한도 무제한으로 바로 승인됩니다.",
}

RISK_EMOJI = {
    "LOW": "🟢",
    "MEDIUM": "🟡",
    "HIGH": "🟠",
    "CRITICAL": "🔴",
}

STATUS_EMOJI = {
    "APPROVED": "✅",
    "PASSED": "✅",
    "APPROVE_WITH_CHANGES": "🛠️",
    "HUMAN_REVIEW_REQUIRED": "👤",
    "REJECTED": "⛔",
}

# P0-2: 승인 상태 한글+색상 매핑 (요청서 §P0 결과 카드화)
APPROVAL_KOR: dict[str, tuple[str, str]] = {
    "APPROVED": ("✅ 승인", "🟢"),
    "PASSED": ("✅ 통과", "🟢"),
    "APPROVE_WITH_CHANGES": ("⚠️ 조건부 승인", "🟡"),
    "CONDITIONAL_APPROVAL": ("⚠️ 조건부 승인", "🟡"),
    "HUMAN_REVIEW_REQUIRED": ("👤 사람 검토 필요", "🟠"),
    "REJECTED": ("⛔ 반려", "🔴"),
}

# P1-4: 영어 필드명 → 한글 라벨 매핑 (Turn 3에서 본격 적용; 본 turn에서는 verdict 카드만 사용)
FIELD_LABELS_KOR: dict[str, str] = {
    "approval_status": "승인 상태",
    "risk_level": "위험도",
    "confidence_score": "신뢰도",
    "confidence": "신뢰도",
    "findings": "위험 표현",
    "revision_suggestions": "수정 제안",
    "verifier_result": "검증 결과",
    "audit_log_id": "감사 번호",
    "board_diagnostics": "심의 위원 의견",
    "execution_engine": "실행 엔진",
    "review_type": "심의 유형",
    "content_type": "콘텐츠 유형",
    "language": "언어",
    "channel": "채널",
    "product_type": "상품 유형",
    "summary": "요약",
}

# Turn 9 AC-4.2: render_json_sections 헤더용 한글 매핑 (FIELD_LABELS_KOR 보완 — 추가 키)
JSON_SECTION_LABELS_KOR: dict[str, str] = {
    "claim_taxonomy_summary": "📋 주장 분류 요약",
    "rag_metadata": "🔎 법령 검색 (RAG) 메타데이터",
    "pdf_requirement_alignment": "📄 PDF 요구사항 정합",
    "evaluation_metadata": "📊 평가 메타데이터",
    "memory_context": "🧠 메모리 컨텍스트",
    "board_diagnostics": "👥 6인 보드 진단",
    "workflow_publish_plan": "📤 외부 공유 계획",
    "workflow_exports": "📦 워크플로우 산출물",
    "routing_decision": "🔀 모델 라우팅 결정",
    "model_plan": "🤖 모델 사용 계획",
    "budget_status": "💰 예산 상태",
    "cross_model_result": "✅ 교차 모델 검증 결과",
}

# severity emoji → 카드 테두리 hex (다크 네이비 톤 유지)
SEVERITY_BORDER_HEX: dict[str, str] = {
    "🟢": "#10b981",
    "🟡": "#eab308",
    "🟠": "#f97316",
    "🔴": "#ef4444",
}

# P1-3: 6인 보드 위원 한글 매핑 (state.board_opinions의 agent_id 키)
BOARD_AGENT_KOR: dict[str, str] = {
    "legal-counsel": "⚖️ 법률 자문",
    "pipa-credit-info-expert": "🔒 개인정보 (PIPA)",
    "consumer-protection-expert": "🛡️ 소비자보호",
    "aml-operational-risk-expert": "💼 운영 리스크 (AML)",
    "business-practicality-expert": "📊 업무 실무성",
    "contrarian-agent": "🎭 반론자 (Contrarian)",
}

# P1-3: 9-step 워크플로우 정의 (final_report 키 존재로 단계 완료 추정)
# 각 튜플: (step_id, 한글 라벨, 완료 판정용 final_report 키)
WORKFLOW_STEPS: list[tuple[str, str, str]] = [
    ("pii", "1. PII 제거", "redacted_content"),
    ("classify", "2. 분류", "review_type"),
    ("rag", "3. 법령 검색", "rag_metadata"),
    ("board", "4. 6인 보드", "board_opinions"),
    ("ceo", "5. CEO 종합", "approval_status"),
    ("verifier", "6. Verifier 검증", "cross_model_result"),
    ("routing", "7. 승인 라우팅", "routing_decision"),
    ("publish", "8. 외부 공유", "workflow_publish_plan"),
    ("audit", "9. 감사 로그", "audit_log_id"),
]

# P1-5: 언어 코드 → 깃발 매핑 (요청서 §P1 다국어 명확화)
LANGUAGE_FLAGS: dict[str, str] = {
    "ko": "🇰🇷 한국어",
    "en": "🇺🇸 영어",
    "zh": "🇨🇳 중국어",
    "zh-cn": "🇨🇳 중국어",
    "zh-tw": "🇹🇼 중국어(번체)",
    "vi": "🇻🇳 베트남어",
    "ja": "🇯🇵 일본어",
    "es": "🇪🇸 스페인어",
    "fr": "🇫🇷 프랑스어",
}

SUPPORTED_UPLOAD_TYPES = {"txt", "md", "json", "csv"}

# 메인 review_form 파일 업로드 — multimodal_input.py 활용 (offline-first)
# pdf/docx/xlsx/rtf/html/hwpx는 항상 OK, 이미지 OCR은 tesseract 설치 필요
SUPPORTED_REVIEW_UPLOAD_TYPES = {
    "txt", "md", "json", "csv",
    "pdf", "docx", "xlsx", "rtf",
    "html", "htm", "hwpx",
    "png", "jpg", "jpeg", "tiff", "bmp",
}

# P2-6 AC-6.2~6.4: 커스텀 CSS — Impeccable 디자인 토큰 차용
#   • Linear (dark-mode-native): 카드 elevated surface, 얇은 보더, primary text 색감
#       - Marketing Black #08090a / Panel Dark #0f1011 / Elevated #191a1b / Border #23252a / Text #f7f8f8
#   • Coinbase (financial trust): hover blue (보조 액센트)
#       - Coinbase Blue #0052ff / Hover Blue #578bfa
#   현재 카드 톤 #0f1929 (다크 네이비)와 호환 — 다크 네이비 톤 유지 (AC-6.3)
STYLE_CSS = """
<style>
/* 다크 네이비 일관 톤 (MVP 제안서 + Linear 영감) */
[data-testid="stAppViewContainer"] {
  background-color: #0a1525;
}
[data-testid="stHeader"] {
  background: transparent;
}
[data-testid="stSidebar"] {
  background-color: #0f1929;
  border-right: 1px solid #23252a;
}
/* 페이지 타이틀 톤 */
h1, h2, h3, h4, h5, h6 {
  color: #f7f8f8;
}
.stCaption, [data-testid="stCaptionContainer"] {
  color: #9ca3af;
}
/* st.metric — 다크 카드 톤 */
[data-testid="stMetric"] {
  background: #0f1011;
  border: 1px solid #23252a;
  border-radius: 8px;
  padding: 10px 14px;
}
/* tabs 보더 — 얇은 보더 사상 (Linear) */
[data-baseweb="tab-list"] {
  border-bottom: 1px solid #23252a;
}
/* st.expander — 다크 elevated surface */
.streamlit-expanderHeader, [data-testid="stExpander"] details > summary {
  background-color: #0f1011;
  border: 1px solid #23252a;
  border-radius: 8px;
}
/* dataframe (위험 표현 표·6인 보드 표) — 다크 톤 */
[data-testid="stDataFrame"] {
  background-color: #0f1011;
  border: 1px solid #23252a;
  border-radius: 8px;
  padding: 4px;
}
/* divider 색 — 얇은 보더 */
hr {
  border-top: 1px solid #23252a !important;
  margin: 14px 0 !important;
}
/* st.info / st.success / st.warning — 다크 톤 정렬 */
[data-testid="stAlert"] {
  background: #0f1011;
  border: 1px solid #23252a;
  border-radius: 8px;
}
/* Turn 9 A+B: 'Made with Streamlit' footer 숨김 — 사용자 "그냥 streamlit" 인상 차단 */
footer, [data-testid="stStatusWidget"], .reportview-container .main footer {
  display: none !important;
}
/* Sidebar width 확대 — 한글 라벨 잘림 방지 (기본 ~250px → 320px) */
[data-testid="stSidebar"] {
  min-width: 320px !important;
  max-width: 360px !important;
}
[data-testid="stSidebar"] > div:first-child {
  min-width: 320px !important;
}
/* Turn 9b fix: 헤더 그라데이션 제거 (streamlit h1과 충돌로 텍스트 사라짐).
   단순 색 + 굵게로 강조. */
h1 {
  color: #f7f8f8 !important;
  font-weight: 700;
  letter-spacing: -0.5px;
}
/* Spinner 색 강조 */
[data-testid="stSpinner"] > div {
  border-color: #5e6ad2 transparent transparent transparent !important;
}
</style>
"""
MAX_UPLOAD_BYTES = 1_500_000


def to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def normalize_report(result: Any) -> dict[str, Any]:
    report = dict(result.state.final_report)
    report["execution_engine"] = result.engine
    if result.fallback_reason:
        report["engine_fallback_reason"] = result.fallback_reason

    # P1-3: 6인 보드 위원 의견을 UI 노출용으로 추가 (final_report는 board_diagnostics 집계만 보유)
    try:
        from dataclasses import asdict, is_dataclass

        bo = getattr(result.state, "board_opinions", None)
        if isinstance(bo, dict):
            report["board_opinions"] = {
                k: (asdict(v) if is_dataclass(v) else v)
                for k, v in bo.items()
            }
    except Exception:
        pass

    return report


def severity_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        severity = str(finding.get("severity") or finding.get("risk_level") or "UNKNOWN")
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def render_metric_cards(report: dict[str, Any]) -> None:
    risk = str(report.get("risk_level", "UNKNOWN"))
    status = str(report.get("approval_status") or report.get("status", "UNKNOWN"))
    confidence = str(report.get("confidence", "UNKNOWN"))
    audit_id = str(report.get("audit_log_id", "-"))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("위험도", f"{RISK_EMOJI.get(risk, '⚪')} {risk}")
    col2.metric("승인 상태", f"{STATUS_EMOJI.get(status, 'ℹ️')} {status}")
    col3.metric("신뢰도", confidence)
    col4.metric("감사 로그", audit_id)


def render_verdict_card(report: dict[str, Any]) -> None:
    """P0-2: 판정 배지 카드 — 결과 최상단.

    한글+영문 병기, 승인상태별 색(승인🟢/조건부🟡/사람검토🟠/반려🔴),
    위험도 emoji, 신뢰도, 감사 ID inline.
    """
    approval_raw = str(report.get("approval_status") or report.get("status", "UNKNOWN"))
    risk = str(report.get("risk_level", "UNKNOWN"))
    confidence = report.get("confidence_score") or report.get("confidence") or "-"
    audit_id = str(report.get("audit_log_id", "-"))

    approval_kor, approval_color = APPROVAL_KOR.get(approval_raw, (approval_raw, "⚪"))
    risk_emoji = RISK_EMOJI.get(risk, "⚪")
    border_color = SEVERITY_BORDER_HEX.get(approval_color, "#6b7280")

    # 사용자 입력 escape (XSS 방지 — disclaimer/audit_id 등 외부 데이터)
    approval_kor_safe = html.escape(approval_kor)
    approval_raw_safe = html.escape(approval_raw)
    risk_safe = html.escape(risk)
    confidence_safe = html.escape(str(confidence))
    audit_id_safe = html.escape(audit_id)

    st.markdown(
        f"""
<div style="background:#0f1929;border-left:4px solid {border_color};padding:18px 22px;border-radius:10px;margin:8px 0 16px 0;">
  <div style="font-size:24px;font-weight:700;color:#fff;">{approval_color} {approval_kor_safe} <span style="font-size:14px;font-weight:400;color:#9ca3af;">({approval_raw_safe})</span></div>
  <div style="font-size:16px;color:#e5e7eb;margin-top:6px;">위험도: {risk_emoji} <b>{risk_safe}</b> · 신뢰도: <b>{confidence_safe}</b> · 감사 번호: <code style="color:#9ca3af;background:transparent;">{audit_id_safe}</code></div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_finding_cards(findings: list[dict[str, Any]]) -> None:
    """P0-2: 위험 표현을 카드 1개씩으로 — 표현 + 문제 + 수정안.

    각 finding이 카드 한 장(헤더에 severity 색·표현·severity 배지, 본문에 문제·근거·수정안).
    """
    if not findings:
        st.success("✅ 탐지된 주요 위반/리스크 항목이 없습니다.")
        return

    st.caption(f"총 {len(findings)}건 위험 표현 발견")
    for finding in findings:
        severity = str(finding.get("severity") or finding.get("risk_level") or "UNKNOWN")
        risk_emoji = RISK_EMOJI.get(severity, "⚪")
        border_color = SEVERITY_BORDER_HEX.get(risk_emoji, "#6b7280")

        excerpt_raw = str(
            finding.get("excerpt")
            or finding.get("text_excerpt")
            or finding.get("issue")
            or finding.get("id", "-")
        )
        issue_raw = str(
            finding.get("issue")
            or finding.get("applicability_reason")
            or finding.get("rationale")
            or "-"
        )
        revision_raw = str(finding.get("suggested_revision") or "-")
        law_ref_raw = ""
        if finding.get("law_name"):
            law_ref_raw = f" · 근거: {finding['law_name']} 제{finding.get('article_no', '-')}조"

        # XSS 방지 — finding 내용은 사용자 입력 분석에서 유래
        excerpt = html.escape(excerpt_raw)
        issue = html.escape(issue_raw)
        revision = html.escape(revision_raw)
        law_ref = html.escape(law_ref_raw)
        severity_safe = html.escape(severity)

        st.markdown(
            f"""
<div style="background:#0f1929;border-left:3px solid {border_color};padding:14px 18px;border-radius:8px;margin:10px 0;">
  <div style="font-size:16px;font-weight:600;color:#fff;">{risk_emoji} "{excerpt}" <span style="font-size:11px;color:#fff;background:{border_color};padding:2px 8px;border-radius:4px;margin-left:6px;vertical-align:middle;">{severity_safe}</span></div>
  <div style="margin-top:10px;color:#d1d5db;font-size:14px;"><b>문제</b>: {issue}{law_ref}</div>
  <div style="margin-top:6px;color:#86efac;font-size:14px;"><b>수정안</b>: {revision}</div>
</div>
""",
            unsafe_allow_html=True,
        )


def render_workflow_progress(report: dict[str, Any]) -> None:
    """P1-3 AC-3.1: 9단계 심의 과정 진행 — Turn 8 강화 (큰 카드 + 화살표 연결)."""
    # 9단계 + 8개 화살표 = 17 컬럼 (각 step과 step 사이 좁은 → 컬럼)
    col_specs = []
    for i in range(len(WORKFLOW_STEPS)):
        col_specs.append(5)  # 단계 카드 너비
        if i < len(WORKFLOW_STEPS) - 1:
            col_specs.append(1)  # 화살표 너비
    cols = st.columns(col_specs)

    for i, (_step_id, label, check_key) in enumerate(WORKFLOW_STEPS):
        col_idx = i * 2
        value = report.get(check_key)
        done = bool(value) if not isinstance(value, (dict, list)) else len(value) > 0
        if done:
            mark = "✅"
            border_color = "#10b981"  # 초록
            bg_color = "#0f2922"
        else:
            mark = "⏸"
            border_color = "#374151"
            bg_color = "#0f1929"
        cols[col_idx].markdown(
            f"<div style='text-align:center;padding:14px 4px;background:{bg_color};"
            f"border:1px solid {border_color};border-radius:10px;min-height:90px;"
            f"display:flex;flex-direction:column;justify-content:center;'>"
            f"<div style='font-size:26px;line-height:1;'>{mark}</div>"
            f"<div style='font-size:11px;color:#f7f8f8;margin-top:8px;line-height:1.3;font-weight:500;'>{html.escape(label)}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        # 화살표 (마지막 단계 제외)
        if i < len(WORKFLOW_STEPS) - 1:
            cols[col_idx + 1].markdown(
                "<div style='text-align:center;padding-top:38px;color:#5e6ad2;font-size:20px;font-weight:bold;'>→</div>",
                unsafe_allow_html=True,
            )


def render_board_table(report: dict[str, Any]) -> None:
    """P1-3 AC-3.2~3.3: 6인 보드 위원 표 — 위원/판정/의견. 위험판정 색 강조."""
    board_opinions = report.get("board_opinions") or {}
    if not board_opinions:
        st.info(
            "6인 보드 의견 데이터가 없습니다. (정상 분석이라면 6명 위원 모두 채워져야 합니다)"
        )
        return

    rows = []
    for agent_id, opinion in board_opinions.items():
        if not isinstance(opinion, dict):
            continue
        agent_kor = BOARD_AGENT_KOR.get(agent_id, agent_id)
        risk = str(opinion.get("risk_level", "UNKNOWN"))
        risk_emoji = RISK_EMOJI.get(risk, "⚪")
        stance = str(opinion.get("stance", "")).strip()
        rationale = str(opinion.get("rationale", "")).strip()
        if stance and rationale:
            opinion_text = f"{stance} — {rationale}"
        else:
            opinion_text = stance or rationale or "-"
        # Turn 9: truncation 제거 — 시연 시 전체 의견 보이게
        rows.append(
            {
                "심의 위원": agent_kor,
                "위험 판정": f"{risk_emoji} {risk}",
                "의견": opinion_text,
            }
        )

    if rows:
        # Turn 9 AC-3.3: HIGH/CRITICAL 행 배경 강조 (pandas Styler)
        # _risk_raw 헬퍼 컬럼 안 두고 "위험 판정" 텍스트에서 매핑 추출
        try:
            import pandas as pd
            df = pd.DataFrame(rows)

            def _highlight_row(row):
                judge_text = str(row.get("위험 판정", ""))
                # "🟠 HIGH" 형식에서 마지막 토큰 추출
                tokens = judge_text.split()
                risk_token = tokens[-1] if tokens else ""
                if risk_token in ("CRITICAL", "HIGH"):
                    return ["background-color: #2d1518; color: #fca5a5; font-weight: 600"] * len(row)
                if risk_token == "MEDIUM":
                    return ["background-color: #2d2515; color: #fcd34d"] * len(row)
                return [""] * len(row)

            styler = df.style.apply(_highlight_row, axis=1)
            st.dataframe(
                styler,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "의견": st.column_config.TextColumn("의견", width="large"),
                    "심의 위원": st.column_config.TextColumn("심의 위원", width="small"),
                    "위험 판정": st.column_config.TextColumn("위험 판정", width="small"),
                },
            )
        except Exception:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        # 다관점 강조 — 위원들이 서로 다른 판정을 내렸을 때
        distinct_risks = {r["위험 판정"] for r in rows}
        if len(distinct_risks) >= 2:
            st.caption(
                f"💡 6인 위원이 **{len(distinct_risks)}가지 다른 판정**을 내림 — 다관점 심의의 차별화 지점"
            )


def _detect_finding_language(text: str) -> str:
    """P1-5 fix (Codex review): finding evidence/excerpt 텍스트에서 dominant 언어 추론.

    백엔드가 모든 finding에 단일 dominant language를 부여하는 한계 우회.
    한글/한자/베트남 diacritics/라틴 순으로 첫 매칭 반환.
    """
    import re

    if re.search(r"[가-힣]", text):
        return "ko"
    if re.search(r"[一-鿿]", text):
        return "zh"
    # 베트남어 diacritics (basic accents + Vietnamese-unique 음운 + 대문자)
    if re.search(
        r"[ăâđêôơưĂÂĐÊÔƠƯạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ"
        r"àáảãèéẻẽìíòóỏõùúủũýÀÁẢÃÈÉẺẼÌÍÒÓỎÕÙÚỦŨÝ]",
        text,
    ):
        return "vi"
    if re.search(r"[a-zA-Z]", text):
        return "en"
    return "unknown"


def render_multilingual_findings(findings: list[dict[str, Any]]) -> None:
    """P1-5 AC-5.1~5.2: 다국어 위험 표현 → 언어 깃발 + 표현 그룹핑.

    Codex review fix (Turn 6): finding의 evidence/excerpt에서 per-finding 언어
    재추론하여 mixed-language 입력에서도 그룹핑 가능 (백엔드 단일 language 한계 우회).
    """
    if not findings:
        return

    by_lang: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        # 우선 evidence/excerpt에서 finding 단위 언어 재추론 → fallback으로 백엔드 language
        evidence_text = str(
            f.get("excerpt")
            or f.get("text_excerpt")
            or f.get("evidence")
            or f.get("source_text")
            or ""
        )
        lang = _detect_finding_language(evidence_text) if evidence_text else "unknown"
        if lang == "unknown":
            lang = str(f.get("language", "unknown")).lower()
        by_lang.setdefault(lang, []).append(f)

    # 단일 언어이면 표시 의미 없음 (이미 위 위험 표현 카드에 다 보임)
    if len(by_lang) < 2:
        return

    st.markdown("##### 🌐 다국어 위험 표현 (언어별 그룹)")
    for lang in sorted(by_lang.keys()):
        flag_label = LANGUAGE_FLAGS.get(lang, f"🌐 {lang}")
        items = by_lang[lang]
        st.markdown(f"**{flag_label}** ({len(items)}건)")
        for f in items:
            excerpt = str(
                f.get("excerpt") or f.get("text_excerpt") or f.get("issue") or f.get("id", "-")
            )
            issue = str(f.get("issue") or "-")
            st.markdown(
                f'- "{html.escape(excerpt[:80])}" — {html.escape(issue[:120])}'
            )


def render_findings(findings: list[dict[str, Any]]) -> None:
    if not findings:
        st.success("탐지된 주요 위반/리스크 항목이 없습니다.")
        return

    st.caption(f"총 {len(findings)}개 finding")
    # P1-4 한글화: 코드 키 그대로가 아닌 한글 컬럼으로 표시
    display_rows = [
        {
            "ID": f.get("id", "-"),
            "위험도": f"{RISK_EMOJI.get(str(f.get('severity', '')), '⚪')} {f.get('severity', '-')}",
            "검증 결과": f.get("verifier_status", "-"),
            "이슈": f.get("issue", "-"),
            "근거 법령": f.get("law_name", "-"),
            "조항": f.get("article_no", "-"),
            "수정 제안": f.get("suggested_revision", "-"),
        }
        for f in findings
    ]
    st.dataframe(display_rows, use_container_width=True, hide_index=True)
    _LEGACY_FINDINGS_DATAFRAME = None  # noqa: F841 — 아래 legacy 호출 무효화
    # (이 함수의 expander 본문은 아래에 그대로 유지 — finding 1건씩 상세 표시)
    for finding in findings:
        title = (
            f"{finding.get('id', '-')}: {finding.get('severity', '-')}"
            f"/{finding.get('verifier_status', '-')}"
        )
        with st.expander(title):
            st.write(f"**이슈**: {finding.get('issue', '-')}")
            st.write(
                f"**근거**: {finding.get('law_name', '-')} 제{finding.get('article_no', '-')}조"
            )
            st.write(
                f"**판단 사유**: {finding.get('applicability_reason') or finding.get('rationale') or '-'}"
            )
            st.write(f"**수정 제안**: {finding.get('suggested_revision', '-')}")
            if finding.get("citation_text"):
                st.info(str(finding["citation_text"]))
    return  # 아래 legacy dataframe/expander 블록은 무력화

    st.dataframe(
        findings,
        use_container_width=True,
        hide_index=True,
        column_order=[
            "id",
            "severity",
            "verifier_status",
            "issue",
            "law_name",
            "article_no",
            "suggested_revision",
        ],
    )

    for finding in findings:
        title = f"{finding.get('id', '-')}: {finding.get('severity', '-')}/{finding.get('verifier_status', '-')}"
        with st.expander(title):
            st.write(f"**이슈**: {finding.get('issue', '-')}")
            st.write(f"**근거**: {finding.get('law_name', '-')} 제{finding.get('article_no', '-')}조")
            st.write(f"**판단 사유**: {finding.get('applicability_reason') or finding.get('rationale') or '-'}")
            st.write(f"**수정 제안**: {finding.get('suggested_revision', '-')}")
            if finding.get("citation_text"):
                st.info(str(finding["citation_text"]))


def render_revision_suggestions(suggestions: list[dict[str, Any]]) -> None:
    if not suggestions:
        st.info("별도 수정 제안이 없습니다.")
        return
    st.dataframe(suggestions, use_container_width=True, hide_index=True)

    for suggestion in suggestions:
        with st.expander(f"수정안 {suggestion.get('finding_id', '-')}"):
            st.write("**원문/위험 표현**")
            st.warning(str(suggestion.get("original", "-")))
            st.write("**권장 문구**")
            st.success(str(suggestion.get("revised", "-")))
            if suggestion.get("reason"):
                st.caption(str(suggestion["reason"]))


def render_json_sections(report: dict[str, Any], keys: list[str]) -> None:
    """Turn 9 AC-4.2: expander 헤더를 FIELD_LABELS_KOR로 한글 변환 (snake_case 노출 0)."""
    for key in keys:
        kor = JSON_SECTION_LABELS_KOR.get(key, FIELD_LABELS_KOR.get(key, key))
        with st.expander(kor, expanded=False):
            st.json(report.get(key, {}))


def collect_secure_settings_from_widgets(settings: dict[str, Any]) -> dict[str, Any]:
    """Collect the latest Streamlit widget state before save/apply.

    Secret inputs are intentionally rendered empty, so relying only on the
    previously loaded settings can keep an old key. Reading widget state at the
    button-click moment guarantees that a newly pasted key replaces the stored
    encrypted value immediately.
    """

    latest = {
        "secrets": dict(settings.get("secrets") or {}),
        "models": dict(settings.get("models") or {}),
        "flags": dict(settings.get("flags") or {}),
        "routing": dict(settings.get("routing") or {}),
        "updated_at": str(settings.get("updated_at") or ""),
    }
    for field in SECRET_FIELDS:
        clear_key = f"clear_secret_{field.env}"
        input_key = f"secret_input_{field.env}"
        if st.session_state.get(clear_key):
            latest["secrets"][field.env] = ""
            continue
        new_value = str(st.session_state.get(input_key) or "").strip()
        if new_value:
            latest["secrets"][field.env] = new_value
    for field in MODEL_FIELDS:
        input_key = f"model_input_{field.env}"
        latest["models"][field.env] = str(
            st.session_state.get(input_key)
            or latest["models"].get(field.env)
            or os.environ.get(field.env)
            or field.default
        ).strip()
    for field in FLAG_FIELDS:
        latest["flags"][field.env] = "1" if st.session_state.get(f"flag_{field.env}") else "0"
    for field in ROUTING_FIELDS:
        input_key = f"routing_input_{field.env}"
        widget_value = st.session_state.get(input_key) if input_key in st.session_state else None
        latest["routing"][field.env] = str(
            widget_value
            if widget_value is not None
            else latest["routing"].get(field.env)
            or os.environ.get(field.env)
            or field.default
        ).strip()
    return latest


def apply_runtime_settings(settings: dict[str, Any]) -> None:
    """Apply settings and drop cached agents/LLM clients that may hold old keys."""

    apply_settings_to_environment(settings)
    clear_agent_cache()


def decode_uploaded_document(file: Any) -> str:
    data = file.getvalue()
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("파일이 너무 큽니다. 1.5MB 이하 텍스트 문서만 업로드해 주세요.")
    suffix = Path(file.name).suffix.lower().lstrip(".")
    if suffix not in SUPPORTED_UPLOAD_TYPES:
        raise ValueError("지원 형식은 txt, md, json, csv입니다. PDF/DOCX는 텍스트로 변환 후 업로드해 주세요.")
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("문서 인코딩을 읽을 수 없습니다. UTF-8 텍스트로 저장 후 다시 업로드해 주세요.")


def render_secure_settings_panel() -> None:
    if "secure_settings" not in st.session_state:
        st.session_state.secure_settings = default_settings()
    if "settings_unlocked" not in st.session_state:
        st.session_state.settings_unlocked = False

    st.header("설정")
    st.caption("API key는 화면에 표시하지 않고, 저장 시 로컬 암호화 파일에만 보관합니다.")
    encrypted_exists = has_encrypted_settings()
    st.caption(f"암호화 설정 파일: {'있음' if encrypted_exists else '없음'}")

    master_password = st.text_input("마스터 비밀번호", type="password", help="암호화 설정 저장/불러오기에 사용합니다. 저장되지 않습니다.")
    if st.button("설정 불러오기", use_container_width=True):
        try:
            settings = load_encrypted_settings(master_password)
            apply_runtime_settings(settings)
            st.session_state.secure_settings = settings
            st.session_state.settings_unlocked = True
            st.success("암호화 설정을 불러와 세션에 적용했습니다. 기존 LLM 클라이언트 캐시도 초기화했습니다.")
        except Exception as exc:
            st.error(str(exc))

    settings = st.session_state.secure_settings
    statuses = secret_status(settings)

    with st.expander("API Keys / 외부 연동", expanded=True):
        secrets = dict(settings.get("secrets") or {})
        for field in SECRET_FIELDS:
            current = "설정됨" if statuses.get(field.env) or os.environ.get(field.env) else "미설정"
            new_value = st.text_input(
                field.label,
                type="password",
                value="",
                placeholder=f"{current} · 새 값 입력 시 교체",
                key=f"secret_input_{field.env}",
                help=f"{field.env} — {field.help}",
            )
            if new_value.strip():
                secrets[field.env] = new_value.strip()
            if st.checkbox(f"{field.label} 삭제", key=f"clear_secret_{field.env}"):
                secrets[field.env] = ""
                os.environ.pop(field.env, None)
        settings["secrets"] = secrets

    with st.expander("모델 라우팅", expanded=True):
        st.caption("간단/일반/복잡/검증 작업에 사용할 모델을 분리합니다.")
        models = dict(settings.get("models") or {})
        for field in MODEL_FIELDS:
            models[field.env] = st.text_input(
                field.label,
                value=str(models.get(field.env) or os.environ.get(field.env) or field.default),
                key=f"model_input_{field.env}",
                help=f"{field.env} — {field.help}",
            ).strip()
        settings["models"] = models
        st.caption("현재 세션 라우팅 모델")
        st.json(model_route_summary_from_env())

    with st.expander("런타임 옵션", expanded=False):
        flags = dict(settings.get("flags") or {})
        for field in FLAG_FIELDS:
            checked = str(flags.get(field.env) or os.environ.get(field.env) or field.default) == "1"
            flags[field.env] = "1" if st.checkbox(field.label, value=checked, key=f"flag_{field.env}", help=f"{field.env} — {field.help}") else "0"
        settings["flags"] = flags

    with st.expander("라우팅/성능 옵션", expanded=False):
        routing = dict(settings.get("routing") or {})
        for field in ROUTING_FIELDS:
            current = str(routing.get(field.env) or os.environ.get(field.env) or field.default)
            if field.options:
                routing[field.env] = st.selectbox(
                    field.label,
                    options=list(field.options),
                    index=list(field.options).index(current) if current in field.options else 0,
                    key=f"routing_input_{field.env}",
                    help=f"{field.env} — {field.help}",
                )
            elif field.kind == "number":
                routing[field.env] = str(
                    st.number_input(
                        field.label,
                        value=int(current or field.default),
                        min_value=field.minimum or 0,
                        max_value=field.maximum or 10_000_000,
                        step=1,
                        key=f"routing_input_{field.env}",
                        help=f"{field.env} — {field.help}",
                    )
                )
            else:
                routing[field.env] = st.text_input(
                    field.label,
                    value=current,
                    key=f"routing_input_{field.env}",
                    help=f"{field.env} — {field.help}",
                ).strip()
        settings["routing"] = routing
        st.caption("현재 세션 라우팅/성능 설정")
        st.json(runtime_route_summary_from_env())

    st.session_state.secure_settings = settings
    col_save, col_session, col_delete = st.columns(3)
    if col_save.button("암호화 저장 + 세션 적용", use_container_width=True):  # P2-6 AC-6.1: 빨강은 메인 액션(준법 심의 실행)만
        try:
            latest_settings = collect_secure_settings_from_widgets(settings)
            save_encrypted_settings(latest_settings, master_password)
            apply_runtime_settings(latest_settings)
            st.session_state.secure_settings = latest_settings
            st.session_state.settings_unlocked = True
            st.success("현재 화면 설정을 암호화 저장하고 세션에 적용했습니다. 기존 LLM 클라이언트 캐시도 초기화했습니다.")
        except Exception as exc:
            st.error(str(exc))
    if col_session.button("저장 없이 세션 적용", use_container_width=True):
        try:
            latest_settings = collect_secure_settings_from_widgets(settings)
            apply_runtime_settings(latest_settings)
            st.session_state.secure_settings = latest_settings
            st.success("현재 화면 설정을 세션 환경변수에 적용했습니다. 기존 LLM 클라이언트 캐시도 초기화했습니다.")
        except Exception as exc:
            st.error(str(exc))
    if col_delete.button("암호화 설정 파일 삭제", use_container_width=True):
        delete_encrypted_settings()
        st.session_state.secure_settings = default_settings()
        st.session_state.settings_unlocked = False
        clear_agent_cache()
        st.warning("암호화 설정 파일을 삭제했습니다. 기존 LLM 클라이언트 캐시도 초기화했습니다. 현재 프로세스 환경변수는 필요 시 재시작으로 초기화하세요.")


if hasattr(st, "dialog"):
    @st.dialog("⚙️ 설정창", width="large")
    def render_settings_dialog() -> None:
        render_secure_settings_panel()
else:  # pragma: no cover - Streamlit 구버전 fallback
    def render_settings_dialog() -> None:
        st.session_state.show_settings_panel = True


def run_document_ingest(files: list[Any], *, source_prefix: str, apply: bool, approved_memory: bool) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for file in files:
        text = decode_uploaded_document(file)
        report = ingest_document(
            text,
            source=f"{source_prefix}:{Path(file.name).name}",
            apply=apply,
            approved_memory=approved_memory,
        )
        reports.append(asdict(report))
    return reports


def run_analysis(text: str) -> dict[str, Any]:
    result = analyze_with_engine(text)
    return normalize_report(result)


def main() -> None:
    st.set_page_config(
        page_title="Compliance Sentinel",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # P2-6: 커스텀 CSS 주입 (Impeccable Linear/Coinbase 토큰 차용 — 다크 네이비 톤)
    st.markdown(STYLE_CSS, unsafe_allow_html=True)

    # Turn 9 B-#6: 헤더 강화 — 그라데이션 (CSS) + 부제 + 차별화 배지
    st.title("🛡️ Compliance Sentinel")
    st.markdown(
        "<div style='margin-top:-12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;'>"
        "<span style='color:#9ca3af;font-size:13px;'>금융 마케팅 콘텐츠 준법 심의 · 위험 탐지 · 수정 제안 · 감사 로그</span>"
        "<span style='background:#5e6ad2;color:#fff;font-size:11px;padding:3px 8px;border-radius:4px;font-weight:600;'>9-step</span>"
        "<span style='background:#0667d0;color:#fff;font-size:11px;padding:3px 8px;border-radius:4px;font-weight:600;'>6-인 보드</span>"
        "<span style='background:#10b981;color:#fff;font-size:11px;padding:3px 8px;border-radius:4px;font-weight:600;'>RAG + Verifier</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    if "history" not in st.session_state:
        st.session_state.history = []
    if "sample_text" not in st.session_state:
        st.session_state.sample_text = SAMPLES["고위험 적금 광고"]
    if "ingest_reports" not in st.session_state:
        st.session_state.ingest_reports = []
    if "secure_settings" not in st.session_state:
        st.session_state.secure_settings = default_settings()
    if "settings_unlocked" not in st.session_state:
        st.session_state.settings_unlocked = False

    with st.sidebar:
        # P0-1: 기본 (항상 보임) — 첫인상은 "문구 넣고 → 심의 실행" 한 줄로
        st.subheader("입력 도우미")
        selected_sample = st.selectbox("샘플 문구", list(SAMPLES.keys()))
        if st.button("샘플 불러오기", use_container_width=True):
            st.session_state.sample_text = SAMPLES[selected_sample]

        if st.button("⚙️ 설정 (API 키 등)", use_container_width=True):
            render_settings_dialog()
        configured_keys = sum(1 for configured in secret_status(st.session_state.secure_settings).values() if configured)
        st.caption(f"저장된 키 {configured_keys}개")
        if st.session_state.get("show_settings_panel"):
            # nested expander 회피: render_secure_settings_panel 내부가 이미 expander 3개 사용
            st.markdown("##### ⚙️ 설정 패널")
            render_secure_settings_panel()

        st.divider()

        # P0-1: 관리자 도구 (접힘) — 전문가 1명만 쓰는 기능, 첫 화면에서 가려야 함
        with st.expander("⚙️ 관리자 도구", expanded=False):
            st.caption("전문가/관리자 전용 — 문서 주입 · Memory 승인")
            uploaded_files = st.file_uploader(
                "경험/심의 기준 문서 업로드",
                type=sorted(SUPPORTED_UPLOAD_TYPES),
                accept_multiple_files=True,
                help="기존 시스템의 knowledge_ingest 파이프라인으로 Skill + RAG + Memory 후보에 분류/주입합니다.",
            )
            source_prefix = st.text_input("출처 라벨", value="expert-upload")
            apply_ingest = st.checkbox("실제 주입 적용", value=True, help="끄면 dry-run으로 분류 결과만 확인합니다.")
            approved_memory = st.checkbox("승인된 전문가 경험으로 Memory까지 승인", value=False)
            if st.button("문서 주입 실행", use_container_width=True):
                if not uploaded_files:
                    st.error("업로드할 문서를 선택해 주세요.")
                else:
                    with st.spinner("문서를 Skill/RAG/Memory로 분류 및 주입 중..."):
                        try:
                            reports = run_document_ingest(
                                uploaded_files,
                                source_prefix=source_prefix.strip() or "expert-upload",
                                apply=apply_ingest,
                                approved_memory=approved_memory,
                            )
                        except Exception as exc:  # pragma: no cover - UI safety net
                            st.error(str(exc))
                        else:
                            st.session_state.ingest_reports = reports
                            written = sum(r.get("written_skill_items", 0) + r.get("written_rag_items", 0) + r.get("written_memory_items", 0) for r in reports)
                            st.success(f"문서 {len(reports)}개 처리 완료 · written={written}")
            if st.session_state.ingest_reports:
                # nested expander 회피 (관리자 도구 expander 안) — markdown header로 대체
                st.markdown("###### 최근 주입 결과")
                for report in st.session_state.ingest_reports[-3:]:
                        st.write(f"**{report.get('source')}**")
                        st.json({
                            "applied": report.get("applied"),
                            "chunks": report.get("total_chunks"),
                            "blocked": report.get("blocked_chunks"),
                            "targets": report.get("target_counts"),
                            "written": {
                                "skill": report.get("written_skill_items"),
                                "rag": report.get("written_rag_items"),
                                "memory": report.get("written_memory_items"),
                            },
                        })

        st.divider()

        # 최근 감사 로그 (작게)
        if st.session_state.history:
            st.caption("최근 감사 로그")
            for item in reversed(st.session_state.history[-5:]):
                st.caption(f"{item.get('audit_log_id', '-')} · {item.get('risk_level', '-')}")
        st.caption("기본: deterministic-safe · LLM은 환경변수 opt-in")

    # 메인 파일 업로드 (form 외부 — file_uploader는 form 내부에서 제한적)
    uploaded_review_file = st.file_uploader(
        "📎 파일 업로드 (선택) — PDF/DOCX/XLSX/RTF/HTML/HWPX/이미지(OCR)",
        type=sorted(SUPPORTED_REVIEW_UPLOAD_TYPES),
        accept_multiple_files=False,
        help=(
            "파일 업로드 시 텍스트를 자동 추출해서 아래 입력란에 채워줍니다. "
            "이미지(PNG/JPG)는 tesseract OCR 필요 (`brew install tesseract tesseract-lang`). "
            "최대 20MB."
        ),
        key="review_file_upload",
    )

    # 업로드된 파일에서 텍스트 추출 — submit 전에 미리 처리 (사용자가 검토/수정 가능)
    extracted_text = ""
    if uploaded_review_file is not None:
        try:
            from compliance_sentinel.multimodal_input import (
                extract_text_from_bytes,
                MultimodalExtractError,
            )
            file_bytes = uploaded_review_file.getvalue()
            extracted = extract_text_from_bytes(file_bytes, uploaded_review_file.name)
            extracted_text = extracted.text
            st.success(
                f"📄 `{extracted.source_filename}` ({extracted.extractor}) — "
                f"{extracted.char_count}자 추출됨"
                + (f" · {extracted.page_count}페이지" if extracted.page_count else "")
            )
            if extracted.warnings:
                with st.expander(f"⚠️ 경고 {len(extracted.warnings)}건"):
                    for w in extracted.warnings:
                        st.caption(f"• {w}")
        except MultimodalExtractError as exc:
            st.error(f"❌ 파일 추출 실패: {exc}")
        except ImportError as exc:
            st.error(
                f"❌ multimodal 의존성 미설치: {exc}. "
                "설치: `pip install -e \".[multimodal]\"`"
            )

    with st.form("review_form"):
        # 파일 추출 텍스트가 있으면 우선, 없으면 sample_text
        default_value = extracted_text if extracted_text else st.session_state.sample_text
        content = st.text_area(
            "검토할 금융 마케팅/약관/안내 문구 (파일 업로드 시 자동 채움 · 수정 가능)",
            value=default_value,
            height=240 if extracted_text else 180,
            placeholder="예: JB 슈퍼적금 출시! 누구나 연 8% 확정 수익, 원금 보장!",
        )
        submitted = st.form_submit_button("준법 심의 실행", type="primary", use_container_width=True)

    if submitted:
        if not content.strip():
            st.error("검토할 문구를 입력해 주세요.")
            return
        with st.spinner("⚡ 9단계 심의 워크플로우 + 6인 보드 분석 중... (10-30초)"):
            try:
                report = run_analysis(content.strip())
            except Exception as exc:  # pragma: no cover - UI safety net
                st.exception(exc)
                return
        st.session_state.report = report
        st.session_state.history.append(
            {
                "audit_log_id": report.get("audit_log_id"),
                "risk_level": report.get("risk_level"),
                "status": report.get("approval_status") or report.get("status"),
            }
        )

    report = st.session_state.get("report")
    if not report:
        st.info("문구를 입력하고 **준법 심의 실행**을 눌러 주세요.")
        return

    # P0-2: 판정 배지 카드 (최상단) — 한글+영문 병기, 색상, 신뢰도, 감사 ID
    render_verdict_card(report)

    if report.get("disclaimer"):
        st.warning(str(report["disclaimer"]))

    findings = report.get("findings") or []
    suggestions = report.get("revision_suggestions") or []
    counts = severity_counts(findings)

    # P1-3 ⭐ (Turn 8 정정): 9단계 + 6인 보드를 expander 밖 직접 노출
    # 사용자 피드백 "그냥 streamlit으로 보임" — 차별화 시각화가 expander 안에 숨겨져 못 봄
    st.divider()
    st.subheader("⚡ 9단계 심의 워크플로우")
    render_workflow_progress(report)

    st.subheader("👥 6인 심의 보드 (다관점 의견)")
    col_board, col_chart = st.columns([3, 2])
    with col_board:
        render_board_table(report)
    with col_chart:
        # 위험 판정 분포 차트 (다관점 시각화 강화)
        board_opinions = report.get("board_opinions") or {}
        if board_opinions:
            from collections import Counter
            risk_counts = Counter(
                str(o.get("risk_level", "UNKNOWN"))
                for o in board_opinions.values()
                if isinstance(o, dict)
            )
            if risk_counts:
                st.caption("위원별 위험 판정 분포")
                # 다크 톤 호환 bar chart
                chart_data = {risk: count for risk, count in risk_counts.most_common()}
                st.bar_chart(chart_data, height=200, color="#5e6ad2")  # Linear indigo

    st.divider()

    # P0-2: 위험 표현 카드 — 각 finding을 카드 1개로 (표현 + 문제 + 수정안)
    st.subheader("🚨 위험 표현")
    render_finding_cards(findings)

    # P1-5: 다국어 그룹핑 (2개 이상 언어 발견 시만 자동 표시)
    render_multilingual_findings(findings)

    # P0-2 AC-2.3: 상세 보기 — 기존 7-tab은 그 역할 (raw JSON은 각 tab의 expander 안에 expanded=False)
    st.divider()
    st.subheader("🔍 상세 보기 (심사위원·개발자용)")
    tab_summary, tab_findings, tab_revisions, tab_evidence, tab_workflow, tab_ingest, tab_export = st.tabs(
        ["요약", "리스크 Findings", "수정 제안", "근거/RAG", "보드·워크플로우", "문서 주입", "내보내기"]
    )

    with tab_summary:
        st.subheader("심의 요약")
        st.write(report.get("summary", "요약 정보가 없습니다."))
        col1, col2 = st.columns(2)
        with col1:
            st.write("**분류 정보**")
            # P1-4 한글화: 영어 코드 키를 한글 라벨로 표시
            lang_code = report.get("language") or "-"
            lang_label = LANGUAGE_FLAGS.get(str(lang_code).lower(), str(lang_code))
            st.json(
                {
                    "심의 유형": report.get("review_type"),
                    "콘텐츠 유형": report.get("content_type"),
                    "언어": lang_label,
                    "채널": report.get("channel"),
                    "상품 유형": report.get("product_type"),
                    "실행 엔진": report.get("execution_engine"),
                }
            )
        with col2:
            st.write("**위험도 분포**")
            st.json(counts)
            st.write("**사람 검토 필요 여부**")
            st.write("필요" if report.get("human_review_needed") else "불필요")

    with tab_findings:
        render_findings(findings)

    with tab_revisions:
        render_revision_suggestions(suggestions)

    with tab_evidence:
        # Turn 6 fix 정정 (Turn 7-bis): nested expander 금지 — render_json_sections가 내부 expander 사용
        # AC-2.4 충족: render_json_sections의 각 key가 default 접힘 expander → raw JSON은 클릭해야 보임
        st.caption("근거 자료 (RAG/Claim/Memory) — 각 항목 클릭 시 raw JSON 표시 (개발자용)")
        render_json_sections(
            report,
            [
                "claim_taxonomy_summary",
                "rag_metadata",
                "pdf_requirement_alignment",
                "evaluation_metadata",
                "memory_context",
            ],
        )

    with tab_workflow:
        st.caption(
            "보드 진단·라우팅·예산 — 각 항목 클릭 시 raw JSON (위 '심의 과정 9단계 보기'가 시각화 영역)"
        )
        render_json_sections(
            report,
            [
                "board_diagnostics",
                "workflow_publish_plan",
                "workflow_exports",
                "routing_decision",
                "model_plan",
                "budget_status",
                "cross_model_result",
            ],
        )

    with tab_ingest:
        st.subheader("전문가 문서 주입 결과")
        if not st.session_state.ingest_reports:
            st.info("왼쪽 사이드바의 **전문가 문서 주입**에서 문서를 업로드해 주세요.")
        else:
            for ingest_report in st.session_state.ingest_reports:
                with st.expander(str(ingest_report.get("source", "uploaded document")), expanded=True):
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("chunks", ingest_report.get("total_chunks", 0))
                    col2.metric("blocked", ingest_report.get("blocked_chunks", 0))
                    col3.metric("skill", ingest_report.get("written_skill_items", 0))
                    col4.metric("rag/memory", int(ingest_report.get("written_rag_items", 0)) + int(ingest_report.get("written_memory_items", 0)))
                    st.write("**저장 위치**")
                    st.json({
                        "skill_path": ingest_report.get("skill_path"),
                        "rag_path": ingest_report.get("rag_path"),
                        "pending_path": ingest_report.get("pending_path"),
                    })
                    st.write("**신뢰/차단 요약**")
                    st.json(ingest_report.get("trust_summary", {}))
                    if st.checkbox("청크 상세 보기", key=f"chunks_detail_{ingest_report.get('source', id(ingest_report))}"):
                        st.json(ingest_report.get("chunks", []))

    with tab_export:
        st.subheader("보고서 다운로드")
        json_report = to_json(report)
        markdown_report = render_markdown(report)
        col1, col2 = st.columns(2)
        col1.download_button(
            "JSON 다운로드",
            data=json_report,
            file_name=f"compliance-report-{report.get('audit_log_id', 'latest')}.json",
            mime="application/json",
            use_container_width=True,
        )
        col2.download_button(
            "Markdown 다운로드",
            data=markdown_report,
            file_name=f"compliance-report-{report.get('audit_log_id', 'latest')}.md",
            mime="text/markdown",
            use_container_width=True,
        )
        st.code(markdown_report, language="markdown")
        with st.expander("원본 JSON"):
            st.json(report)


if __name__ == "__main__":
    main()
