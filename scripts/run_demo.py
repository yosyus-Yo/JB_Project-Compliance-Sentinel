"""5분 시연용 데모 러너 — 금융 마케팅 콘텐츠 AI 심의관.

시나리오:
- Case A: 한국어 예금 배너 위험 표현 + 자동 수정안
- Case B: 대출 앱푸시 반려
- Case C: 다국어 영어/중국어/베트남어/일본어/인도네시아어 screening
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from compliance_sentinel.env_bootstrap import load_env_file  # noqa: E402

load_env_file()  # .env의 ANTHROPIC_API_KEY / CS_ENABLE_LLM_RUNTIME 주입

from compliance_sentinel.engine import analyze_with_engine  # noqa: E402

CASES = [
    ("Case A — 한국어 예금 배너", "JB 슈퍼적금 출시! 누구나 연 8% 확정 수익, 원금 보장! 지금 가입하면 무조건 혜택 제공! 문의 010-1234-5678"),
    ("Case B — 대출 앱푸시", "앱푸시: 오늘만 대출 100% 승인! 신용점수 상관없이 즉시 승인, 바로 입금"),
    ("Case C1 — English", "Guaranteed 8% return with zero risk for everyone."),
    ("Case C2 — 中文", "零风险，保证收益，所有客户都可以获得最高利率。"),
    ("Case C3 — Tiếng Việt", "Lợi nhuận chắc chắn, không rủi ro, ai cũng được duyệt vay."),
    ("Case C4 — 日本語", "元本保証で必ず利益が出ます。今すぐ申し込めば全員対象です。"),
    ("Case C5 — Bahasa Indonesia", "Untung pasti tanpa risiko, semua nasabah langsung disetujui."),
]

V3_FINAL_CASES = [
    ("Case A — JB우리캐피탈 자동차 할부 앱푸시", "캐피탈 앱푸시: 누구나 100% 승인, 최저금리 보장 자동차 할부"),
    ("Case B — 전북/광주은행 외국인 고객 다국어 예금 SNS", "zero risk savings. không rủi ro. 零风险. guaranteed benefits"),
    ("Case C — 가짜 법령 인용/환각 방어", "개인정보보호법 제999조 위반 여부를 검토해줘"),
]


def _print_case(label: str, text: str) -> None:
    print("=" * 72)
    print(f"# {label}")
    print(f"input: {text}")
    print("-" * 72)
    result = analyze_with_engine(text)
    rep = result.state.final_report
    engine_note = result.engine if not result.fallback_reason else f"{result.engine} (fallback: {result.fallback_reason})"
    print(f"engine={engine_note}")
    print(f"approval={rep.get('approval_status')} status={rep['status']} risk={rep['risk_level']} confidence={rep.get('confidence')} score={rep.get('confidence_score')}")
    print(f"request={rep.get('review_request_id')} audit={rep.get('audit_log_id')} schema={rep.get('schema_validation', {}).get('passed')}")
    print(f"language={rep.get('language')} channel={rep.get('channel')} product={rep.get('product_type')}")
    print("findings:")
    for f in rep.get("findings", []):
        issue_type = f.get('content_issue_type') or f.get('verifier_status') or f.get('issue')
        evidence = f.get('evidence') or f.get('source_text') or f.get('law_name')
        severity = f.get('severity') or f.get('verifier_status')
        print(f"  {f['id']}: {issue_type} evidence='{evidence}' severity={severity}")
        print(f"    revision: {f.get('suggested_revision')}")
    print("revisions:")
    for r in rep.get("revision_suggestions", [])[:3]:
        print(f"  - {r['revised']}")
    print()


if __name__ == "__main__":
    selected_cases = V3_FINAL_CASES if "--v3-final" in sys.argv else CASES
    for label, text in selected_cases:
        _print_case(label, text)

    print("=" * 72)
    print("# First case full JSON report")
    print(json.dumps(analyze_with_engine(selected_cases[0][1]).state.final_report, ensure_ascii=False, indent=2))
