"""API 엔드포인트 테스트 — httpx ASGITransport로 /health·/analyze 검증.

starlette 0.27 `TestClient`는 httpx 0.28에서 제거된 `app=` 인자에 의존하여
비호환이다. 이를 우회하기 위해 httpx.AsyncClient + ASGITransport를 직접 사용한다.
`.[api]` extra(fastapi) 미설치 환경에서는 전체 모듈이 skip된다.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="API 테스트는 .[api] extra 필요")

import httpx
import pytest_asyncio

from compliance_sentinel.api import app

pytestmark = [
    pytest.mark.skipif(app is None, reason="FastAPI 미설치 — api:app is None"),
    pytest.mark.asyncio,
]


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=10.0) as ac:
        yield ac


async def test_health_returns_ok(client) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    # health 응답에 운영 메트릭 필드(app/pid/agent_reuse/runtime 등)가 추가됨 — status=ok만 확인
    assert response.json()["status"] == "ok"


async def test_analyze_returns_final_report_for_valid_content(client) -> None:
    response = await client.post("/analyze", json={"text": "JB 적금 신규 출시 안내"})
    assert response.status_code == 200
    body = response.json()
    for field in ("review_type", "approval_status", "risk_level", "confidence", "findings", "audit_log_id"):
        assert field in body, f"final_report에 '{field}' 필드 누락"
    assert body["review_type"] == "marketing_content_compliance"
    assert body["execution_engine"] in {"deterministic", "langgraph"}


async def test_analyze_flags_high_risk_violation(client) -> None:
    response = await client.post("/analyze", json={"text": "누구나 연 8% 확정 수익, 원금 보장!"})
    assert response.status_code == 200
    body = response.json()
    assert body["risk_level"] in {"HIGH", "CRITICAL"}
    assert len(body["findings"]) > 0


async def test_analyze_rejects_empty_text(client) -> None:
    response = await client.post("/analyze", json={"text": ""})
    assert response.status_code == 422


async def test_analyze_rejects_whitespace_only_text(client) -> None:
    response = await client.post("/analyze", json={"text": "   "})
    assert response.status_code == 422
    assert response.json()["detail"] == "text is required"


async def test_analyze_rejects_missing_text_field(client) -> None:
    # text 필드 누락 → Pydantic 스키마 검증 실패 (FastAPI 표준 422)
    response = await client.post("/analyze", json={"language": "ko"})
    assert response.status_code == 422


async def test_analyze_echoes_provided_metadata(client) -> None:
    response = await client.post(
        "/analyze",
        json={
            "text": "JB 카드 혜택 안내",
            "language": "ko",
            "channel": "banner",
            "product_type": "card",
            "target_audience": "general_customer",
        },
    )
    assert response.status_code == 200
    provided = response.json()["input_completeness"]["provided_metadata"]
    assert provided == {
        "language": "ko",
        "channel": "banner",
        "product_type": "card",
        "target_audience": "general_customer",
    }
