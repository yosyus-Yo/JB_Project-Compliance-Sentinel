"""cli.py — argparse-based CLI entry."""
from __future__ import annotations

import argparse

import pytest

from compliance_sentinel.cli import build_parser, read_input


class TestBuildParser:
    def test_returns_argparse_parser(self):
        parser = build_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parser_help_callable(self):
        parser = build_parser()
        # --help 사용 가능 확인 (system exit 발생 정상)
        with pytest.raises(SystemExit):
            parser.parse_args(["--help"])


class TestReadInput:
    def test_reads_positional_text_argument(self):
        # 실제 시그니처: text 가 positional (nargs="?") + --file + stdin fallback
        parser = build_parser()
        args = parser.parse_args(["광고 카피"])
        result = read_input(args)
        assert result == "광고 카피"

    def test_reads_from_file(self, tmp_path):
        from pathlib import Path
        file_path = tmp_path / "input.txt"
        file_path.write_text("파일 내용", encoding="utf-8")
        parser = build_parser()
        args = parser.parse_args(["--file", str(file_path)])
        result = read_input(args)
        assert result == "파일 내용"

    def test_file_priority_over_text(self, tmp_path):
        from pathlib import Path
        file_path = tmp_path / "input.txt"
        file_path.write_text("파일 우선", encoding="utf-8")
        parser = build_parser()
        args = parser.parse_args(["--file", str(file_path), "텍스트 인자"])
        result = read_input(args)
        assert result == "파일 우선"

    def test_default_engine_auto(self):
        parser = build_parser()
        args = parser.parse_args(["x"])
        assert args.engine == "auto"

    def test_json_flag(self):
        parser = build_parser()
        args = parser.parse_args(["x", "--json"])
        assert args.json is True

    def test_engine_deterministic(self):
        parser = build_parser()
        args = parser.parse_args(["x", "--engine", "deterministic"])
        assert args.engine == "deterministic"

    def test_audit_default(self):
        parser = build_parser()
        args = parser.parse_args(["x"])
        assert "audit_logs" in args.audit


class TestMain:
    def test_main_text_argument(self, tmp_audit_path, monkeypatch, capsys):
        from compliance_sentinel.cli import main
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        result = main(["테스트 입력", "--audit", str(tmp_audit_path), "--engine", "deterministic"])
        assert result == 0

    def test_main_json_output(self, tmp_audit_path, monkeypatch, capsys):
        from compliance_sentinel.cli import main
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        result = main(["테스트", "--audit", str(tmp_audit_path), "--json",
                       "--engine", "deterministic"])
        assert result == 0
        captured = capsys.readouterr()
        # JSON 출력
        assert "{" in captured.out

    def test_main_file_input(self, tmp_path, tmp_audit_path, monkeypatch):
        from compliance_sentinel.cli import main
        monkeypatch.delenv("USE_LANGGRAPH", raising=False)
        input_file = tmp_path / "in.txt"
        input_file.write_text("파일 내용", encoding="utf-8")
        result = main(["--file", str(input_file), "--audit", str(tmp_audit_path),
                       "--engine", "deterministic"])
        assert result == 0

    def test_main_empty_input_errors(self, tmp_audit_path, monkeypatch):
        from compliance_sentinel.cli import main
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(""))
        with pytest.raises(SystemExit):
            main(["--audit", str(tmp_audit_path)])
