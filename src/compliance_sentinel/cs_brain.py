"""Compliance Sentinel Brain — Self-Evolving Learning System (Phase 8, P3).

5 기능을 단일 모듈에 통합:
  1. capture   — 4 분류 (success/failure/warning/discovery)로 pending_patterns에 append
  2. search    — BM25 기반 패턴 검색 (sentence-transformers optional, BGE-M3)
  3. merge     — pending → project_brain.yaml (readonly 보호)
  4. ablation  — 30일 fire 빈도 측정 (HEALTHY/UNDERUSED/DEAD)
  5. analyze   — 메타 인사이트 (top LP, similar queries, zero_hit_rate)

설계 원칙:
  - 결정론적 + offline-first: PyYAML / sentence-transformers 부재 시 fallback
  - readonly 패턴 절대 보호 (LP-CS-030 같은 critical 도메인 지식)
  - CLI 통합: `cs-brain capture|search|merge|ablation|analyze`
  - Stop hook 의존 없음 — 사용자 manual `cs-brain merge` 호출

출처:
  - SEAS .opencode/brain/project_brain.yaml + .claude/rules/learning-loop.md
  - SEAS scripts/{capture-learning,search-patterns,sync-brain,ablation-report,sync-history-analyzer}.ts
"""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# PyYAML optional — fallback to minimal parser in router.py
try:
    import yaml as _yaml  # type: ignore
    _HAS_YAML = True
except ImportError:
    from .router import _load_yaml as _fallback_yaml_load
    _HAS_YAML = False

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BRAIN_DIR = PROJECT_ROOT / ".cs-brain"
PROJECT_BRAIN = BRAIN_DIR / "project_brain.yaml"
PENDING_PATTERNS = BRAIN_DIR / "pending_patterns.yaml"
ABLATION_CONFIG = BRAIN_DIR / "ablation-config.yaml"
CAPTURE_LOG = BRAIN_DIR / "capture.log"
MERGE_LOG = BRAIN_DIR / "merge.log"
SEARCH_HITS_LOG = PROJECT_ROOT / "audit_logs" / "search-hits.log"

VALID_STATUS_MAP = {
    "success": "SUCCESS_PATTERN",
    "failure": "FAILURE_PATTERN",
    "warning": "FAILURE_PATTERN",  # SEAS 분류: warning은 milder failure
    "discovery": "SUCCESS_PATTERN",
}

VALID_SCENARIO_TYPES = {
    "implementation",
    "debug",
    "refactor",
    "investigation",
    "integration",
    "migration",
    "testing",
    "research",
}


# ──────────────────────────────────────────────────────────────────
# YAML I/O helpers
# ──────────────────────────────────────────────────────────────────

def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if _HAS_YAML:
        return _yaml.safe_load(text) or {}
    return _fallback_yaml_load(path)  # type: ignore


def _dump_yaml(path: Path, data: dict) -> None:
    if _HAS_YAML:
        text = _yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    else:
        text = _minimal_yaml_dump(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _minimal_yaml_dump(data: Any, indent: int = 0) -> str:
    """Minimal YAML dumper — PyYAML 부재 시 fallback. project_brain.yaml 구조 한정."""
    lines: list[str] = []
    sp = "  " * indent
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{sp}{k}:")
                lines.append(_minimal_yaml_dump(v, indent + 1))
            elif v is None or v == "":
                lines.append(f"{sp}{k}: null")
            elif isinstance(v, str) and ("\n" in v or ":" in v):
                lines.append(f"{sp}{k}: |")
                for line in v.split("\n"):
                    lines.append(f"{sp}  {line}")
            elif isinstance(v, bool):
                lines.append(f"{sp}{k}: {'true' if v else 'false'}")
            else:
                lines.append(f"{sp}{k}: {v}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                first = True
                for k, v in item.items():
                    prefix = f"{sp}- " if first else f"{sp}  "
                    first = False
                    if isinstance(v, (dict, list)) and v:
                        lines.append(f"{prefix}{k}:")
                        lines.append(_minimal_yaml_dump(v, indent + 2))
                    elif isinstance(v, str) and "\n" in v:
                        lines.append(f"{prefix}{k}: |")
                        for line in v.split("\n"):
                            lines.append(f"{sp}    {line}")
                    elif isinstance(v, bool):
                        lines.append(f"{prefix}{k}: {'true' if v else 'false'}")
                    else:
                        lines.append(f"{prefix}{k}: {v}")
            else:
                lines.append(f"{sp}- {item}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# Pattern model
# ──────────────────────────────────────────────────────────────────

@dataclass
class Pattern:
    id: str
    context: str
    status: str  # SUCCESS_PATTERN | FAILURE_PATTERN
    content: str
    learned_at: str
    confidence: float = 0.8
    severity: Optional[str] = None  # critical | warning | info
    readonly: bool = False
    scenario_type: str = "implementation"
    tags: list[str] = field(default_factory=list)
    caused_by: list[str] = field(default_factory=list)
    hypothesis: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # null/빈 리스트 제거 (가독성). readonly=False는 기본값이며 pending
        # buffer에서는 무의미 — 생략하여 AgentShield memory-poisoning 오탐을
        # 피한다. .get("readonly")가 falsy로 동일 처리하므로 동작은 불변.
        out = {k: v for k, v in d.items() if v is not None and v != []}
        if out.get("readonly") is False:
            out.pop("readonly")
        return out


# ──────────────────────────────────────────────────────────────────
# T-802: Capture (4 분류)
# ──────────────────────────────────────────────────────────────────

def capture(
    *,
    classification: str,  # success | failure | warning | discovery
    context: str,
    content: str,
    confidence: float = 0.8,
    severity: Optional[str] = None,
    readonly: bool = False,
    scenario_type: str = "implementation",
    tags: Optional[list[str]] = None,
    caused_by: Optional[list[str]] = None,
    hypothesis: Optional[str] = None,
    pending_path: Path = PENDING_PATTERNS,
) -> Pattern:
    """4 분류 (success/failure/warning/discovery)로 pending_patterns에 패턴 append.

    LP ID는 자동 생성: LP-CS-PND-<timestamp> (merge 시 정식 LP-CS-NNN 부여).
    """
    if classification not in VALID_STATUS_MAP:
        raise ValueError(f"unknown classification: {classification} (valid: {list(VALID_STATUS_MAP)})")
    if scenario_type not in VALID_SCENARIO_TYPES:
        raise ValueError(f"unknown scenario_type: {scenario_type}")

    status = VALID_STATUS_MAP[classification]
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    pattern = Pattern(
        id=f"LP-CS-PND-{int(time.time() * 1000)}",
        context=context,
        status=status,
        content=content,
        learned_at=timestamp,
        confidence=confidence,
        severity=severity,
        readonly=readonly,
        scenario_type=scenario_type,
        tags=tags or [],
        caused_by=caused_by or [],
        hypothesis=hypothesis,
    )

    # pending 추가
    pending = _load_yaml(pending_path) or {}
    pending.setdefault("schema_version", "cs-brain/v1")
    pending.setdefault("pending_patterns", [])
    pending["pending_patterns"].append(pattern.to_dict())
    _dump_yaml(pending_path, pending)

    # capture.log append (ablation 측정용)
    CAPTURE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with CAPTURE_LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{timestamp}\t{classification}\t{pattern.id}\t{context[:60]}\n")

    return pattern


# ──────────────────────────────────────────────────────────────────
# T-803 + T-806: Search (BM25) + History Analyzer
# ──────────────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    pattern_id: str
    score: float
    context: str
    content_snippet: str
    status: str
    readonly: bool


def _tokenize(text: str) -> list[str]:
    """Simple Korean+English tokenizer — 정규식 기반.

    한국어 형태소 분석은 외부 의존성 — 본 MVP는 character n-gram + 단어 분할 어림.
    """
    text = text.lower()
    # 한국어는 2-char n-gram, 영어/숫자는 단어 단위
    tokens: list[str] = []
    # 영어/숫자 단어
    for w in re.findall(r"[a-z0-9_\-]+", text):
        if len(w) >= 2:
            tokens.append(w)
    # 한국어 — 2-char n-gram
    kor = re.findall(r"[가-힣]+", text)
    for word in kor:
        for i in range(len(word) - 1):
            tokens.append(word[i:i + 2])
    return tokens


class BM25:
    """Self-contained BM25 implementation (외부 의존성 0).

    sentence-transformers 통합은 P4에서 hybrid RRF로 보강.
    """
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs: list[list[str]] = []
        self.doc_ids: list[str] = []
        self.avg_doc_len: float = 0.0
        self.doc_freq: Counter = Counter()
        self.n_docs: int = 0

    def index(self, doc_id: str, text: str) -> None:
        tokens = _tokenize(text)
        self.docs.append(tokens)
        self.doc_ids.append(doc_id)
        for t in set(tokens):
            self.doc_freq[t] += 1
        self.n_docs = len(self.docs)
        total_len = sum(len(d) for d in self.docs)
        self.avg_doc_len = total_len / max(1, self.n_docs)

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        if self.n_docs == 0:
            return []
        q_tokens = _tokenize(query)
        scored: list[tuple[str, float]] = []
        for doc_id, doc in zip(self.doc_ids, self.docs):
            doc_len = len(doc)
            doc_counts = Counter(doc)
            score = 0.0
            for term in q_tokens:
                f = doc_counts.get(term, 0)
                if f == 0:
                    continue
                df = self.doc_freq.get(term, 1)
                idf = math.log((self.n_docs - df + 0.5) / (df + 0.5) + 1.0)
                tf_part = (f * (self.k1 + 1)) / (
                    f + self.k1 * (1 - self.b + self.b * doc_len / self.avg_doc_len)
                )
                score += idf * tf_part
            if score > 0:
                scored.append((doc_id, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


def search(query: str, *, top_k: int = 5, brain_path: Path = PROJECT_BRAIN) -> list[SearchResult]:
    """project_brain.yaml의 패턴을 BM25로 검색 + search-hits.log append.

    가산점:
      - readonly 패턴: ×1.2 (법무 승인 패턴 우선)
      - 같은 status (SUCCESS_PATTERN)만 우대는 적용 안 함 — 필요 시 future
    """
    brain = _load_yaml(brain_path) or {}
    patterns = brain.get("learned_patterns") or []

    bm25 = BM25()
    pattern_map: dict[str, dict] = {}
    for p in patterns:
        pid = p.get("id", "")
        if not pid:
            continue
        text = " ".join([
            p.get("context", ""),
            p.get("content", ""),
            " ".join(p.get("tags", []) or []),
            p.get("scenario_type", ""),
        ])
        bm25.index(pid, text)
        pattern_map[pid] = p

    raw_results = bm25.search(query, top_k=top_k * 2)  # readonly boost 후 자르기

    results: list[SearchResult] = []
    for pid, score in raw_results:
        p = pattern_map[pid]
        boosted_score = score * (1.2 if p.get("readonly") else 1.0)
        results.append(SearchResult(
            pattern_id=pid,
            score=round(boosted_score, 3),
            context=p.get("context", ""),
            content_snippet=p.get("content", "")[:120],
            status=p.get("status", ""),
            readonly=bool(p.get("readonly")),
        ))
    results.sort(key=lambda r: r.score, reverse=True)
    results = results[:top_k]

    # search-hits.log append (ablation 측정용)
    SEARCH_HITS_LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    hit_ids = ",".join(r.pattern_id for r in results) or "NO_HIT"
    with SEARCH_HITS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{timestamp}\t{query[:60]}\t{len(results)}\t{hit_ids}\n")

    return results


@dataclass
class HistoryInsight:
    total_queries: int
    zero_hit_count: int
    zero_hit_rate: float
    top_lp_ids: list[tuple[str, int]]  # (LP-ID, hit_count)
    similar_queries: list[tuple[str, float]]  # (query, similarity)
    hint_for_route: str

    def to_dict(self) -> dict:
        return asdict(self)


def analyze_history(query: str, *, days: int = 14, log_path: Path = SEARCH_HITS_LOG) -> HistoryInsight:
    """search-hits.log를 메타 분석.

    - top_lp_ids: 최근 days 동안 가장 자주 hit된 LP 5개
    - similar_queries: 현재 query와 토큰 overlap 상위 5개
    - zero_hit_rate: 검색 0건 응답 비율
    """
    if not log_path.exists():
        return HistoryInsight(0, 0, 0.0, [], [], "(no history)")

    cutoff_epoch = time.time() - days * 86400
    lp_counter: Counter = Counter()
    queries_seen: list[tuple[str, set[str]]] = []
    zero_hits = 0
    total = 0
    current_tokens = set(_tokenize(query))

    for line in log_path.read_text(encoding="utf-8").strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        ts_str, hist_query, hit_count_str, lp_ids = parts[0], parts[1], parts[2], parts[3]
        try:
            ts_epoch = time.mktime(time.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            continue
        if ts_epoch < cutoff_epoch:
            continue
        total += 1
        if hit_count_str == "0" or lp_ids == "NO_HIT":
            zero_hits += 1
        else:
            for lp_id in lp_ids.split(","):
                if lp_id.strip():
                    lp_counter[lp_id.strip()] += 1
        queries_seen.append((hist_query, set(_tokenize(hist_query))))

    # similar queries by token jaccard
    similar: list[tuple[str, float]] = []
    for q, q_tokens in queries_seen:
        if not q_tokens or q == query:
            continue
        intersection = len(current_tokens & q_tokens)
        union = len(current_tokens | q_tokens)
        sim = intersection / union if union else 0.0
        if sim > 0.0:
            similar.append((q, round(sim, 3)))
    similar.sort(key=lambda x: x[1], reverse=True)

    top_lps = lp_counter.most_common(5)
    zero_rate = zero_hits / max(1, total)

    if zero_rate > 0.4:
        hint = f"⚠️ Brain 미커버 영역 (zero_hit_rate={zero_rate:.2f}) — 외부 자료 탐색 필요"
    elif top_lps:
        hint = f"top 패턴: {top_lps[0][0]} ({top_lps[0][1]}회) — 동일 컨텍스트 반복"
    else:
        hint = "no significant pattern"

    return HistoryInsight(
        total_queries=total,
        zero_hit_count=zero_hits,
        zero_hit_rate=round(zero_rate, 3),
        top_lp_ids=top_lps,
        similar_queries=similar[:5],
        hint_for_route=hint,
    )


# ──────────────────────────────────────────────────────────────────
# T-804 + T-807: Merge (readonly 보호)
# ──────────────────────────────────────────────────────────────────

@dataclass
class MergeReport:
    merged_count: int
    skipped_readonly_count: int
    new_pattern_ids: list[str]
    next_lp_number: int


def merge(
    *,
    pending_path: Path = PENDING_PATTERNS,
    brain_path: Path = PROJECT_BRAIN,
    log_path: Path = MERGE_LOG,
    min_confidence: float = 0.0,
    auto_only: bool = False,
) -> MergeReport:
    """pending → project_brain. readonly 패턴은 자동 학습이 덮어쓰기 금지.

    Behavior:
      1. project_brain.yaml 의 기존 readonly 패턴은 절대 변경/삭제 안 함
      2. pending에서 readonly: true로 마킹된 신규 패턴은 그대로 등재 (사용자 명시)
      3. 중복 context 패턴이면 confidence 낮은 쪽 폐기
      4. LP-CS-PND-<ts> → LP-CS-NNN (다음 sequence number)
      5. 품질 게이트(min_confidence): confidence < min_confidence 인 패턴은
         승격하지 않고 pending에 잔류시킨다 (자동 merge 시 노이즈/저품질 패턴 차단용).
         기본 0.0 → 게이트 비활성(기존 동작 유지). 자동 트리거는 0.75 권장.
    """
    pending = _load_yaml(pending_path) or {}
    brain = _load_yaml(brain_path) or {}
    pending_list = list(pending.get("pending_patterns") or [])
    learned = list(brain.get("learned_patterns") or [])

    # 다음 LP-CS-NNN 번호 결정
    existing_nums = []
    for p in learned:
        m = re.match(r"LP-CS-(\d+)$", p.get("id", ""))
        if m:
            existing_nums.append(int(m.group(1)))
    next_num = max(existing_nums, default=0) + 1

    # readonly 패턴은 project_brain에서 분리 — merge 과정에서 절대 건드리지 않음
    readonly_existing = {p.get("id"): p for p in learned if p.get("readonly")}
    mutable_existing = [p for p in learned if not p.get("readonly")]

    merged_count = 0
    skipped_readonly = 0
    skipped_low_conf = 0
    skipped_needs_approval = 0
    retained_pending: list = []  # min_confidence 미달 / HITL 대기 → pending 잔류
    new_ids: list[str] = []

    for pending_p in pending_list:
        tags = pending_p.get("tags", []) or []
        # auto_only(자동 merge): needs-approval 태그(결과/법적 판단 패턴)는 사람 검토 전까지
        # 승격 보류. 과정 패턴(process/auto-learn)만 자동 승격 — "결과=HITL, 과정=자동" 분리.
        if auto_only and "needs-approval" in tags:
            retained_pending.append(pending_p)
            skipped_needs_approval += 1
            continue
        # readonly 패턴 보호: pending에서 동일 id로 들어와도 기존 readonly 덮어쓰기 금지
        if pending_p.get("id") in readonly_existing:
            skipped_readonly += 1
            continue
        # 품질 게이트: min_confidence 미달은 승격 안 하고 pending 잔류 (자동 merge 노이즈 차단)
        if float(pending_p.get("confidence", 0.8)) < min_confidence:
            retained_pending.append(pending_p)
            skipped_low_conf += 1
            continue
        # 중복 context 체크 (mutable만 대상)
        dup_idx = None
        for i, existing in enumerate(mutable_existing):
            if existing.get("context") == pending_p.get("context"):
                dup_idx = i
                break
        # 정식 LP-CS-NNN 부여 (pending id가 PND-* 형태면)
        if pending_p.get("id", "").startswith("LP-CS-PND-"):
            pending_p["id"] = f"LP-CS-{next_num:03d}"
            next_num += 1
        if dup_idx is not None:
            existing_conf = float(mutable_existing[dup_idx].get("confidence", 0.8))
            new_conf = float(pending_p.get("confidence", 0.8))
            if new_conf > existing_conf:
                mutable_existing[dup_idx] = pending_p
                merged_count += 1
                new_ids.append(pending_p["id"])
        else:
            mutable_existing.append(pending_p)
            merged_count += 1
            new_ids.append(pending_p["id"])

    # readonly 보존 + mutable 갱신
    brain["learned_patterns"] = list(readonly_existing.values()) + mutable_existing

    # metrics 갱신
    brain.setdefault("metrics", {})
    brain["metrics"]["readonly_pattern_count"] = sum(1 for p in brain["learned_patterns"] if p.get("readonly") is True)
    brain["metrics"]["total_pattern_count"] = len(brain["learned_patterns"])
    brain["metrics"]["evolution_cycles"] = int(brain["metrics"].get("evolution_cycles", 0)) + 1

    _dump_yaml(brain_path, brain)

    # pending clear (min_confidence 미달분은 잔류 — 품질 게이트)
    pending["pending_patterns"] = retained_pending
    _dump_yaml(pending_path, pending)

    # merge.log
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{timestamp}\tmerged={merged_count}\tskipped_readonly={skipped_readonly}\tskipped_low_conf={skipped_low_conf}\tskipped_needs_approval={skipped_needs_approval}\tauto_only={auto_only}\tmin_conf={min_confidence}\tnew_ids={','.join(new_ids) or '-'}\n")

    return MergeReport(
        merged_count=merged_count,
        skipped_readonly_count=skipped_readonly,
        new_pattern_ids=new_ids,
        next_lp_number=next_num,
    )


# ──────────────────────────────────────────────────────────────────
# T-805: Ablation Report
# ──────────────────────────────────────────────────────────────────

@dataclass
class FeatureHealth:
    feature_id: str
    fires: int
    expected_per_week: int
    weeks: float
    judgment: str  # HEALTHY | UNDERUSED | DEAD | INSUFFICIENT_DATA | UNMEASURED


def ablation_report(*, days: int = 7, config_path: Path = ABLATION_CONFIG) -> list[FeatureHealth]:
    """30일 (또는 N일) feature fire 빈도 → HEALTHY/UNDERUSED/DEAD 판정."""
    config = _load_yaml(config_path) or {}
    features = config.get("features") or []
    weeks = days / 7.0
    cutoff_epoch = time.time() - days * 86400

    reports: list[FeatureHealth] = []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        fid = feat.get("id", "")
        source = feat.get("measurement_source") or {}
        log_file = PROJECT_ROOT / source.get("file", "")
        signal = source.get("signal") or "."
        expected_per_week = int(feat.get("expected_per_week", 0))

        if not log_file.exists():
            reports.append(FeatureHealth(fid, 0, expected_per_week, weeks, "UNMEASURED"))
            continue

        fires = 0
        try:
            for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
                if not line:
                    continue
                # 시간 필터링 — 라인 첫 컬럼이 ISO 시간이라고 가정
                parts = line.split("\t")
                if not parts:
                    continue
                ts_str = parts[0]
                try:
                    ts_epoch = time.mktime(time.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ"))
                except ValueError:
                    # JSONL일 수도 있음 (llm_cost_ledger.jsonl)
                    try:
                        rec = json.loads(line)
                        ts_str = rec.get("timestamp", "")
                        ts_epoch = time.mktime(time.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ"))
                    except (json.JSONDecodeError, ValueError):
                        continue
                if ts_epoch < cutoff_epoch:
                    continue
                if signal == "." or re.search(signal, line):
                    fires += 1
        except Exception:
            reports.append(FeatureHealth(fid, 0, expected_per_week, weeks, "UNMEASURED"))
            continue

        # 판정
        expected_total = expected_per_week * weeks
        if expected_total < 1:
            judgment = "INSUFFICIENT_DATA"
        elif fires == 0 and expected_total >= 1:
            judgment = "DEAD"
        elif fires < expected_total * 0.2:
            judgment = "UNDERUSED"
        elif fires >= expected_total * 0.8:
            judgment = "HEALTHY"
        else:
            judgment = "UNDERUSED"

        reports.append(FeatureHealth(fid, fires, expected_per_week, weeks, judgment))

    return reports


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Compliance Sentinel Brain — Self-Evolving Learning")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # capture
    p_cap = sub.add_parser("capture", help="새 학습 패턴을 pending에 기록")
    p_cap.add_argument("classification", choices=list(VALID_STATUS_MAP))
    p_cap.add_argument("context")
    p_cap.add_argument("content")
    p_cap.add_argument("--severity", choices=["critical", "warning", "info"])
    p_cap.add_argument("--readonly", action="store_true")
    p_cap.add_argument("--scenario", default="implementation")
    p_cap.add_argument("--tags", default="")
    p_cap.add_argument("--confidence", type=float, default=0.8)
    p_cap.add_argument("--hypothesis")
    p_cap.add_argument("--json", action="store_true")

    # search
    p_search = sub.add_parser("search", help="project_brain에서 BM25 검색 + 메타 인사이트")
    p_search.add_argument("query")
    p_search.add_argument("--top", type=int, default=5)
    p_search.add_argument("--analyze", action="store_true", help="메타 인사이트 함께 출력")
    p_search.add_argument("--days", type=int, default=14)
    p_search.add_argument("--json", action="store_true")

    # merge
    p_merge = sub.add_parser("merge", help="pending → project_brain (readonly 보호)")
    p_merge.add_argument("--json", action="store_true")

    # ablation
    p_abl = sub.add_parser("ablation", help="feature fire 빈도 → HEALTHY/UNDERUSED/DEAD")
    p_abl.add_argument("--days", type=int, default=7)
    p_abl.add_argument("--json", action="store_true")

    # status
    p_status = sub.add_parser("status", help="Brain 상태 한눈에")

    args = parser.parse_args(argv)

    if args.cmd == "capture":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        pattern = capture(
            classification=args.classification,
            context=args.context,
            content=args.content,
            severity=args.severity,
            readonly=args.readonly,
            scenario_type=args.scenario,
            tags=tags,
            confidence=args.confidence,
            hypothesis=args.hypothesis,
        )
        if args.json:
            print(json.dumps(pattern.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"✅ captured {pattern.id} ({args.classification})")
        return 0

    if args.cmd == "search":
        results = search(args.query, top_k=args.top)
        if args.json:
            out: dict = {"results": [asdict(r) for r in results]}
            if args.analyze:
                out["history_insight"] = analyze_history(args.query, days=args.days).to_dict()
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print(f"검색 결과 ({len(results)}건):")
            for r in results:
                ro = " [readonly]" if r.readonly else ""
                print(f"  {r.pattern_id} (score={r.score}){ro}: {r.context[:60]}")
            if args.analyze:
                ins = analyze_history(args.query, days=args.days)
                print()
                print(f"메타 인사이트 (최근 {args.days}일):")
                print(f"  total_queries: {ins.total_queries}, zero_hit_rate: {ins.zero_hit_rate}")
                print(f"  top LPs: {ins.top_lp_ids}")
                print(f"  hint: {ins.hint_for_route}")
        return 0

    if args.cmd == "merge":
        report = merge()
        if args.json:
            print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        else:
            print(f"✅ merged {report.merged_count} pattern(s)")
            print(f"   skipped readonly: {report.skipped_readonly_count}")
            print(f"   new IDs: {', '.join(report.new_pattern_ids) or '(none)'}")
            print(f"   next LP number: {report.next_lp_number}")
        return 0

    if args.cmd == "ablation":
        reports = ablation_report(days=args.days)
        if args.json:
            print(json.dumps([asdict(r) for r in reports], ensure_ascii=False, indent=2))
        else:
            print(f"Ablation report (지난 {args.days}일):")
            for r in reports:
                judgment_color = {
                    "HEALTHY": "✅",
                    "UNDERUSED": "⚠️",
                    "DEAD": "💀",
                    "INSUFFICIENT_DATA": "❓",
                    "UNMEASURED": "—",
                }.get(r.judgment, "  ")
                print(f"  {judgment_color} {r.feature_id:35s} fires={r.fires}  expected={int(r.expected_per_week * r.weeks)}  ({r.judgment})")
        return 0

    if args.cmd == "status":
        brain = _load_yaml(PROJECT_BRAIN) or {}
        pending = _load_yaml(PENDING_PATTERNS) or {}
        learned = brain.get("learned_patterns") or []
        readonly_count = sum(1 for p in learned if p.get("readonly"))
        print(f"project_brain.yaml: {len(learned)} pattern(s), {readonly_count} readonly")
        print(f"pending_patterns.yaml: {len(pending.get('pending_patterns') or [])} pattern(s)")
        if CAPTURE_LOG.exists():
            captures = CAPTURE_LOG.read_text().count("\n")
            print(f"capture.log: {captures} lines")
        if MERGE_LOG.exists():
            merges = MERGE_LOG.read_text().count("\n")
            print(f"merge.log: {merges} lines")
        if SEARCH_HITS_LOG.exists():
            hits = SEARCH_HITS_LOG.read_text().count("\n")
            print(f"search-hits.log: {hits} lines")
        return 0

    parser.error(f"unknown command: {args.cmd}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
