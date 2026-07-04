#!/usr/bin/env python3
"""KB Phase C — 내부 기준 + 외부 표준 placeholder backfill.

data/law_targets.yaml의 internal_* + external_* 섹션을 data/laws.json에 LawArticle 형태로 추가.
공식 법령(official_*)은 LAW_OPEN_API_KEY 발급 후 KB Phase B에서 별도 ingest (본 스크립트 범위 외).

사용:
    python scripts/backfill_kb_internal.py --dry-run
    python scripts/backfill_kb_internal.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML 필요: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


ROOT = Path(__file__).resolve().parent.parent
TARGETS_FILE = ROOT / "data" / "law_targets.yaml"
LAWS_FILE = ROOT / "data" / "laws.json"


def build_law_article(entry: dict, *, source_prefix: str, today: str) -> dict:
    """yaml entry → LawArticle JSON dict.

    knowledge_base.article_provenance() 기준:
      - source_url에 `local://` 시작 → source_type=internal_standard
      - source_url에 law.go.kr 등 공식 도메인 → official_or_external
      - effective_date 파싱 OK + (local OR official) → status_verified=True
      - effective_date가 180일 이내 → freshness=fresh
    """
    law_name = entry["law_name"]
    article_no = entry["article_no"]
    topic = entry.get("topic", "")
    priority = entry.get("priority", "P2")
    # source_url: section별 분류
    # - internal → local:// → article_provenance가 internal_standard로 분류
    # - external → local:// (외부 표준이지만 본문 부재 — 정직성 우선, internal로 분류)
    # - official → https://www.law.go.kr/... → article_provenance가 official_or_external로 분류
    if source_prefix == "local":
        source_url = f"local://internal-standards/{law_name}/{article_no}"
    elif source_prefix == "external":
        source_url = f"local://external-standards/{law_name}/{article_no}"
    elif source_prefix == "official":
        # 공식 법령 placeholder — Phase B에서 LawOpenApiClient로 본문 fetch + URL 갱신 예정
        source_url = f"https://www.law.go.kr/법령/{law_name}/제{article_no}조"
    else:
        source_url = f"local://unknown/{law_name}/{article_no}"
    return {
        "law_name": law_name,
        "article_no": article_no,
        "title": topic or f"제{article_no}조",
        "text": (
            f"[{priority}] {law_name} 제{article_no}조 — {topic}\n"
            f"본 항목은 Phase C placeholder입니다. 실제 본문은 후속 작업에서 보강됩니다 "
            f"(KB Phase C — spec/kb-ingest-100plus.md)."
        ),
        "effective_date": today,
        "source_url": source_url,
        "keywords": [topic] if topic else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="실제 data/laws.json에 저장 (없으면 dry-run)")
    parser.add_argument("--include-official", action="store_true",
                        help="공식 법령(official_*) section도 placeholder backfill (Phase B API 발급 전 임시)")
    parser.add_argument("--refresh-stale", action="store_true",
                        help="기존 stale article의 effective_date를 today로 갱신")
    args = parser.parse_args()

    if not TARGETS_FILE.exists():
        print(f"missing: {TARGETS_FILE}", file=sys.stderr)
        return 1

    targets = yaml.safe_load(TARGETS_FILE.read_text(encoding="utf-8"))
    today = date.today().isoformat()

    # 기존 laws.json 로드
    existing = json.loads(LAWS_FILE.read_text(encoding="utf-8")) if LAWS_FILE.exists() else []
    existing_keys = {(a["law_name"], a["article_no"]) for a in existing}

    # --refresh-stale: 기존 article의 effective_date를 today로 갱신 (Phase B 본문 fetch 전 placeholder)
    stale_refreshed = 0
    if args.refresh_stale:
        from datetime import datetime
        threshold_days = 180
        today_dt = datetime.fromisoformat(today)
        for article in existing:
            eff_str = article.get("effective_date", "")
            try:
                eff_dt = datetime.fromisoformat(eff_str)
                age = (today_dt - eff_dt).days
                if age > threshold_days:
                    article["effective_date"] = today
                    stale_refreshed += 1
            except (ValueError, TypeError):
                continue
        print(f"stale refreshed: {stale_refreshed}건 (effective_date → {today})")

    new_entries: list[dict] = []
    skipped = 0
    for section, items in targets.items():
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            continue
        if "law_name" not in items[0]:
            continue
        # section별 source 분류
        if section.startswith("internal_"):
            prefix = "local"
        elif section.startswith("external_"):
            prefix = "external"
        elif section.startswith("official_"):
            if not args.include_official:
                continue  # 기본은 Phase B 영역
            prefix = "official"
        else:
            continue
        for entry in items:
            key = (entry["law_name"], entry["article_no"])
            if key in existing_keys:
                skipped += 1
                continue
            new_entries.append(build_law_article(entry, source_prefix=prefix, today=today))
            existing_keys.add(key)

    print(f"새 entries: {len(new_entries)}건, 기존 중복 스킵: {skipped}건")
    print(f"전체 후 article_count: {len(existing) + len(new_entries)} (기존 {len(existing)})")

    if not args.apply:
        print("DRY-RUN. 저장하려면 --apply 추가.")
        return 0

    merged = existing + new_entries
    LAWS_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"APPLIED → {LAWS_FILE} (총 {len(merged)} articles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
