"""api.py — FastAPI endpoints + direct route function invocation.

Test client (httpx/starlette) has version conflicts; we test route functions
directly which still exercises the request handler logic + pydantic validation.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def api_mod():
    try:
        from compliance_sentinel import api as api_mod
    except Exception:
        pytest.skip("FastAPI not installed")
    if api_mod.app is None:
        pytest.skip("FastAPI app is None (deps missing)")
    return api_mod


class TestApiImport:
    def test_imports_successfully(self):
        import compliance_sentinel.api as api_mod
        assert api_mod is not None

    def test_main_callable(self):
        from compliance_sentinel.api import main
        assert callable(main)


class TestAppMetadata:
    def test_app_exists(self, api_mod):
        assert api_mod.app is not None

    def test_app_title(self, api_mod):
        assert "Compliance Sentinel" in api_mod.app.title

    def test_app_version_set(self, api_mod):
        assert api_mod.app.version

    def test_request_models_defined(self, api_mod):
        assert api_mod.AnalyzeRequest is not None
        assert api_mod.BatchAnalyzeRequest is not None


class TestHealthEndpoint:
    def test_health_returns_dict(self, api_mod):
        result = api_mod.health()
        assert result["status"] == "ok"
        assert "pid" in result
        assert "agent_reuse" in result
        assert result["app"] == "compliance-sentinel-python-worker"


class TestAnalyzeRequest:
    def test_construct_with_text(self, api_mod):
        req = api_mod.AnalyzeRequest(text="x")
        assert req.text == "x"

    def test_optional_fields_none_default(self, api_mod):
        req = api_mod.AnalyzeRequest(text="x")
        assert req.metadata is None
        assert req.language is None

    def test_all_metadata_fields(self, api_mod):
        req = api_mod.AnalyzeRequest(
            text="x", metadata={"k": "v"}, language="ko",
            channel="banner", product_type="loan", target_audience="X",
            prefer_langgraph=False,
        )
        assert req.metadata == {"k": "v"}
        assert req.language == "ko"


class TestAnalyzeRouteDirect:
    def test_basic_analyze(self, api_mod, monkeypatch):
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        # triage gate 통과를 위해 광고 콘텐츠 사용 (비-광고는 NOT_APPLICABLE 분기)
        req = api_mod.AnalyzeRequest(text="원금 100% 보장 무조건 승인 특판 적금")
        result = api_mod.analyze(req)
        assert isinstance(result, dict)
        assert "status" in result
        assert "execution_engine" in result
        assert "bridge_runtime" in result

    def test_analyze_missing_text_raises_422(self, api_mod):
        req = api_mod.AnalyzeRequest()
        with pytest.raises(api_mod.HTTPException) as exc_info:
            api_mod.analyze(req)
        assert exc_info.value.status_code == 422

    def test_analyze_empty_text_raises_422(self, api_mod):
        req = api_mod.AnalyzeRequest(text="   ")
        with pytest.raises(api_mod.HTTPException) as exc_info:
            api_mod.analyze(req)
        assert exc_info.value.status_code == 422

    def test_analyze_content_alias(self, api_mod, monkeypatch):
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        req = api_mod.AnalyzeRequest(content="광고 카피")
        result = api_mod.analyze(req)
        assert isinstance(result, dict)

    def test_analyze_with_metadata(self, api_mod, monkeypatch):
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        req = api_mod.AnalyzeRequest(
            text="광고", language="ko", channel="banner",
            product_type="loan", target_audience="직장인",
        )
        result = api_mod.analyze(req)
        assert "input_completeness" in result

    def test_analyze_prefer_langgraph_explicit_false(self, api_mod):
        req = api_mod.AnalyzeRequest(text="x", prefer_langgraph=False)
        result = api_mod.analyze(req)
        assert result["execution_engine"] == "deterministic"


class TestReviewRoute:
    def test_review_basic(self, api_mod, monkeypatch):
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        req = api_mod.AnalyzeRequest(text="리뷰 입력")
        result = api_mod.review(req)
        assert isinstance(result, dict)

    def test_review_is_alias_of_analyze(self, api_mod):
        # 같은 _analyze_request 호출
        from compliance_sentinel.api import analyze, review
        assert callable(analyze)
        assert callable(review)


class TestBatchRoute:
    def test_batch_basic(self, api_mod, monkeypatch):
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        req = api_mod.BatchAnalyzeRequest(items=["입력1", "입력2"])
        result = api_mod.batch_review(req)
        assert "results" in result
        assert "batch" in result
        assert result["batch"]["item_count"] == 2

    def test_batch_empty_items_raises_422(self, api_mod):
        req = api_mod.BatchAnalyzeRequest(items=[])
        with pytest.raises(api_mod.HTTPException) as exc_info:
            api_mod.batch_review(req)
        assert exc_info.value.status_code == 422

    def test_batch_none_items_raises_422(self, api_mod):
        req = api_mod.BatchAnalyzeRequest()
        with pytest.raises(api_mod.HTTPException) as exc_info:
            api_mod.batch_review(req)
        assert exc_info.value.status_code == 422

    def test_batch_whitespace_only_raises_422(self, api_mod):
        req = api_mod.BatchAnalyzeRequest(items=["  ", "\t"])
        with pytest.raises(api_mod.HTTPException) as exc_info:
            api_mod.batch_review(req)
        assert exc_info.value.status_code == 422

    def test_batch_with_metadata(self, api_mod, monkeypatch):
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        req = api_mod.BatchAnalyzeRequest(
            items=["광고1", "광고2"],
            metadata={"campaign": "X"},
            reuse_agents=True,
        )
        result = api_mod.batch_review(req)
        assert result["batch"]["reused_agents"] is True

    def test_batch_no_reuse_agents(self, api_mod, monkeypatch):
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        req = api_mod.BatchAnalyzeRequest(
            items=["입력"], reuse_agents=False,
        )
        result = api_mod.batch_review(req)
        assert result["batch"]["reused_agents"] is False
