from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

STANDARDS_DIR = Path(__file__).resolve().parents[2] / "data" / "review_standards"


def _fallback_standards() -> dict[str, Any]:
    return {
        "forbidden_expressions": [
            {"id": "GUARANTEED_PRINCIPAL", "severity": "HIGH", "patterns": ["원금 보장", "원금보장", "元本保証"], "rationale": "원금 보장 표현은 소비자 오인을 유발할 수 있습니다.", "suggested_revision": "예금자보호 여부, 보호 한도, 상품 조건을 명확히 고지하세요."},
            {"id": "ZERO_RISK", "severity": "HIGH", "patterns": ["무위험", "zero risk", "零风险", "không rủi ro", "リスクなし", "tanpa risiko"], "rationale": "무위험 표현은 리스크를 축소할 수 있습니다.", "suggested_revision": "상품 조건과 손실/변동 가능성 또는 심사 조건을 함께 안내하세요."},
            {"id": "GUARANTEED_RETURN", "severity": "HIGH", "patterns": ["확정 수익", "확정수익", "guaranteed", "guaranteed return", "guaranteed profit", "保证收益", "lợi nhuận chắc chắn", "必ず利益", "untung pasti"], "rationale": "수익 확정·보장 표현은 과장 또는 오인 소지가 큽니다.", "suggested_revision": "조건 충족 시 가능한 혜택과 제한 조건을 분리해 표시하세요."},
            {"id": "EVERYONE_BEST_RATE", "severity": "MEDIUM", "patterns": ["누구나", "모든 고객", "everyone", "所有客户", "ai cũng", "全員", "semua nasabah"], "rationale": "모든 고객 대상 표현은 실제 조건과 충돌할 수 있습니다.", "suggested_revision": "대상 조건, 가입 한도, 심사 기준을 명확히 고지하세요."},
            {"id": "GUARANTEED_APPROVAL", "severity": "CRITICAL", "patterns": ["100% 승인", "100% 가입 승인", "100%가입승인", "100% 가입", "무조건 승인", "무조건 가입 승인", "즉시 승인", "신용점수 상관없이", "심사 없음", "심사없이", "everyone approved", "langsung disetujui", "được duyệt vay"], "rationale": "대출 승인 보장 표현은 고위험입니다.", "suggested_revision": "심사 결과에 따라 승인 여부와 조건이 달라질 수 있음을 명시하세요."},
            {"id": "LOWEST_RATE_GUARANTEE", "severity": "HIGH", "patterns": ["최저금리 보장", "최저 금리 보장", "최저금리보장", "업계 최저금리", "업계 최저 금리", "최고 금리 보장", "최고금리 보장", "최고금리보장", "lowest rate guaranteed", "best rate guaranteed", "保证最低利率"], "rationale": "최저/최고 금리 보장 표현은 실제 적용 금리·조건과 충돌하여 소비자 오인을 유발할 수 있습니다.", "suggested_revision": "적용 금리는 시장 상황·심사 결과에 따라 달라질 수 있으며 우대 조건을 함께 안내하세요."},
        ],
        "required_disclosures": {
            "deposit": ["우대금리 조건", "가입 한도", "세전/세후 여부", "중도해지 조건"],
            "loan": ["심사 조건", "금리 범위", "상환 조건", "신용도 영향"],
            "investment": ["원금 손실 가능성", "수수료", "과거 수익률이 미래 수익을 보장하지 않음"],
            "card": ["전월 실적 조건", "혜택 한도", "행사 기간"],
        },
    }


@lru_cache(maxsize=1)
def load_marketing_standards() -> dict[str, Any]:
    path = STANDARDS_DIR / "financial_marketing.yaml"
    if not path.exists():
        return _fallback_standards()
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else _fallback_standards()
    except Exception:
        return _fallback_standards()
