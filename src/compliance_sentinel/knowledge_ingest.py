"""Document ingestion pipeline for Skill + RAG + Memory storage.

Given a review document, this module classifies redacted chunks into:
- Skill: reusable reviewer procedure/checklist knowledge.
- RAG: source-grounded rules, law/internal standards, product disclosures.
- Memory: experience patterns and repeated decisions, staged into Brain pending.

The default CLI is dry-run. Use `--apply` to write generated artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

from . import cs_brain
from .pii import redact_pii
from .skill_injection import DEFAULT_MARKETING_SKILL_PATH

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAG_PATH = PROJECT_ROOT / "data" / "knowledge_rag" / "financial_marketing_corpus.jsonl"
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "data" / "knowledge_rag" / "ingest_manifest.jsonl"

Target = Literal["skill", "rag", "memory"]
_JSONL_CACHE: dict[str, tuple[float, int, list[dict]]] = {}

SKILL_START = "<!-- AUTO-GENERATED-EXPERIENCE-START -->"
SKILL_END = "<!-- AUTO-GENERATED-EXPERIENCE-END -->"

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\s*[:=]\s*[^\s]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
]

PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore (all )?(previous|above) instructions"),
    re.compile(r"(?i)disregard (all )?(previous|above)"),
    re.compile(r"(?i)(system|developer) prompt"),
    re.compile(r"(?i)you are now"),
    re.compile(r"(?i)switch to developer mode"),
]

HIDDEN_UNICODE_PATTERN = re.compile(r"[\u200b\u200c\u200d\ufeff]")
SOURCE_ALLOWLIST_DOMAINS = {
    "law.go.kr",
    "open.law.go.kr",
    "fsc.go.kr",
    "fss.or.kr",
    "pipc.go.kr",
    "kofia.or.kr",
    "jbfg.com",
}
FRESHNESS_REVIEW_YEARS = 2

TARGET_KEYWORDS: dict[Target, list[str]] = {
    "skill": [
        "절차", "순서", "체크리스트", "판단 기준", "판정 기준", "원칙", "해야 한다", "하지 않는다",
        "수정안", "대체 문구", "먼저", "다음", "검토 순서", "심의관", "reviewer", "checklist",
    ],
    "rag": [
        "법", "규정", "기준", "심의 기준", "조항", "고시", "가이드라인", "내부 기준", "상품설명서", "약관", "원문",
        "근거", "출처", "시행", "필수 고지", "제", "article", "policy", "standard",
    ],
    "memory": [
        "사례", "반복", "과거", "경험", "승인", "반려", "위반", "재발", "항상", "무조건",
        "critical", "고위험", "false negative", "놓치기 쉬운", "무심사", "한도 무제한", "LP-",
    ],
}


@dataclass(frozen=True)
class IngestChunk:
    id: str
    source: str
    text: str
    targets: list[Target]
    blocked_reasons: list[str] = field(default_factory=list)
    score_by_target: dict[str, int] = field(default_factory=dict)
    trust_notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IngestReport:
    source: str
    applied: bool
    approved_memory: bool
    total_chunks: int
    blocked_chunks: int
    target_counts: dict[str, int]
    skill_path: str
    rag_path: str
    pending_path: str
    trust_summary: dict[str, int] = field(default_factory=dict)
    written_skill_items: int = 0
    written_rag_items: int = 0
    written_memory_items: int = 0
    chunks: list[dict] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}"


def _contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def _contains_prompt_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in PROMPT_INJECTION_PATTERNS)


def _source_trust_notes(source: str) -> tuple[list[str], list[str]]:
    """Return (blocking reasons, non-blocking trust notes) for an ingest source."""
    parsed = urlparse(source)
    if not parsed.scheme or not parsed.netloc:
        return [], ["local_or_manual_source"]
    domain = parsed.netloc.lower().split(":", 1)[0]
    if domain in SOURCE_ALLOWLIST_DOMAINS or any(domain.endswith(f".{allowed}") for allowed in SOURCE_ALLOWLIST_DOMAINS):
        return [], ["source_allowlisted"]
    return ["source_not_allowlisted"], [f"untrusted_domain:{domain}"]


def _freshness_notes(text: str) -> list[str]:
    years = [int(year) for year in re.findall(r"(?<!\d)(20\d{2})(?!\d)", text)]
    if not years:
        return ["freshness_unknown"]
    current_year = datetime.now(timezone.utc).year
    newest = max(years)
    if current_year - newest > FRESHNESS_REVIEW_YEARS:
        return [f"freshness_review_required:newest_year={newest}"]
    return [f"freshness_recent:newest_year={newest}"]


def _split_document(text: str, *, max_chars: int = 1100) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\r\n\s*\r\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs or [text.strip()]:
        if len(paragraph) > max_chars:
            for i in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[i:i + max_chars].strip())
            continue
        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current.strip())
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current.strip():
        chunks.append(current.strip())
    return chunks


def classify_text(text: str) -> tuple[list[Target], dict[str, int]]:
    lowered = text.lower()
    scores: dict[str, int] = {}
    for target, keywords in TARGET_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword.lower() in lowered:
                score += 1
        scores[target] = score
    targets = [target for target in ("skill", "rag", "memory") if scores[target] > 0]
    if not targets:
        targets = ["rag"]
    # 경험 지식은 대부분 skill+memory 또는 rag+memory로도 유용하다.
    if "memory" in targets and "skill" not in targets and any(k in lowered for k in ["해야", "기준", "항상", "무조건"]):
        targets.append("skill")
    return targets, scores


def plan_document_ingest(text: str, *, source: str) -> list[IngestChunk]:
    chunks: list[IngestChunk] = []
    source_blocks, source_notes = _source_trust_notes(source)
    for raw_chunk in _split_document(text):
        redacted, _ = redact_pii(raw_chunk)
        blocked = list(source_blocks)
        trust_notes = list(source_notes) + _freshness_notes(raw_chunk)
        if _contains_secret(raw_chunk):
            blocked.append("secret_like_token_detected")
        if _contains_prompt_injection(raw_chunk):
            blocked.append("prompt_injection_pattern_detected")
        if HIDDEN_UNICODE_PATTERN.search(raw_chunk):
            trust_notes.append("hidden_unicode_detected")
        targets, scores = classify_text(redacted)
        chunk_id = _stable_id("DOC", f"{source}\n{redacted}")
        chunks.append(IngestChunk(
            id=chunk_id,
            source=source,
            text=redacted,
            targets=targets,
            blocked_reasons=blocked,
            score_by_target=scores,
            trust_notes=trust_notes,
        ))
    return chunks


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    stat = path.stat()
    cache_key = str(path.resolve())
    cached = _JSONL_CACHE.get(cache_key)
    if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
        return [dict(row) for row in cached[2]]
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    _JSONL_CACHE[cache_key] = (stat.st_mtime, stat.st_size, [dict(row) for row in rows])
    return rows


def _append_jsonl_unique(path: Path, rows: list[dict]) -> int:
    existing_ids = {row.get("id") for row in _load_jsonl(path)}
    new_rows = [row for row in rows if row.get("id") not in existing_ids]
    if not new_rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in new_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    _JSONL_CACHE.pop(str(path.resolve()), None)
    return len(new_rows)


def _summarize_for_skill(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line[:260]


def _default_skill_doc() -> str:
    return f"""---
name: financial-marketing-content-reviewer-experience
description: 금융 마케팅 콘텐츠 AI 심의관 경험 지식. 상품/채널/다국어 심의 절차, 금지 표현 해석, 수정안 작성 원칙을 내부 에이전트에 주입합니다.
version: generated
---

# Financial Marketing Content Reviewer Experience Skill

## Overview

이 스킬은 문서 ingest 파이프라인이 승인 가능한 경험 지식을 요약해 생성합니다. 내부 에이전트는 법률 자문이 아니라 금융 마케팅 콘텐츠 준법 심의 보조 관점으로 사용합니다.

## Practice Profile (Cold-start Surface)

운영 전 다음 항목을 JB 내부 기준으로 채웁니다. 플러그인 업데이트나 문서 ingest가 이 영역을 덮어쓰지 않도록 수동 관리합니다.

| Field | Value |
|---|---|
| 상품 범위 | 예금/대출/카드/투자/보험 및 신규 상품군 |
| 채널 범위 | 배너/앱푸시/SNS/이메일/랜딩/고지문 |
| 리스크 성향 | 보수적 기본값: 보장·무위험·무조건 승인 표현은 차단 또는 HITL |
| 필수 에스컬레이션 | CRITICAL, 외국어 고위험, 신규 규제·상품, 근거 미검증 |
| 공식 근거 | 법령정보센터, 금융위, 금감원, 개인정보위, JB 내부 심의 기준 |
| 승인 산출물 | 수정안, 근거, reviewer note, audit_log_id, Slack/Notion payload |

## Operating Rules

- 먼저 상품유형, 채널, 언어, 대상 고객을 분류합니다.
- 주장 유형을 subjective/factual/comparative/implied/absolute로 분해하고, non-puffery claim은 실증 근거를 요구합니다.
- 금지/주의 표현과 필수 고지 누락을 분리해 판단합니다.
- critical 또는 반복 위반 패턴은 human review를 필수화합니다.
- 법령/내부 기준 원문은 RAG 근거로 확인하고, 경험 지식만으로 최종 법률판단을 하지 않습니다.
- PII 원문, 비밀, 토큰은 skill/RAG/memory에 저장하지 않습니다.
- 외부 문서·스킬은 출처 allowlist, freshness, prompt-injection scan 통과 전 운영 판단에 반영하지 않습니다.

## Generated Experience Notes

{SKILL_START}
{SKILL_END}
"""


def _upsert_skill_items(skill_path: Path, chunks: list[IngestChunk]) -> int:
    skill_chunks = [c for c in chunks if "skill" in c.targets and not c.blocked_reasons]
    if not skill_chunks:
        return 0
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    text = skill_path.read_text(encoding="utf-8") if skill_path.exists() else _default_skill_doc()
    if SKILL_START not in text or SKILL_END not in text:
        text = text.rstrip() + f"\n\n## Generated Experience Notes\n\n{SKILL_START}\n{SKILL_END}\n"
    existing_region = text.split(SKILL_START, 1)[1].split(SKILL_END, 1)[0]
    existing_ids = set(re.findall(r"<!-- id: ([A-Za-z0-9-]+) -->", existing_region))
    new_items: list[str] = []
    for chunk in skill_chunks:
        if chunk.id in existing_ids:
            continue
        new_items.append(
            f"- <!-- id: {chunk.id} --> [{chunk.source}] {_summarize_for_skill(chunk.text)}"
        )
    if not new_items:
        return 0
    new_region = existing_region.rstrip() + ("\n" if existing_region.strip() else "") + "\n".join(new_items) + "\n"
    updated = text.split(SKILL_START, 1)[0] + SKILL_START + "\n" + new_region + SKILL_END + text.split(SKILL_END, 1)[1]
    skill_path.write_text(updated, encoding="utf-8")
    return len(new_items)


def _write_rag_items(rag_path: Path, chunks: list[IngestChunk]) -> int:
    rows = []
    for chunk in chunks:
        if "rag" not in chunk.targets or chunk.blocked_reasons:
            continue
        rows.append({
            "id": _stable_id("RAG", chunk.id),
            "source": chunk.source,
            "text": chunk.text,
            "targets": chunk.targets,
            "created_at": _now(),
            "metadata": {"kind": "financial_marketing_review_knowledge"},
        })
    return _append_jsonl_unique(rag_path, rows)


def _write_memory_items(chunks: list[IngestChunk], *, pending_path: Path, approved_memory: bool) -> int:
    pending = cs_brain._load_yaml(pending_path) or {}
    existing_content = "\n".join(str(pattern.get("content", "")) for pattern in pending.get("pending_patterns") or [])
    count = 0
    for chunk in chunks:
        if "memory" not in chunk.targets or chunk.blocked_reasons:
            continue
        if f"chunk_id={chunk.id}" in existing_content:
            continue
        cs_brain.capture(
            classification="discovery" if approved_memory else "warning",
            context=f"document-ingest experience: {chunk.source}",
            content=f"approval={'approved' if approved_memory else 'pending'}; chunk_id={chunk.id}; {chunk.text[:420]}",
            confidence=0.86 if approved_memory else 0.72,
            severity="info" if approved_memory else "warning",
            readonly=approved_memory,
            scenario_type="integration",
            tags=["document-ingest", "financial-marketing", "experience", "approved" if approved_memory else "needs-approval"],
            pending_path=pending_path,
        )
        existing_content += f"\nchunk_id={chunk.id}"
        count += 1
    return count


def search_document_rag(query: str, *, rag_path: Path = DEFAULT_RAG_PATH, limit: int = 5) -> list[dict]:
    """Small lexical search over ingested RAG chunks.

    This is an offline-first companion to Qdrant. The document corpus can later be
    embedded into Qdrant, but this keeps recall testable without external infra.
    """

    rows = _load_jsonl(rag_path)
    if not rows:
        return []
    q_tokens = {t for t in re.split(r"\W+", query.lower()) if len(t) >= 2}
    scored: list[tuple[int, dict]] = []
    for row in rows:
        text = str(row.get("text", ""))
        hay = text.lower()
        score = sum(1 for token in q_tokens if token in hay)
        # Korean fallback: direct phrase fragments matter for compliance copy.
        for fragment in ["무심사", "한도", "원금", "필수 고지", "수정안", "고위험"]:
            if fragment in query and fragment in text:
                score += 2
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row | {"score": score} for score, row in scored[:limit]]


def ingest_document(
    text: str,
    *,
    source: str,
    apply: bool = False,
    approved_memory: bool = False,
    skill_path: Path = DEFAULT_MARKETING_SKILL_PATH,
    rag_path: Path = DEFAULT_RAG_PATH,
    pending_path: Path = cs_brain.PENDING_PATTERNS,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> IngestReport:
    chunks = plan_document_ingest(text, source=source)
    target_counts = {"skill": 0, "rag": 0, "memory": 0}
    for chunk in chunks:
        if chunk.blocked_reasons:
            continue
        for target in chunk.targets:
            target_counts[target] += 1

    trust_summary: dict[str, int] = {}
    for chunk in chunks:
        for key in chunk.blocked_reasons + chunk.trust_notes:
            trust_summary[key] = trust_summary.get(key, 0) + 1

    written_skill = written_rag = written_memory = 0
    if apply:
        written_skill = _upsert_skill_items(skill_path, chunks)
        written_rag = _write_rag_items(rag_path, chunks)
        written_memory = _write_memory_items(chunks, pending_path=pending_path, approved_memory=approved_memory)
        _append_jsonl_unique(manifest_path, [{
            "id": _stable_id("INGEST", source + str([c.id for c in chunks])),
            "source": source,
            "created_at": _now(),
            "approved_memory": approved_memory,
            "target_counts": target_counts,
            "blocked_chunks": sum(1 for c in chunks if c.blocked_reasons),
            "trust_summary": trust_summary,
        }])

    return IngestReport(
        source=source,
        applied=apply,
        approved_memory=approved_memory,
        total_chunks=len(chunks),
        blocked_chunks=sum(1 for c in chunks if c.blocked_reasons),
        target_counts=target_counts,
        skill_path=str(skill_path),
        rag_path=str(rag_path),
        pending_path=str(pending_path),
        trust_summary=trust_summary,
        written_skill_items=written_skill,
        written_rag_items=written_rag,
        written_memory_items=written_memory,
        chunks=[asdict(chunk) for chunk in chunks],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify a document into Skill + RAG + Memory stores")
    parser.add_argument("path", help="문서 경로 (.txt/.md 권장)")
    parser.add_argument("--source", help="source label. 기본값은 파일명")
    parser.add_argument("--apply", action="store_true", help="실제 저장. 없으면 dry-run")
    parser.add_argument("--approve-memory", action="store_true", help="memory 후보를 승인/readonly 후보로 캡처")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    path = Path(args.path)
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 1
    text = path.read_text(encoding="utf-8")
    report = ingest_document(
        text,
        source=args.source or path.name,
        apply=args.apply,
        approved_memory=args.approve_memory,
    )
    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        mode = "APPLIED" if report.applied else "DRY-RUN"
        print(f"[{mode}] {report.source}")
        print(f"chunks={report.total_chunks}, blocked={report.blocked_chunks}, targets={report.target_counts}")
        print(f"written skill={report.written_skill_items}, rag={report.written_rag_items}, memory={report.written_memory_items}")
        if not report.applied:
            print("저장하려면 --apply를 추가하세요. memory 승인 후보는 --approve-memory를 함께 사용하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
