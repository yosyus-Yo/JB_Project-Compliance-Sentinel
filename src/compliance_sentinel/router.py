"""Request Router — SEAS /auto 5-Phase 패턴을 JB 환경에 맞춰 압축한 결정론적 라우터.

목적:
  사용자 입력 → 5축(domain, complexity, quality, collaboration, automation) 분류
              → 파이프라인 감지
              → 최적 workflow + options 결정
              → routing_history.log에 7-col TSV append

특징:
  - **결정론적**: LLM 호출 0건. 동일 입력 → 동일 출력 (재현성 보장, AC-010).
  - **Single source**: 모든 규칙은 .cs-brain/routing-table.yaml. 본 모듈은 yaml 해석만.
  - **CLI 통합**: compliance-sentinel router classify|route|status

설계 출처:
  - SEAS .opencode/routing-table.yaml + .claude/skills/auto/SKILL.md
  - CLAUDE.md SP#18 Retrieval/Computation vs Reasoning 분리

비고:
  - PyYAML 부재 시 `yaml` 표준 라이브러리 fallback 시도. 둘 다 없으면 minimal parser.
"""
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUTING_TABLE_PATH = PROJECT_ROOT / ".cs-brain" / "routing-table.yaml"
ROUTING_HISTORY_LOG = PROJECT_ROOT / "audit_logs" / "routing_history.log"


# ──────────────────────────────────────────────────────────────────
# YAML loader (PyYAML optional)
# ──────────────────────────────────────────────────────────────────

def _load_yaml(path: Path) -> dict:
    """PyYAML이 있으면 사용, 없으면 minimal parser. 본 routing-table.yaml은 단순 구조라 가능."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        return _minimal_yaml_parse(text)


def _minimal_yaml_parse(text: str) -> dict:
    """Minimal YAML parser — 본 routing-table.yaml 구조 한정 (nested dict + lists + strings).

    Limits: anchor/alias 미지원, flow style 미지원, multiline string 미지원.
    실 사용 환경에서는 PyYAML 설치 권장 (pyproject.toml dev extras에 이미 등록).
    """
    result: dict = {}
    stack: list[tuple[int, Any]] = [(-1, result)]
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        indent = len(line) - len(line.lstrip())
        # pop stack until parent indent
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else result

        stripped = line.strip()
        # list item
        if stripped.startswith("- "):
            value = stripped[2:].strip()
            if not isinstance(parent, list):
                # convert latest key's value to list
                raise ValueError(f"YAML parse: unexpected list at line {i}: {raw}")
            if ":" in value and not _is_quoted_value(value):
                key, val = value.split(":", 1)
                obj: dict = {key.strip(): _parse_scalar(val.strip())}
                parent.append(obj)
                stack.append((indent + 2, obj))
            elif value.startswith("{") and value.endswith("}"):
                # flow dict — minimal {k: v, k2: v2}
                inner = value[1:-1]
                obj = {}
                for pair in _split_flow(inner):
                    k, v = pair.split(":", 1)
                    obj[k.strip()] = _parse_scalar(v.strip())
                parent.append(obj)
            else:
                parent.append(_parse_scalar(value))
            i += 1
            continue
        # key: value
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not value:
                # nested — next line starts child
                # decide whether dict or list by looking ahead
                if _next_nonempty_is_list_item(lines, i + 1, indent):
                    parent[key] = []
                    stack.append((indent, parent[key]))
                else:
                    parent[key] = {}
                    stack.append((indent, parent[key]))
            else:
                if value.startswith("[") and value.endswith("]"):
                    # inline list
                    inner = value[1:-1]
                    parent[key] = [_parse_scalar(x.strip()) for x in _split_flow(inner) if x.strip()]
                else:
                    parent[key] = _parse_scalar(value)
        i += 1
    return result


def _is_quoted_value(s: str) -> bool:
    return s.startswith("'") or s.startswith('"')


def _parse_scalar(s: str) -> Any:
    if not s:
        return None
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1]
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    if s.lower() == "null" or s == "~":
        return None
    try:
        if "." not in s:
            return int(s)
        return float(s)
    except ValueError:
        return s


def _split_flow(s: str) -> list[str]:
    out: list[str] = []
    depth = 0
    buf: list[str] = []
    for c in s:
        if c == "," and depth == 0:
            out.append("".join(buf).strip())
            buf = []
        else:
            if c in "[{":
                depth += 1
            elif c in "]}":
                depth -= 1
            buf.append(c)
    if buf:
        out.append("".join(buf).strip())
    return out


def _next_nonempty_is_list_item(lines: list[str], start: int, parent_indent: int) -> bool:
    for j in range(start, len(lines)):
        line = lines[j].rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        ind = len(line) - len(line.lstrip())
        if ind <= parent_indent:
            return False
        return line.lstrip().startswith("- ")
    return False


# ──────────────────────────────────────────────────────────────────
# Routing decision data class
# ──────────────────────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    raw_input: str
    domain: str
    domain_confidence: str  # HIGH | MED | LOW
    domain_matched_keyword: str
    complexity: str
    quality: str
    collaboration: str
    automation: str
    matched_pipeline: Optional[str]
    routed_workflow: str
    routed_options: list[str] = field(default_factory=list)
    routed_model_tier: str = "standard"
    is_pipeline: bool = False
    pipeline_steps: list[dict] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────
# Core router
# ──────────────────────────────────────────────────────────────────

class RouterError(Exception):
    pass


class Router:
    def __init__(self, table_path: Path = ROUTING_TABLE_PATH) -> None:
        if not table_path.exists():
            raise RouterError(f"Routing table not found: {table_path}")
        self.table = _load_yaml(table_path)
        if not isinstance(self.table, dict) or "domains" not in self.table:
            raise RouterError(f"Routing table missing 'domains': {table_path}")

    def classify(self, text: str) -> RoutingDecision:
        domain, conf, matched_kw = self._classify_domain(text)
        complexity = self._classify_axis(text, "complexity")
        quality = self._classify_axis(text, "quality")
        collaboration = self._classify_axis(text, "collaboration")
        automation = self._classify_axis(text, "automation")

        matched_pipeline = self._detect_pipeline(text)
        is_pipeline = matched_pipeline is not None

        if is_pipeline:
            pipeline_def = self.table.get("pipelines", {}).get(matched_pipeline, {})
            pipeline_steps = pipeline_def.get("steps", []) or []
            # 파이프라인 첫 step을 routed_workflow로 (Phase 4 진입점)
            first = pipeline_steps[0] if pipeline_steps else {}
            routed_workflow = first.get("workflow", "cs-evolve")
            routed_options = list(first.get("options", []) or [])
        else:
            domain_def = self.table["domains"].get(domain, {})
            routed_workflow = domain_def.get("default_workflow", "cs-evolve")
            routed_options = list(domain_def.get("default_options", []) or [])
            pipeline_steps = []

        # 품질에 따른 옵션 누적 (매트릭스 single source — 본 라우터는 단순 + 명시 옵션만)
        routed_options = self._apply_quality_options(quality, complexity, routed_workflow, routed_options)

        # 모델 tier 결정
        routed_model_tier = self._decide_model_tier(domain, complexity, quality)

        return RoutingDecision(
            raw_input=text,
            domain=domain,
            domain_confidence=conf,
            domain_matched_keyword=matched_kw,
            complexity=complexity,
            quality=quality,
            collaboration=collaboration,
            automation=automation,
            matched_pipeline=matched_pipeline,
            routed_workflow=routed_workflow,
            routed_options=routed_options,
            routed_model_tier=routed_model_tier,
            is_pipeline=is_pipeline,
            pipeline_steps=pipeline_steps,
        )

    def _classify_domain(self, text: str) -> tuple[str, str, str]:
        """첫 매칭 도메인 반환. YAML의 domains는 우선순위 순으로 정의됨."""
        domains = self.table.get("domains", {})
        # dict 순서 보존 (Python 3.7+ + minimal_yaml_parse도 OrderedDict 보존)
        for name, definition in domains.items():
            if not isinstance(definition, dict):
                continue
            patterns = definition.get("patterns") or []
            for pattern in patterns:
                try:
                    if re.search(pattern, text):
                        return name, "HIGH", pattern
                except re.error:
                    # invalid regex 무시
                    continue
        return "terms_review", "LOW", "(default fallback)"

    def _classify_axis(self, text: str, axis: str) -> str:
        """complexity/quality/collaboration/automation 분류."""
        axis_def = self.table.get(axis, {})
        default_value = None
        for value_name, value_def in axis_def.items():
            if not isinstance(value_def, dict):
                continue
            if value_def.get("default"):
                default_value = value_name
                continue
            keywords = value_def.get("keywords") or []
            for kw in keywords:
                if kw in text:
                    return value_name
        return default_value or "standard"

    def _detect_pipeline(self, text: str) -> Optional[str]:
        """pipelines 섹션 patterns와 직접 매칭. first-match wins."""
        pipelines = self.table.get("pipelines", {})
        for name, definition in pipelines.items():
            if not isinstance(definition, dict):
                continue
            patterns = definition.get("patterns") or []
            for pattern in patterns:
                try:
                    if re.search(pattern, text):
                        return name
                except re.error:
                    continue
        return None

    def _apply_quality_options(
        self,
        quality: str,
        complexity: str,
        workflow: str,
        base_options: list[str],
    ) -> list[str]:
        """품질 등급에 따른 옵션 누적. cs-evolve 계열만 인식.

        SEAS Phase 2 매트릭스 single source 정책 적용.
        """
        options = list(base_options)
        cs_evolve_family = {"cs-evolve", "cs-evolve-superclaude", "cs-evolve-loop"}

        if quality == "critical":
            if workflow in cs_evolve_family:
                for opt in ("--with-judge", "--with-review", "--strict"):
                    if opt not in options:
                        options.append(opt)
                if complexity in {"complex", "massive"} and "--verifier-stack" not in options:
                    options.append("--verifier-stack")
            elif workflow == "cs-evolve-team":
                for opt in ("--strict", "--adversarial", "--codex-review"):
                    if opt not in options:
                        options.append(opt)
            # cs-research / cs-ship / cs-cso 등 비호환 명령어는 옵션 부착 금지 (silent failure 차단)
        elif quality == "high":
            if workflow in cs_evolve_family and "--with-review" not in options:
                options.append("--with-review")
        # standard + simple 면제 룰은 router 단계에서 적용 안 함 (사용자 정책 — 옵션 미부착이 default)
        return options

    def _decide_model_tier(self, domain: str, complexity: str, quality: str) -> str:
        if quality == "critical":
            return "critical"
        if complexity in {"complex", "massive"}:
            return "deep"
        if domain in {"law_question", "policy_change"} and complexity == "simple":
            return "shallow"
        return "standard"


# ──────────────────────────────────────────────────────────────────
# Routing history log (7-col TSV)
# ──────────────────────────────────────────────────────────────────

def append_routing_history(decision: RoutingDecision, outcome: str = "pending") -> None:
    """7-col TSV: ts<TAB>domain<TAB>workflow<TAB>request_summary<TAB>outcome<TAB>tier<TAB>pipeline."""
    ROUTING_HISTORY_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    request_summary = decision.raw_input.replace("\t", " ").replace("\n", " ")[:80]
    pipeline = decision.matched_pipeline or "-"
    row = "\t".join([
        ts,
        decision.domain,
        decision.routed_workflow,
        request_summary,
        outcome,
        decision.routed_model_tier,
        pipeline,
    ])
    with ROUTING_HISTORY_LOG.open("a", encoding="utf-8") as fh:
        fh.write(row + "\n")


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Compliance Sentinel Request Router (Phase 6, P1)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_classify = sub.add_parser("classify", help="입력을 5축으로 분류만 (라우팅 결정 X)")
    p_classify.add_argument("text", help="분석할 텍스트")
    p_classify.add_argument("--json", action="store_true")

    p_route = sub.add_parser("route", help="입력 → 5축 분류 + 워크플로우 라우팅 결정")
    p_route.add_argument("text", help="분석할 텍스트")
    p_route.add_argument("--json", action="store_true")
    p_route.add_argument("--dry-run", action="store_true", help="routing_history.log에 기록 안 함")
    p_route.add_argument("--explain", action="store_true", help="결정 이유 표시")

    p_status = sub.add_parser("status", help="routing_history.log 최근 통계")
    p_status.add_argument("--limit", type=int, default=10)

    args = parser.parse_args(argv)
    router = Router()

    if args.cmd == "classify":
        decision = router.classify(args.text)
        out = {
            "domain": decision.domain,
            "complexity": decision.complexity,
            "quality": decision.quality,
            "collaboration": decision.collaboration,
            "automation": decision.automation,
            "matched_pipeline": decision.matched_pipeline,
        }
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            for k, v in out.items():
                print(f"{k:20s}: {v}")
        return 0

    if args.cmd == "route":
        decision = router.classify(args.text)
        if not args.dry_run:
            append_routing_history(decision)
        if args.json:
            print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
            return 0
        print(f"workflow:  {decision.routed_workflow}")
        print(f"options:   {' '.join(decision.routed_options) if decision.routed_options else '(none)'}")
        print(f"model:     {decision.routed_model_tier}")
        if decision.is_pipeline:
            print(f"pipeline:  {decision.matched_pipeline} ({len(decision.pipeline_steps)} steps)")
            for i, step in enumerate(decision.pipeline_steps, 1):
                opts = " ".join(step.get("options", []) or [])
                print(f"  step {i}: {step.get('workflow')} {opts}")
        if args.explain:
            print()
            print(f"domain:    {decision.domain} (conf={decision.domain_confidence}, kw='{decision.domain_matched_keyword}')")
            print(f"5축:       complexity={decision.complexity} / quality={decision.quality} / collaboration={decision.collaboration} / automation={decision.automation}")
        return 0

    if args.cmd == "status":
        if not ROUTING_HISTORY_LOG.exists():
            print("routing_history.log 없음 (아직 라우팅 결정 없음)")
            return 0
        lines = ROUTING_HISTORY_LOG.read_text(encoding="utf-8").strip().split("\n")
        print(f"총 {len(lines)} routing 결정")
        for line in lines[-args.limit:]:
            print(f"  {line}")
        return 0

    parser.error(f"unknown command: {args.cmd}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
