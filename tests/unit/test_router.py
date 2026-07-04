"""router.py — Router classifier + RoutingDecision + history append."""
from __future__ import annotations

from pathlib import Path

import pytest

from compliance_sentinel.router import (
    Router,
    RoutingDecision,
    RouterError,
    _is_quoted_value,
    _minimal_yaml_parse,
    _next_nonempty_is_list_item,
    _parse_scalar,
    _split_flow,
    append_routing_history,
)


class TestParseScalar:
    def test_integer(self):
        assert _parse_scalar("42") == 42

    def test_float(self):
        assert _parse_scalar("3.14") == 3.14

    def test_boolean(self):
        assert _parse_scalar("true") is True
        assert _parse_scalar("false") is False

    def test_null(self):
        assert _parse_scalar("null") is None

    def test_string(self):
        assert _parse_scalar("hello") == "hello"

    def test_quoted_string(self):
        assert _parse_scalar('"quoted"') == "quoted"


class TestIsQuotedValue:
    def test_double_quoted(self):
        assert _is_quoted_value('"text"') is True

    def test_single_quoted(self):
        assert _is_quoted_value("'text'") is True

    def test_unquoted(self):
        assert _is_quoted_value("text") is False


def _make_decision(**overrides):
    """RoutingDecision 빌더 — 실제 9 필수 + 1 optional 시그니처 정합."""
    defaults = dict(
        raw_input="원본 텍스트",
        domain="advertisement",
        domain_confidence="HIGH",
        domain_matched_keyword="광고",
        complexity="medium",
        quality="standard",
        collaboration="solo",
        automation="standard",
        matched_pipeline=None,
        routed_workflow="/evolve",
    )
    defaults.update(overrides)
    return RoutingDecision(**defaults)


class TestRoutingDecision:
    def test_construction_with_required_fields(self):
        decision = _make_decision()
        assert decision.domain == "advertisement"
        assert decision.complexity == "medium"
        assert decision.routed_workflow == "/evolve"

    def test_default_optional_fields(self):
        decision = _make_decision()
        assert decision.routed_options == []
        assert decision.routed_model_tier == "standard"
        assert decision.is_pipeline is False
        assert decision.pipeline_steps == []
        assert decision.dry_run is False

    def test_to_dict_returns_full_payload(self):
        decision = _make_decision(routed_options=["--with-review"])
        d = decision.to_dict()
        assert d["domain"] == "advertisement"
        assert d["routed_workflow"] == "/evolve"
        assert d["routed_options"] == ["--with-review"]
        assert "raw_input" in d
        assert "complexity" in d

    def test_pipeline_decision(self):
        decision = _make_decision(
            matched_pipeline="design_then_implement",
            is_pipeline=True,
            pipeline_steps=[{"command": "/evolve-sc-design"}, {"command": "/evolve"}],
        )
        assert decision.is_pipeline is True
        assert len(decision.pipeline_steps) == 2


class TestRouterClassify:
    def test_classify_returns_decision(self, monkeypatch):
        # Router는 routing-table.yaml에 의존 — minimal valid table 필요
        # 실패해도 RouterError 또는 fallback 처리
        try:
            router = Router()
            decision = router.classify("원금 보장 광고")
            assert isinstance(decision, RoutingDecision)
        except (RouterError, FileNotFoundError, OSError):
            pytest.skip("routing-table.yaml not available in test env")


class TestAppendRoutingHistory:
    def test_appends_to_log(self, tmp_path: Path, monkeypatch):
        from compliance_sentinel import router as router_mod
        log_path = tmp_path / "history.log"
        monkeypatch.setattr(router_mod, "ROUTING_HISTORY_LOG", log_path)

        decision = _make_decision(complexity="simple")
        append_routing_history(decision, outcome="success")
        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")
        # log에 도메인, 워크플로우 또는 outcome 표시
        assert any(token in content for token in ["advertisement", "/evolve", "success"])

    def test_appends_multiple_entries(self, tmp_path: Path, monkeypatch):
        from compliance_sentinel import router as router_mod
        log_path = tmp_path / "history.log"
        monkeypatch.setattr(router_mod, "ROUTING_HISTORY_LOG", log_path)

        for outcome in ["success", "failure", "pending"]:
            append_routing_history(_make_decision(), outcome=outcome)

        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

    def test_log_is_tab_separated_7_cols(self, tmp_path: Path, monkeypatch):
        from compliance_sentinel import router as router_mod
        log_path = tmp_path / "history.log"
        monkeypatch.setattr(router_mod, "ROUTING_HISTORY_LOG", log_path)
        append_routing_history(_make_decision(), outcome="success")
        cols = log_path.read_text(encoding="utf-8").strip().split("\t")
        assert len(cols) == 7


class TestParseScalarExtra:
    def test_empty_returns_none(self):
        assert _parse_scalar("") is None

    def test_single_quoted(self):
        assert _parse_scalar("'hi'") == "hi"

    def test_null_alias_tilde(self):
        assert _parse_scalar("~") is None

    def test_case_insensitive_true(self):
        assert _parse_scalar("True") is True
        assert _parse_scalar("TRUE") is True


class TestSplitFlow:
    def test_basic_comma_separated(self):
        assert _split_flow("a, b, c") == ["a", "b", "c"]

    def test_nested_brackets_preserved(self):
        result = _split_flow("[a, b], c")
        assert len(result) == 2
        assert result[0] == "[a, b]"

    def test_empty(self):
        assert _split_flow("") == []


class TestNextNonemptyIsListItem:
    def test_returns_true_when_next_is_list(self):
        lines = ["key:", "  - item1", "  - item2"]
        assert _next_nonempty_is_list_item(lines, 1, parent_indent=0) is True

    def test_returns_false_when_next_is_dict(self):
        lines = ["key:", "  nested: value"]
        assert _next_nonempty_is_list_item(lines, 1, parent_indent=0) is False

    def test_skips_comments(self):
        lines = ["key:", "  # comment", "  - item"]
        assert _next_nonempty_is_list_item(lines, 1, parent_indent=0) is True

    def test_returns_false_when_indent_lte_parent(self):
        lines = ["key:", "other: value"]
        assert _next_nonempty_is_list_item(lines, 1, parent_indent=0) is False


class TestMinimalYamlParse:
    def test_simple_key_value(self):
        result = _minimal_yaml_parse("name: alice\nage: 30")
        assert result["name"] == "alice"
        assert result["age"] == 30

    def test_nested_dict(self):
        text = """parent:
  child: value"""
        result = _minimal_yaml_parse(text)
        assert result["parent"]["child"] == "value"

    def test_inline_list(self):
        result = _minimal_yaml_parse("items: [a, b, c]")
        assert result["items"] == ["a", "b", "c"]

    def test_list_of_strings(self):
        text = """items:
  - apple
  - banana"""
        result = _minimal_yaml_parse(text)
        assert result["items"] == ["apple", "banana"]

    def test_skips_comments_and_blank_lines(self):
        text = """# comment

key: value
# another"""
        result = _minimal_yaml_parse(text)
        assert result == {"key": "value"}

    def test_boolean_and_null(self):
        result = _minimal_yaml_parse("flag: true\nempty: null")
        assert result["flag"] is True
        assert result["empty"] is None


class TestRouterFull:
    def test_classify_axis_default_value(self):
        try:
            router = Router()
        except (RouterError, FileNotFoundError):
            pytest.skip("routing table missing")
        # 키워드 매칭 없는 빈 문자열 → default 또는 standard
        decision = router.classify("text without keywords")
        assert decision.complexity in {"simple", "medium", "complex", "massive", "standard"}
        assert decision.quality in {"standard", "high", "critical"}

    def test_decide_model_tier_via_quality_critical(self):
        try:
            router = Router()
        except (RouterError, FileNotFoundError):
            pytest.skip("routing table missing")
        tier = router._decide_model_tier("any", "simple", "critical")
        assert tier == "critical"

    def test_decide_model_tier_via_complexity_complex(self):
        try:
            router = Router()
        except (RouterError, FileNotFoundError):
            pytest.skip("routing table missing")
        tier = router._decide_model_tier("any", "complex", "standard")
        assert tier == "deep"

    def test_decide_model_tier_law_question_simple_shallow(self):
        try:
            router = Router()
        except (RouterError, FileNotFoundError):
            pytest.skip("routing table missing")
        tier = router._decide_model_tier("law_question", "simple", "standard")
        assert tier == "shallow"

    def test_decide_model_tier_default_standard(self):
        try:
            router = Router()
        except (RouterError, FileNotFoundError):
            pytest.skip("routing table missing")
        tier = router._decide_model_tier("other", "medium", "standard")
        assert tier == "standard"

    def test_apply_quality_options_critical_cs_evolve(self):
        try:
            router = Router()
        except (RouterError, FileNotFoundError):
            pytest.skip("routing table missing")
        opts = router._apply_quality_options("critical", "medium", "cs-evolve", [])
        assert "--with-judge" in opts
        assert "--with-review" in opts
        assert "--strict" in opts

    def test_apply_quality_options_critical_complex_verifier_stack(self):
        try:
            router = Router()
        except (RouterError, FileNotFoundError):
            pytest.skip("routing table missing")
        opts = router._apply_quality_options("critical", "complex", "cs-evolve", [])
        assert "--verifier-stack" in opts

    def test_apply_quality_options_critical_team(self):
        try:
            router = Router()
        except (RouterError, FileNotFoundError):
            pytest.skip("routing table missing")
        opts = router._apply_quality_options("critical", "medium", "cs-evolve-team", [])
        assert "--strict" in opts
        assert "--adversarial" in opts
        assert "--codex-review" in opts

    def test_apply_quality_options_high_review(self):
        try:
            router = Router()
        except (RouterError, FileNotFoundError):
            pytest.skip("routing table missing")
        opts = router._apply_quality_options("high", "medium", "cs-evolve", [])
        assert "--with-review" in opts

    def test_apply_quality_options_standard_no_change(self):
        try:
            router = Router()
        except (RouterError, FileNotFoundError):
            pytest.skip("routing table missing")
        opts = router._apply_quality_options("standard", "simple", "cs-evolve", [])
        assert opts == []

    def test_apply_quality_options_critical_incompatible_workflow(self):
        try:
            router = Router()
        except (RouterError, FileNotFoundError):
            pytest.skip("routing table missing")
        # critical + cs-research → 옵션 부착 금지 (silent failure 차단)
        opts = router._apply_quality_options("critical", "medium", "cs-research", [])
        assert opts == []

    def test_apply_quality_options_idempotent(self):
        try:
            router = Router()
        except (RouterError, FileNotFoundError):
            pytest.skip("routing table missing")
        opts = router._apply_quality_options(
            "critical", "medium", "cs-evolve", ["--with-judge"],
        )
        # 이미 존재 → 중복 추가 안 함
        assert opts.count("--with-judge") == 1

    def test_router_error_when_table_missing(self, tmp_path):
        with pytest.raises(RouterError):
            Router(table_path=tmp_path / "missing.yaml")


class TestRouterMain:
    def test_classify_subcommand_json(self, capsys):
        from compliance_sentinel.router import main
        try:
            result = main(["classify", "원금 보장 광고", "--json"])
        except (FileNotFoundError, OSError, Exception) as e:
            if "Routing table" in str(e):
                pytest.skip("routing table missing")
            raise
        assert result == 0
        captured = capsys.readouterr()
        assert "{" in captured.out
        assert "domain" in captured.out

    def test_classify_subcommand_text(self, capsys):
        from compliance_sentinel.router import main
        try:
            result = main(["classify", "광고 텍스트"])
        except Exception as e:
            if "Routing table" in str(e):
                pytest.skip("routing table missing")
            raise
        assert result == 0
        captured = capsys.readouterr()
        assert "domain" in captured.out

    def test_route_subcommand_dry_run(self, capsys, tmp_path, monkeypatch):
        from compliance_sentinel import router as router_mod
        from compliance_sentinel.router import main
        monkeypatch.setattr(router_mod, "ROUTING_HISTORY_LOG", tmp_path / "history.log")
        try:
            result = main(["route", "광고 텍스트", "--dry-run", "--explain"])
        except Exception as e:
            if "Routing table" in str(e):
                pytest.skip("routing table missing")
            raise
        assert result == 0

    def test_route_subcommand_json(self, capsys, tmp_path, monkeypatch):
        from compliance_sentinel import router as router_mod
        from compliance_sentinel.router import main
        monkeypatch.setattr(router_mod, "ROUTING_HISTORY_LOG", tmp_path / "history.log")
        try:
            result = main(["route", "광고", "--json", "--dry-run"])
        except Exception as e:
            if "Routing table" in str(e):
                pytest.skip("routing table missing")
            raise
        assert result == 0
        captured = capsys.readouterr()
        assert "{" in captured.out

    def test_status_subcommand_no_log(self, capsys, tmp_path, monkeypatch):
        from compliance_sentinel import router as router_mod
        from compliance_sentinel.router import main
        monkeypatch.setattr(router_mod, "ROUTING_HISTORY_LOG", tmp_path / "missing.log")
        result = main(["status"])
        assert result == 0
        captured = capsys.readouterr()
        assert "없음" in captured.out

    def test_status_subcommand_with_log(self, capsys, tmp_path, monkeypatch):
        from compliance_sentinel import router as router_mod
        from compliance_sentinel.router import main
        log_path = tmp_path / "history.log"
        log_path.write_text("2026-01-01T00:00:00Z\tdomain\tworkflow\treq\tsuccess\tstandard\t-\n",
                            encoding="utf-8")
        monkeypatch.setattr(router_mod, "ROUTING_HISTORY_LOG", log_path)
        result = main(["status", "--limit", "5"])
        assert result == 0
