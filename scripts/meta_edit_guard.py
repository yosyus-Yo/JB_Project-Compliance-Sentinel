#!/usr/bin/env python3
"""Meta Edit Guard — `.cs-brain/` 및 메타 인프라 자동 편집 차단 (AC-015).

목적:
  SEAS L4 보안 layer 등가 — readonly 패턴 + routing-table schema + KB checksum을
  baseline에 기록하고, CI/pre-commit에서 변경 감지하여 차단.

  기존 `cs_brain.merge()`의 readonly 보호는 **Brain 자동 학습 layer 내부만** 동작 —
  사용자가 vi로 직접 `.cs-brain/project_brain.yaml` readonly 패턴 수정 시 무방비.
  본 가드가 이 사각지대를 닫음.

CLI:
  python scripts/meta_edit_guard.py record    # 현재 상태를 baseline으로 기록
  python scripts/meta_edit_guard.py check     # baseline 대비 변경 감지 (exit 1 if violation)
  python scripts/meta_edit_guard.py status    # 현재 baseline 상태 표시

Bypass:
  CS_BYPASS_META_GUARD=1  → check가 violation 발견해도 exit 0 (stderr 경고만, ablation 측정 전용)

설치:
  pre-commit hook에 등록: `python scripts/meta_edit_guard.py check`

출처:
  - spec.md AC-015 ".cs-brain/ 자동 편집 차단"
  - plan.md §12 SEAS bash-guard.sh → "Python AST validator" 이식 매핑
  - SEAS .claude/hooks/meta-edit-guard.sh (advisory 모드)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRAIN_DIR = PROJECT_ROOT / ".cs-brain"
BASELINE_FILE = BRAIN_DIR / "meta-baseline.json"

# 보호 대상 — 본 가드가 변경 감지하는 파일들
PROTECTED_FILES = {
    "project_brain.yaml": BRAIN_DIR / "project_brain.yaml",
    "routing-table.yaml": BRAIN_DIR / "routing-table.yaml",
    "laws.json": PROJECT_ROOT / "data" / "laws.json",
    "ablation-config.yaml": BRAIN_DIR / "ablation-config.yaml",
}

# routing-table 최소 schema 요건 (변경 감지)
REQUIRED_ROUTING_KEYS = {"domains", "pipelines"}
EXPECTED_DOMAIN_COUNT_MIN = 6  # 8 domain 기준이지만 일부 제거 가능 — 6 미만이면 anomaly
EXPECTED_PIPELINE_COUNT_MIN = 2  # 3 pipeline 기준


def sha256_file(path: Path) -> str:
    """파일 sha256 hash. 파일 부재 시 'MISSING' 반환."""
    if not path.exists():
        return "MISSING"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_readonly_patterns(brain_yaml_path: Path) -> list[dict]:
    """project_brain.yaml에서 readonly: true 패턴만 추출. PyYAML 없으면 cs_brain의 fallback 사용."""
    if not brain_yaml_path.exists():
        return []
    # cs_brain의 yaml loader 활용 (PyYAML optional fallback 포함)
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from compliance_sentinel.cs_brain import _load_yaml  # type: ignore
        data = _load_yaml(brain_yaml_path)
    except Exception:
        return []
    patterns = data.get("learned_patterns") or []
    return [p for p in patterns if p.get("readonly") is True]


def routing_table_schema(yaml_path: Path) -> dict:
    """routing-table.yaml의 top-level schema 추출 (domain 수, pipeline 수, 필수 키)."""
    if not yaml_path.exists():
        return {"present": False, "domain_count": 0, "pipeline_count": 0, "missing_keys": list(REQUIRED_ROUTING_KEYS)}
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from compliance_sentinel.cs_brain import _load_yaml  # type: ignore
        data = _load_yaml(yaml_path)
    except Exception:
        return {"present": True, "domain_count": -1, "pipeline_count": -1, "missing_keys": ["parse_error"]}
    domains = data.get("domains") or {}
    pipelines = data.get("pipelines") or {}
    missing = [k for k in REQUIRED_ROUTING_KEYS if k not in data]
    return {
        "present": True,
        "domain_count": len(domains) if isinstance(domains, dict) else -1,
        "pipeline_count": len(pipelines) if isinstance(pipelines, dict) else -1,
        "missing_keys": missing,
    }


@dataclass
class Baseline:
    """현 시점의 메타 인프라 상태 snapshot."""
    schema_version: str = "meta-baseline/v1"
    recorded_at: str = ""
    file_hashes: dict[str, str] = field(default_factory=dict)
    readonly_pattern_count: int = 0
    readonly_pattern_ids: list[str] = field(default_factory=list)
    readonly_pattern_hashes: dict[str, str] = field(default_factory=dict)  # id → content hash
    routing_schema: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def compute_baseline(baseline_path: Path = BASELINE_FILE) -> Baseline:
    """현재 상태로 Baseline 객체 생성."""
    import time
    b = Baseline(recorded_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    for key, path in PROTECTED_FILES.items():
        b.file_hashes[key] = sha256_file(path)
    # readonly 패턴 상세 hash
    readonly_patterns = extract_readonly_patterns(PROTECTED_FILES["project_brain.yaml"])
    b.readonly_pattern_count = len(readonly_patterns)
    b.readonly_pattern_ids = [p.get("id", "") for p in readonly_patterns]
    for p in readonly_patterns:
        pid = p.get("id", "")
        if not pid:
            continue
        # 패턴 본문 (context + content + confidence)을 hash
        canonical = json.dumps({
            "context": p.get("context", ""),
            "content": p.get("content", ""),
            "confidence": p.get("confidence"),
            "severity": p.get("severity"),
        }, sort_keys=True, ensure_ascii=False)
        b.readonly_pattern_hashes[pid] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    # routing schema
    b.routing_schema = routing_table_schema(PROTECTED_FILES["routing-table.yaml"])
    return b


def load_baseline(baseline_path: Path = BASELINE_FILE) -> Optional[Baseline]:
    if not baseline_path.exists():
        return None
    try:
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        return Baseline(
            schema_version=data.get("schema_version", "meta-baseline/v1"),
            recorded_at=data.get("recorded_at", ""),
            file_hashes=data.get("file_hashes", {}),
            readonly_pattern_count=data.get("readonly_pattern_count", 0),
            readonly_pattern_ids=data.get("readonly_pattern_ids", []),
            readonly_pattern_hashes=data.get("readonly_pattern_hashes", {}),
            routing_schema=data.get("routing_schema", {}),
        )
    except (json.JSONDecodeError, OSError):
        return None


def save_baseline(baseline: Baseline, path: Path = BASELINE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class Violation:
    rule: str
    severity: str  # critical | warning
    detail: str


def check_violations(*, baseline_path: Path = BASELINE_FILE) -> list[Violation]:
    """현재 상태를 baseline과 비교하여 violation 목록 반환.

    Returns:
        violations: 빈 list면 PASS. 1개라도 있으면 critical/warning.
    """
    violations: list[Violation] = []
    baseline = load_baseline(baseline_path)
    if baseline is None:
        violations.append(Violation(
            rule="no_baseline",
            severity="warning",
            detail=f"baseline 파일이 없습니다. 먼저 `record` 실행하세요. ({baseline_path})",
        ))
        return violations

    current = compute_baseline()

    # 1. readonly 패턴 변경 감지 (critical)
    for pid, base_hash in baseline.readonly_pattern_hashes.items():
        cur_hash = current.readonly_pattern_hashes.get(pid)
        if cur_hash is None:
            violations.append(Violation(
                rule="readonly_pattern_removed",
                severity="critical",
                detail=f"readonly 패턴 {pid} 삭제됨 — 법무/보안 승인 패턴 절대 보호 위반",
            ))
        elif cur_hash != base_hash:
            violations.append(Violation(
                rule="readonly_pattern_modified",
                severity="critical",
                detail=f"readonly 패턴 {pid} 내용 변경 — 자동 학습 또는 사용자 직접 편집",
            ))

    # 2. routing-table schema 위반 (critical)
    base_schema = baseline.routing_schema or {}
    cur_schema = current.routing_schema
    if base_schema.get("present") and not cur_schema.get("present"):
        violations.append(Violation(
            rule="routing_table_missing",
            severity="critical",
            detail="routing-table.yaml이 사라졌습니다 — Phase 6 라우터 기반 파괴",
        ))
    if cur_schema.get("missing_keys"):
        violations.append(Violation(
            rule="routing_table_schema",
            severity="critical",
            detail=f"routing-table.yaml 필수 키 누락: {cur_schema['missing_keys']}",
        ))
    if cur_schema.get("domain_count", 0) < EXPECTED_DOMAIN_COUNT_MIN:
        violations.append(Violation(
            rule="routing_table_domain_count",
            severity="warning",
            detail=f"domain 수 {cur_schema['domain_count']} < {EXPECTED_DOMAIN_COUNT_MIN} — 도메인 누락 의심",
        ))
    if cur_schema.get("pipeline_count", 0) < EXPECTED_PIPELINE_COUNT_MIN:
        violations.append(Violation(
            rule="routing_table_pipeline_count",
            severity="warning",
            detail=f"pipeline 수 {cur_schema['pipeline_count']} < {EXPECTED_PIPELINE_COUNT_MIN}",
        ))

    # 3. 파일 hash 변경 (warning — laws.json/ablation-config.yaml는 변경 가능하나 추적)
    for key, base_hash in baseline.file_hashes.items():
        cur_hash = current.file_hashes.get(key, "MISSING")
        if base_hash == "MISSING" and cur_hash != "MISSING":
            # 신규 추가는 OK
            continue
        if cur_hash == "MISSING" and base_hash != "MISSING":
            violations.append(Violation(
                rule=f"file_deleted:{key}",
                severity="critical" if key in {"routing-table.yaml", "project_brain.yaml"} else "warning",
                detail=f"보호 파일 {key} 삭제됨",
            ))
        elif cur_hash != base_hash:
            # routing-table / project_brain은 readonly 패턴/schema로 별도 검증 — 여기는 hash 변경 정보만
            severity = "warning"  # critical은 위 readonly/schema 검사가 담당
            violations.append(Violation(
                rule=f"file_modified:{key}",
                severity=severity,
                detail=f"{key} hash 변경 (record 이후 편집됨) — 의도된 변경이면 `record` 재실행",
            ))

    return violations


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────


def cmd_record(args) -> int:
    baseline = compute_baseline()
    save_baseline(baseline)
    if args.json:
        print(json.dumps(baseline.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"✅ baseline 기록 완료: {BASELINE_FILE}")
        print(f"   recorded_at: {baseline.recorded_at}")
        print(f"   readonly 패턴: {baseline.readonly_pattern_count}건")
        print(f"   routing domains: {baseline.routing_schema.get('domain_count')}, pipelines: {baseline.routing_schema.get('pipeline_count')}")
    return 0


def cmd_check(args) -> int:
    violations = check_violations()
    bypass = os.environ.get("CS_BYPASS_META_GUARD") == "1"

    if args.json:
        print(json.dumps({
            "violations": [asdict(v) for v in violations],
            "critical_count": sum(1 for v in violations if v.severity == "critical"),
            "warning_count": sum(1 for v in violations if v.severity == "warning"),
            "bypass_active": bypass,
        }, ensure_ascii=False, indent=2))
    else:
        if not violations:
            print("✅ 메타 인프라 무결성 PASS — 모든 readonly 패턴 + routing schema 보존")
            return 0
        critical_count = sum(1 for v in violations if v.severity == "critical")
        warning_count = sum(1 for v in violations if v.severity == "warning")
        marker = "🔴" if critical_count > 0 else "⚠️"
        print(f"{marker} 메타 인프라 변경 감지: critical={critical_count} warning={warning_count}")
        for v in violations:
            sev_marker = "🔴" if v.severity == "critical" else "⚠️ "
            print(f"  {sev_marker} [{v.rule}] {v.detail}")

    critical_count = sum(1 for v in violations if v.severity == "critical")
    if critical_count > 0:
        if bypass:
            print(f"⚠️  [CS_BYPASS_META_GUARD=1] critical violation {critical_count}건이 있지만 bypass 모드로 진행", file=sys.stderr)
            return 0
        return 1
    return 0


def cmd_status(args) -> int:
    baseline = load_baseline()
    if baseline is None:
        print(f"baseline 없음 ({BASELINE_FILE}). 먼저 `record` 실행하세요.")
        return 0
    if args.json:
        print(json.dumps(baseline.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"baseline: {BASELINE_FILE}")
        print(f"recorded_at: {baseline.recorded_at}")
        print(f"readonly 패턴: {baseline.readonly_pattern_count}건 — {', '.join(baseline.readonly_pattern_ids)}")
        print(f"routing domains: {baseline.routing_schema.get('domain_count')}, pipelines: {baseline.routing_schema.get('pipeline_count')}")
        print(f"보호 파일 hashes:")
        for key, h in baseline.file_hashes.items():
            print(f"  {key:25s} {h[:16]}{'...' if h != 'MISSING' else ''}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Compliance Sentinel Meta Edit Guard (AC-015)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rec = sub.add_parser("record", help="현재 상태를 baseline으로 기록")
    p_rec.add_argument("--json", action="store_true")

    p_chk = sub.add_parser("check", help="baseline 대비 변경 감지 (critical 시 exit 1)")
    p_chk.add_argument("--json", action="store_true")

    p_st = sub.add_parser("status", help="현재 baseline 상태 표시")
    p_st.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "record":
        return cmd_record(args)
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "status":
        return cmd_status(args)
    parser.error(f"unknown command: {args.cmd}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
