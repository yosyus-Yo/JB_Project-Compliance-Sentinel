"""law_open_api.py — URL builders + helpers + client paths (urlopen mocked)."""
from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

from compliance_sentinel.law_open_api import (
    API_BASE,
    API_SEARCH,
    DEFAULT_TIMEOUT_SECONDS,
    LawApiArticle,
    LawOpenApiClient,
    _article_text,
    _clean_text,
    _digits,
    _first_payload_value,
    _first_value,
    _lsInfoP_url,
    _lsSc_search_url,
    _normalize_article_no,
    _normalize_date,
    _normalize_law_name,
    _official_law_url,
    _parse_article_response,
    _walk_dicts,
    from_env,
)


class TestConstants:
    def test_api_base_is_law_go_kr(self):
        assert "law.go.kr" in API_BASE

    def test_api_search_is_law_go_kr(self):
        assert "law.go.kr" in API_SEARCH

    def test_timeout_positive(self):
        assert DEFAULT_TIMEOUT_SECONDS > 0


class TestDigits:
    def test_extracts_digits(self):
        assert _digits("제15조") == "15"

    def test_alphanumeric(self):
        assert _digits("abc123def") == "123"

    def test_no_digits_returns_empty(self):
        assert _digits("no_digits") == ""

    def test_only_digits(self):
        assert _digits("987654") == "987654"


class TestNormalizeLawName:
    def test_removes_spaces(self):
        result = _normalize_law_name("개인 정보 보호 법")
        assert " " not in result

    def test_lowercases(self):
        result = _normalize_law_name("Banking Act")
        assert result == "bankingact"

    def test_replaces_special_dot(self):
        # "ㆍ" → "·"
        result = _normalize_law_name("법ㆍ령")
        assert "·" in result


class TestNormalizeArticleNo:
    def test_extracts_number(self):
        assert "15" in _normalize_article_no("제15조")

    def test_already_numeric(self):
        assert _normalize_article_no("15") == "15"

    def test_with_의_suffix(self):
        # "제15조의2" → "15-2"
        result = _normalize_article_no("제15조의2")
        assert result == "15-2"


class TestNormalizeDate:
    def test_yyyymmdd_dashed(self):
        assert _normalize_date("20200101") == "2020-01-01"

    def test_already_normalized(self):
        result = _normalize_date("2020-01-01")
        assert result == "2020-01-01"

    def test_short_returns_as_is(self):
        assert _normalize_date("xyz") == "xyz"


class TestCleanText:
    def test_strips_and_collapses_whitespace(self):
        assert _clean_text("  hello   world\n\n") == "hello world"

    def test_empty(self):
        assert _clean_text("") == ""


class TestUrlBuilders:
    def test_official_law_url_with_article(self):
        url = _official_law_url("개인정보보호법", "15")
        assert "law.go.kr" in url

    def test_official_law_url_without_article(self):
        url = _official_law_url("개인정보보호법", "")
        assert "law.go.kr" in url

    def test_lsInfoP_url_with_mst_article_date(self):
        url = _lsInfoP_url("123456", "15", "2020-01-01")
        assert "lsiSeq=123456" in url
        # article anchor 추가됨
        assert "%EC%A0%9C" in url or "15" in url

    def test_lsInfoP_url_minimal(self):
        url = _lsInfoP_url("123456")
        assert "lsiSeq=123456" in url

    def test_lsInfoP_non_numeric_article_no_anchor(self):
        # article_no가 숫자 아니면 anchor 추가 안 함
        url = _lsInfoP_url("123456", "abc")
        assert "lsiSeq=123456" in url

    def test_lsSc_search_url(self):
        url = _lsSc_search_url("은행연합회 자율규제")
        assert "lsSc.do" in url
        assert "query=" in url


class TestWalkDicts:
    def test_yields_dicts(self):
        result = list(_walk_dicts({"a": 1, "b": {"c": 2}}))
        assert len(result) == 2

    def test_handles_list(self):
        result = list(_walk_dicts([{"a": 1}, {"b": 2}]))
        assert len(result) == 2

    def test_empty(self):
        assert list(_walk_dicts({})) == [{}]


class TestFirstValue:
    def test_returns_first_match(self):
        node = {"a": "1", "b": "2"}
        assert _first_value(node, ["a", "b"]) == "1"

    def test_skips_empty_string(self):
        node = {"a": "", "b": "2"}
        assert _first_value(node, ["a", "b"]) == "2"

    def test_skips_none(self):
        node = {"a": None, "b": "2"}
        assert _first_value(node, ["a", "b"]) == "2"

    def test_no_match(self):
        assert _first_value({"a": 1}, ["x", "y"]) is None


class TestFirstPayloadValue:
    def test_deep_nested_match(self):
        payload = {"outer": {"inner": {"target": "found"}}}
        assert _first_payload_value(payload, ["target"]) == "found"

    def test_no_match(self):
        assert _first_payload_value({}, ["target"]) is None


class TestArticleText:
    def test_extracts_조문내용(self):
        node = {"조문내용": "조문 본문입니다"}
        result = _article_text(node)
        assert "조문 본문" in result

    def test_appends_항내용(self):
        node = {"조문내용": "본문", "항": [{"항내용": "1. 첫째"}]}
        result = _article_text(node)
        assert "본문" in result

    def test_empty_node(self):
        result = _article_text({})
        assert result == ""


class TestLawApiArticle:
    def test_class_importable(self):
        assert LawApiArticle is not None


class TestLawOpenApiClient:
    def test_disabled_without_key(self, monkeypatch):
        monkeypatch.delenv("LAW_OPEN_API_KEY", raising=False)
        client = LawOpenApiClient()
        assert client.enabled is False

    def test_enabled_with_key(self, monkeypatch):
        monkeypatch.setenv("LAW_OPEN_API_KEY", "fake-key")
        client = LawOpenApiClient()
        assert client.enabled is True

    def test_search_law_returns_none_when_disabled(self):
        client = LawOpenApiClient(api_key=None)
        assert client.search_law("개인정보보호법") is None

    def test_fetch_article_returns_none_when_disabled(self):
        client = LawOpenApiClient(api_key=None)
        assert client.fetch_article("개인정보보호법", "15") is None

    def test_resolve_public_url_fallback_to_search(self):
        client = LawOpenApiClient(api_key=None)
        url = client.resolve_public_url("자율규제")
        assert "lsSc.do" in url

    def test_search_law_caches_results(self):
        # cache 동작 확인 — 같은 입력으로 두 번 호출 시 같은 결과
        client = LawOpenApiClient(api_key="fake")
        client._mst_cache["개인정보보호법"] = {"mst": "123", "law_name": "개인정보보호법",
                                                "law_id": "", "effective_date": "",
                                                "source_url": ""}
        result = client.search_law("개인정보보호법")
        assert result is not None
        assert result["mst"] == "123"


class TestSearchLawMocked:
    def test_search_law_with_urlopen_mock(self, monkeypatch):
        client = LawOpenApiClient(api_key="fake-key")
        mock_response = {
            "LawSearch": {
                "law": [
                    {"법령명한글": "개인정보보호법", "법령일련번호": "999",
                     "시행일자": "20200101", "법령ID": "L1"},
                ]
            }
        }

        class FakeResponse:
            def __init__(self, data):
                self._data = json.dumps(data).encode("utf-8")
            def read(self):
                return self._data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        with patch("urllib.request.urlopen", return_value=FakeResponse(mock_response)):
            result = client.search_law("개인정보보호법")
        assert result is not None
        assert result["mst"] == "999"

    def test_search_law_handles_network_error(self):
        client = LawOpenApiClient(api_key="fake-key")
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            assert client.search_law("any") is None

    def test_search_law_empty_results(self):
        client = LawOpenApiClient(api_key="fake-key")

        class FakeResponse:
            def __init__(self, data):
                self._data = json.dumps(data).encode("utf-8")
            def read(self):
                return self._data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        with patch("urllib.request.urlopen", return_value=FakeResponse({"LawSearch": {"law": []}})):
            assert client.search_law("missing") is None


class TestParseArticleResponse:
    def test_invalid_json_returns_none(self):
        result = _parse_article_response(
            "not-json", law_name="X", article_no="15", source_url="https://x",
        )
        assert result is None

    def test_no_matching_article(self):
        body = json.dumps({"법령": {"조문": [{"조문번호": "1", "조문내용": "본문"}]}})
        result = _parse_article_response(
            body, law_name="X", article_no="15", source_url="https://x",
        )
        assert result is None

    def test_finds_matching_article(self):
        body = json.dumps({"법령": {"조문": [
            {"조문번호": "15", "조문내용": "개인정보 수집 본문",
             "조문여부": "조문", "시행일자": "20200101"},
        ]}})
        result = _parse_article_response(
            body, law_name="개인정보보호법", article_no="15", source_url="https://x",
        )
        assert result is not None
        assert "본문" in result.text


class TestFromEnv:
    def test_no_env_returns_none(self, monkeypatch):
        monkeypatch.delenv("LAW_OPEN_API_KEY", raising=False)
        assert from_env() is None

    def test_with_env_returns_client(self, monkeypatch):
        monkeypatch.setenv("LAW_OPEN_API_KEY", "key")
        client = from_env()
        assert client is not None
        assert client.enabled is True
