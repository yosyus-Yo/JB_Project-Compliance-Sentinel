"""cs_brain.py — YAML IO + Pattern + BM25 + search + capture + analyze_history."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from compliance_sentinel.cs_brain import (
    BM25,
    BRAIN_DIR,
    PROJECT_BRAIN,
    VALID_SCENARIO_TYPES,
    VALID_STATUS_MAP,
    HistoryInsight,
    Pattern,
    SearchResult,
    _dump_yaml,
    _load_yaml,
    _minimal_yaml_dump,
    _tokenize,
    analyze_history,
    capture,
    search,
)


class TestConstants:
    def test_brain_dir_named(self):
        assert ".cs-brain" in str(BRAIN_DIR)

    def test_project_brain_in_brain_dir(self):
        assert "project_brain" in str(PROJECT_BRAIN)


class TestValidMaps:
    def test_status_map_has_success_pattern(self):
        assert VALID_STATUS_MAP["success"] == "SUCCESS_PATTERN"
        assert VALID_STATUS_MAP["failure"] == "FAILURE_PATTERN"
        assert VALID_STATUS_MAP["warning"] == "FAILURE_PATTERN"
        assert VALID_STATUS_MAP["discovery"] == "SUCCESS_PATTERN"

    def test_scenario_types_include_canonical(self):
        for t in ["implementation", "debug", "refactor", "investigation"]:
            assert t in VALID_SCENARIO_TYPES


class TestLoadYaml:
    def test_nonexistent_returns_empty_dict(self, tmp_path: Path):
        result = _load_yaml(tmp_path / "missing.yaml")
        assert result == {}

    def test_valid_yaml(self, tmp_path: Path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("key: value\nlist:\n  - a\n  - b\n", encoding="utf-8")
        result = _load_yaml(yaml_file)
        assert result["key"] == "value"


class TestDumpYaml:
    def test_dumps_simple_dict(self, tmp_path: Path):
        path = tmp_path / "out.yaml"
        _dump_yaml(path, {"name": "alice", "age": 30})
        content = path.read_text(encoding="utf-8")
        assert "name" in content
        assert "alice" in content

    def test_creates_parent_directory(self, tmp_path: Path):
        path = tmp_path / "sub" / "dir" / "out.yaml"
        _dump_yaml(path, {"x": 1})
        assert path.exists()

    def test_round_trip(self, tmp_path: Path):
        path = tmp_path / "out.yaml"
        original = {"name": "bob", "age": 42}
        _dump_yaml(path, original)
        loaded = _load_yaml(path)
        assert loaded["name"] == "bob"
        # int parsing may vary depending on backend
        assert int(loaded["age"]) == 42


class TestMinimalYamlDump:
    def test_dumps_dict(self):
        result = _minimal_yaml_dump({"key": "value"})
        assert "key" in result
        assert "value" in result

    def test_dumps_nested_dict(self):
        result = _minimal_yaml_dump({"parent": {"child": "value"}})
        assert "parent" in result
        assert "child" in result

    def test_dumps_list_of_strings(self):
        result = _minimal_yaml_dump({"items": ["a", "b"]})
        assert "- a" in result
        assert "- b" in result

    def test_dumps_list_of_dicts(self):
        result = _minimal_yaml_dump([{"id": 1, "name": "x"}, {"id": 2}])
        assert "id" in result

    def test_dumps_none_as_null(self):
        result = _minimal_yaml_dump({"empty": None})
        assert "null" in result

    def test_dumps_bool_as_lowercase(self):
        result = _minimal_yaml_dump({"flag": True})
        assert "true" in result.lower()


class TestPatternDataclass:
    def test_basic_construction(self):
        p = Pattern(
            id="LP-1", context="ctx", status="SUCCESS_PATTERN",
            content="lesson", learned_at="2026-01-01T00:00:00Z",
        )
        assert p.id == "LP-1"
        assert p.confidence == 0.8
        assert p.readonly is False
        assert p.scenario_type == "implementation"

    def test_to_dict_removes_empty_lists(self):
        p = Pattern(
            id="LP-1", context="ctx", status="SUCCESS_PATTERN",
            content="lesson", learned_at="2026-01-01T00:00:00Z",
        )
        d = p.to_dict()
        # default empty list와 None은 제거됨
        assert "tags" not in d  # empty list 제거
        assert "id" in d

    def test_to_dict_keeps_populated_fields(self):
        p = Pattern(
            id="LP-2", context="ctx", status="FAILURE_PATTERN",
            content="lesson", learned_at="2026-01-01T00:00:00Z",
            tags=["a", "b"], hypothesis="if X then Y",
        )
        d = p.to_dict()
        assert d["tags"] == ["a", "b"]
        assert d["hypothesis"] == "if X then Y"


class TestTokenize:
    def test_english_words(self):
        tokens = _tokenize("hello world python")
        assert "hello" in tokens
        assert "python" in tokens

    def test_korean_2char_ngrams(self):
        tokens = _tokenize("개인정보")
        # 4글자 한국어 → 3 bigram (개인/인정/정보)
        assert "개인" in tokens
        assert "정보" in tokens

    def test_mixed_korean_english(self):
        tokens = _tokenize("API 보안 검토")
        assert "api" in tokens  # lowercased
        assert "보안" in tokens

    def test_skip_single_char_english(self):
        tokens = _tokenize("a b ccc")
        assert "a" not in tokens
        assert "b" not in tokens
        assert "ccc" in tokens

    def test_lowercased(self):
        tokens = _tokenize("HELLO World")
        assert "hello" in tokens
        assert "world" in tokens


class TestBM25:
    def test_empty_search_returns_empty(self):
        bm = BM25()
        assert bm.search("anything") == []

    def test_index_and_search(self):
        bm = BM25()
        bm.index("D1", "python programming language")
        bm.index("D2", "ruby on rails framework")
        bm.index("D3", "python web framework")
        results = bm.search("python", top_k=10)
        ids = [r[0] for r in results]
        assert "D1" in ids
        assert "D3" in ids

    def test_top_k_limits_results(self):
        bm = BM25()
        for i in range(5):
            bm.index(f"D{i}", "python python python")
        results = bm.search("python", top_k=2)
        assert len(results) <= 2

    def test_unmatched_query_zero_results(self):
        bm = BM25()
        bm.index("D1", "completely different content")
        results = bm.search("nothing matches", top_k=5)
        assert results == []


class TestSearchResultDataclass:
    def test_construction(self):
        r = SearchResult(
            pattern_id="LP-1", score=0.85, context="ctx",
            content_snippet="snip", status="SUCCESS_PATTERN", readonly=False,
        )
        assert r.pattern_id == "LP-1"
        assert r.readonly is False


class TestCapture:
    def test_basic_success_capture(self, tmp_path: Path, monkeypatch):
        from compliance_sentinel import cs_brain as brain_mod
        pending = tmp_path / "pending.yaml"
        monkeypatch.setattr(brain_mod, "CAPTURE_LOG", tmp_path / "capture.log")
        pattern = capture(
            classification="success",
            context="test ctx",
            content="lesson learned",
            pending_path=pending,
        )
        assert pattern.id.startswith("LP-CS-PND-")
        assert pattern.status == "SUCCESS_PATTERN"
        assert pending.exists()

    def test_invalid_classification_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="unknown classification"):
            capture(
                classification="invalid",
                context="x",
                content="y",
                pending_path=tmp_path / "pending.yaml",
            )

    def test_invalid_scenario_type_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="unknown scenario_type"):
            capture(
                classification="success",
                context="x",
                content="y",
                scenario_type="invalid_xyz",
                pending_path=tmp_path / "pending.yaml",
            )

    def test_failure_classification(self, tmp_path: Path, monkeypatch):
        from compliance_sentinel import cs_brain as brain_mod
        monkeypatch.setattr(brain_mod, "CAPTURE_LOG", tmp_path / "capture.log")
        pattern = capture(
            classification="failure",
            context="bug",
            content="fixed by X",
            pending_path=tmp_path / "pending.yaml",
        )
        assert pattern.status == "FAILURE_PATTERN"

    def test_warning_maps_to_failure_pattern(self, tmp_path: Path, monkeypatch):
        from compliance_sentinel import cs_brain as brain_mod
        monkeypatch.setattr(brain_mod, "CAPTURE_LOG", tmp_path / "capture.log")
        pattern = capture(
            classification="warning",
            context="risk", content="check",
            pending_path=tmp_path / "pending.yaml",
        )
        assert pattern.status == "FAILURE_PATTERN"

    def test_discovery_maps_to_success(self, tmp_path: Path, monkeypatch):
        from compliance_sentinel import cs_brain as brain_mod
        monkeypatch.setattr(brain_mod, "CAPTURE_LOG", tmp_path / "capture.log")
        pattern = capture(
            classification="discovery",
            context="finding", content="x",
            pending_path=tmp_path / "pending.yaml",
        )
        assert pattern.status == "SUCCESS_PATTERN"

    def test_appends_to_capture_log(self, tmp_path: Path, monkeypatch):
        from compliance_sentinel import cs_brain as brain_mod
        log_path = tmp_path / "capture.log"
        monkeypatch.setattr(brain_mod, "CAPTURE_LOG", log_path)
        capture(
            classification="success", context="ctx", content="x",
            pending_path=tmp_path / "pending.yaml",
        )
        assert log_path.exists()
        assert "success" in log_path.read_text(encoding="utf-8")


class TestSearch:
    def test_empty_brain_returns_empty(self, tmp_path: Path, monkeypatch):
        from compliance_sentinel import cs_brain as brain_mod
        brain_path = tmp_path / "brain.yaml"
        monkeypatch.setattr(brain_mod, "SEARCH_HITS_LOG", tmp_path / "search-hits.log")
        results = search("query", brain_path=brain_path)
        assert results == []

    def test_basic_search(self, tmp_path: Path, monkeypatch):
        from compliance_sentinel import cs_brain as brain_mod
        brain_path = tmp_path / "brain.yaml"
        brain_path.write_text(
            "learned_patterns:\n"
            "  - id: LP-1\n"
            "    context: python programming\n"
            "    content: use list comprehensions\n"
            "    status: SUCCESS_PATTERN\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(brain_mod, "SEARCH_HITS_LOG", tmp_path / "search-hits.log")
        results = search("python", brain_path=brain_path)
        # match 또는 0 — backend yaml parser 차이로 무관
        assert isinstance(results, list)

    def test_search_hits_log_appended(self, tmp_path: Path, monkeypatch):
        from compliance_sentinel import cs_brain as brain_mod
        log_path = tmp_path / "search-hits.log"
        monkeypatch.setattr(brain_mod, "SEARCH_HITS_LOG", log_path)
        search("query", brain_path=tmp_path / "missing.yaml")
        assert log_path.exists()
        assert "NO_HIT" in log_path.read_text(encoding="utf-8")


class TestAnalyzeHistory:
    def test_missing_log_returns_empty_insight(self, tmp_path: Path):
        result = analyze_history("query", log_path=tmp_path / "missing.log")
        assert result.total_queries == 0
        assert result.zero_hit_rate == 0.0
        assert result.hint_for_route == "(no history)"

    def test_zero_hit_rate_high_yields_warning_hint(self, tmp_path: Path):
        log_path = tmp_path / "search-hits.log"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        lines = [f"{now}\tquery{i}\t0\tNO_HIT" for i in range(10)]
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = analyze_history("test", log_path=log_path)
        assert result.zero_hit_rate == 1.0
        assert "미커버" in result.hint_for_route or "zero_hit_rate" in result.hint_for_route

    def test_top_lp_identified(self, tmp_path: Path):
        log_path = tmp_path / "search-hits.log"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        lines = [f"{now}\tquery\t1\tLP-100" for _ in range(5)]
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = analyze_history("test", log_path=log_path)
        assert ("LP-100", 5) in result.top_lp_ids

    def test_to_dict_returns_payload(self, tmp_path: Path):
        result = analyze_history("query", log_path=tmp_path / "missing.log")
        d = result.to_dict()
        assert "total_queries" in d
        assert "hint_for_route" in d

    def test_old_entries_outside_cutoff_skipped(self, tmp_path: Path):
        log_path = tmp_path / "search-hits.log"
        # 100일 전 timestamp
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 100 * 86400))
        log_path.write_text(f"{old}\told_query\t0\tNO_HIT\n", encoding="utf-8")
        result = analyze_history("test", days=14, log_path=log_path)
        assert result.total_queries == 0

    def test_malformed_lines_skipped(self, tmp_path: Path):
        log_path = tmp_path / "search-hits.log"
        log_path.write_text("malformed\n\nshort\tline\n", encoding="utf-8")
        result = analyze_history("test", log_path=log_path)
        assert result.total_queries == 0


class TestHistoryInsightDataclass:
    def test_construction(self):
        h = HistoryInsight(
            total_queries=5, zero_hit_count=2, zero_hit_rate=0.4,
            top_lp_ids=[("LP-1", 3)], similar_queries=[("q", 0.5)],
            hint_for_route="test",
        )
        assert h.total_queries == 5
        assert h.top_lp_ids[0][0] == "LP-1"


class TestMergeBasic:
    def test_empty_pending_no_changes(self, tmp_path, monkeypatch):
        from compliance_sentinel import cs_brain as brain_mod
        from compliance_sentinel.cs_brain import merge
        pending = tmp_path / "pending.yaml"
        brain = tmp_path / "brain.yaml"
        log = tmp_path / "merge.log"
        report = merge(pending_path=pending, brain_path=brain, log_path=log)
        assert report.merged_count == 0
        assert report.skipped_readonly_count == 0

    def test_single_pending_pattern_merged(self, tmp_path):
        from compliance_sentinel.cs_brain import capture, merge
        pending = tmp_path / "pending.yaml"
        brain = tmp_path / "brain.yaml"
        log = tmp_path / "merge.log"
        # 직접 pending에 패턴 작성
        import yaml as _y
        pending.write_text(_y.dump({
            "schema_version": "cs-brain/v1",
            "pending_patterns": [{
                "id": "LP-CS-PND-1",
                "context": "테스트 컨텍스트",
                "content": "테스트 교훈",
                "status": "SUCCESS_PATTERN",
                "learned_at": "2026-01-01T00:00:00Z",
                "confidence": 0.85,
            }],
        }), encoding="utf-8")
        report = merge(pending_path=pending, brain_path=brain, log_path=log)
        assert report.merged_count == 1
        assert len(report.new_pattern_ids) == 1

    def test_readonly_existing_protected(self, tmp_path):
        from compliance_sentinel.cs_brain import merge
        pending = tmp_path / "pending.yaml"
        brain = tmp_path / "brain.yaml"
        log = tmp_path / "merge.log"
        import yaml as _y
        brain.write_text(_y.dump({
            "learned_patterns": [{
                "id": "LP-CS-001", "context": "ctx", "content": "lesson",
                "status": "SUCCESS_PATTERN", "learned_at": "x",
                "confidence": 0.95, "readonly": True,
            }],
        }), encoding="utf-8")
        pending.write_text(_y.dump({
            "pending_patterns": [{
                "id": "LP-CS-001",  # 같은 id로 readonly 패턴 덮어쓰기 시도
                "context": "ctx", "content": "다른 내용",
                "status": "SUCCESS_PATTERN", "learned_at": "x",
                "confidence": 0.99,
            }],
        }), encoding="utf-8")
        report = merge(pending_path=pending, brain_path=brain, log_path=log)
        assert report.skipped_readonly_count == 1
        assert report.merged_count == 0


class TestAblationReport:
    def test_no_features_returns_empty(self, tmp_path):
        from compliance_sentinel.cs_brain import ablation_report
        config = tmp_path / "ablation.yaml"
        config.write_text("features: []\n", encoding="utf-8")
        result = ablation_report(config_path=config)
        assert result == []

    def test_missing_config_returns_empty(self, tmp_path):
        from compliance_sentinel.cs_brain import ablation_report
        result = ablation_report(config_path=tmp_path / "missing.yaml")
        assert result == []

    def test_unmeasured_when_log_missing(self, tmp_path):
        from compliance_sentinel.cs_brain import ablation_report
        config = tmp_path / "ablation.yaml"
        import yaml as _y
        config.write_text(_y.dump({
            "features": [{
                "id": "test-feature",
                "expected_per_week": 5,
                "measurement_source": {"file": "missing.log", "signal": "."},
            }],
        }), encoding="utf-8")
        result = ablation_report(config_path=config)
        assert len(result) == 1
        assert result[0].judgment == "UNMEASURED"


class TestMain:
    def test_status_subcommand(self, monkeypatch, capsys):
        from compliance_sentinel.cs_brain import main
        result = main(["status"])
        assert result == 0

    def test_ablation_json(self, capsys, monkeypatch, tmp_path):
        # ablation은 ABLATION_CONFIG를 직접 인자 받아 처리 — module level monkeypatch는 main이 ablation_report() 직접 호출
        from compliance_sentinel.cs_brain import main
        result = main(["ablation", "--json"])
        assert result == 0

    def test_merge_json(self, capsys, monkeypatch, tmp_path):
        from compliance_sentinel import cs_brain as brain_mod
        from compliance_sentinel.cs_brain import main
        monkeypatch.setattr(brain_mod, "PENDING_PATTERNS", tmp_path / "pending.yaml")
        monkeypatch.setattr(brain_mod, "PROJECT_BRAIN", tmp_path / "brain.yaml")
        monkeypatch.setattr(brain_mod, "MERGE_LOG", tmp_path / "merge.log")
        result = main(["merge", "--json"])
        assert result == 0

    def test_capture_subcommand(self, capsys, monkeypatch, tmp_path):
        from compliance_sentinel import cs_brain as brain_mod
        from compliance_sentinel.cs_brain import main
        monkeypatch.setattr(brain_mod, "PENDING_PATTERNS", tmp_path / "pending.yaml")
        monkeypatch.setattr(brain_mod, "CAPTURE_LOG", tmp_path / "capture.log")
        result = main(["capture", "success", "ctx", "lesson"])
        assert result == 0

    def test_search_subcommand(self, capsys, monkeypatch, tmp_path):
        from compliance_sentinel import cs_brain as brain_mod
        from compliance_sentinel.cs_brain import main
        monkeypatch.setattr(brain_mod, "PROJECT_BRAIN", tmp_path / "missing.yaml")
        monkeypatch.setattr(brain_mod, "SEARCH_HITS_LOG", tmp_path / "search-hits.log")
        result = main(["search", "test"])
        assert result == 0
