from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from .engine import analyze_with_engine
from .reporting import render_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compliance Sentinel 금융 마케팅 콘텐츠 AI 심의관")
    parser.add_argument("text", nargs="?", help="심의할 마케팅 콘텐츠 초안. 없으면 stdin 사용")
    parser.add_argument("--file", help="분석할 텍스트 파일")
    parser.add_argument("--audit", default="audit_logs/compliance_audit.jsonl", help="감사 로그 JSONL 경로")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    parser.add_argument(
        "--engine",
        choices=["auto", "deterministic"],
        default="auto",
        help="실행 엔진 선택: auto는 USE_LANGGRAPH=1이면 LangGraph, 아니면 deterministic fallback",
    )
    return parser


def read_input(args: argparse.Namespace) -> str:
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    if args.text:
        return args.text
    return sys.stdin.read()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    text = read_input(args).strip()
    if not text:
        parser.error("text or --file is required")
    result = analyze_with_engine(
        text,
        audit_path=args.audit,
        prefer_langgraph=args.engine == "auto",
    )
    state = result.state
    if args.json:
        payload = dict(state.final_report)
        payload["execution_engine"] = result.engine
        if result.fallback_reason:
            payload["engine_fallback_reason"] = result.fallback_reason
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if result.fallback_reason:
            print(f"[engine: {result.engine}, fallback: {result.fallback_reason}]", file=sys.stderr)
        else:
            print(f"[engine: {result.engine}]", file=sys.stderr)
        print(render_markdown(state.final_report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
