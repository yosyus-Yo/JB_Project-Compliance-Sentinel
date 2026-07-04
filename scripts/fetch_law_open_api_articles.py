#!/usr/bin/env python3
"""Fetch selected official law.go.kr articles into data/laws.json.

Secrets are read from LAW_OPEN_API_KEY or an optional --key-file and are never
printed. The script updates only existing entries by (law_name, article_no) so
curated aliases used by the local KB remain stable.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compliance_sentinel.law_open_api import LawOpenApiClient  # noqa: E402
from compliance_sentinel.knowledge_base import normalize, normalize_article_no  # noqa: E402

DEFAULT_TARGETS: list[tuple[str, str]] = [
    ("금융소비자보호법", "19"),
    ("금융소비자보호법", "21"),
    ("금융소비자보호법", "22"),
    ("개인정보보호법", "15"),
    ("개인정보보호법", "17"),
    ("개인정보보호법", "18"),
    ("개인정보보호법", "22"),
    ("신용정보의 이용 및 보호에 관한 법률", "32"),
    ("신용정보의 이용 및 보호에 관한 법률", "33"),
    ("전자금융거래법", "21"),
    ("자본시장과 금융투자업에 관한 법률", "47"),
    ("자본시장과 금융투자업에 관한 법률", "49"),
    ("자본시장과 금융투자업에 관한 법률", "57"),
    ("표시·광고의 공정화에 관한 법률", "3"),
    ("표시·광고의 공정화에 관한 법률", "5"),
]

KEY_PATTERNS = [
    r"LAW_OPEN_API_KEY\s*[:=]\s*([^\s`]+)",
    r"법제처[^\n:：]*[:：]\s*([^\s`]+)",
    r"OC\s*[:=]\s*([^\s`]+)",
    r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+)",
    r"\b([A-Za-z0-9._%+\-]{8,})\b",
]


def load_key(key_file: Path | None) -> str:
    env_key = os.environ.get("LAW_OPEN_API_KEY")
    if env_key:
        return env_key.strip()
    if not key_file:
        return ""
    text = key_file.read_text(encoding="utf-8", errors="ignore")
    for pattern in KEY_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip().strip('"\'')
    return ""


# 법령형 law_name (가이드라인/내부 기준은 제외). 공식 원문 확대 대상 식별용.
_STATUTE_RE = re.compile(r"(법|법률|규정)$")


def default_targets_from_kb(rows: list[dict]) -> list[tuple[str, str]]:
    """laws.json에서 공식화 대상을 자동 추출한다 — 법령형 law_name이면서 아직
    law.go.kr 공식 출처가 아닌(미공식화) 조문. 하드코딩 목록을 KB 전체로 확대해
    키 확보 시 1회 실행으로 전체 공식 원문을 끌어올 수 있게 한다."""
    seen: set[tuple[str, str]] = set()
    targets: list[tuple[str, str]] = []
    for row in rows:
        law = str(row.get("law_name", "")).strip()
        art = str(row.get("article_no", "")).strip()
        if not law or not art or not _STATUTE_RE.search(law):
            continue
        if "law.go.kr" in str(row.get("source_url", "")):
            continue  # 이미 공식화됨 → 재fetch 불필요
        key = (law, art)
        if key not in seen:
            seen.add(key)
            targets.append(key)
    return targets


def load_targets(path: Path | None, rows: list[dict] | None = None) -> list[tuple[str, str]]:
    """타겟 결정: --targets-json 우선, 없으면 하드코딩 핵심 + KB 자동 추출 병합."""
    if path is not None:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [(str(row["law_name"]), str(row["article_no"])) for row in data]
    targets = list(DEFAULT_TARGETS)
    if rows is not None:
        seen = set(targets)
        for key in default_targets_from_kb(rows):
            if key not in seen:
                seen.add(key)
                targets.append(key)
    return targets


def find_matching_rows(rows: list[dict], law_name: str, article_no: str) -> list[dict]:
    n_law = normalize(law_name)
    n_article = normalize_article_no(article_no)
    matches: list[dict] = []
    for row in rows:
        if normalize(str(row.get("law_name", ""))) == n_law and normalize_article_no(str(row.get("article_no", ""))) == n_article:
            matches.append(row)
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch official law.go.kr articles into data/laws.json")
    parser.add_argument("--key-file", type=Path, default=None, help="Optional file containing LAW_OPEN_API_KEY/OC. Secret is not printed.")
    parser.add_argument("--laws", type=Path, default=ROOT / "data" / "laws.json")
    parser.add_argument("--targets-json", type=Path, default=None, help="Optional JSON list of {law_name, article_no}")
    parser.add_argument("--apply", action="store_true", help="Write data/laws.json. Default is dry-run.")
    parser.add_argument("--sleep", type=float, default=0.25, help="Seconds between API calls")
    parser.add_argument("--add-new", action="store_true", help="laws.json에 없는 (law_name, article_no)는 신규 article로 추가 (기본: 기존 항목만 갱신)")
    args = parser.parse_args()

    api_key = load_key(args.key_file)
    if not api_key:
        print(json.dumps({"ok": False, "error": "missing LAW_OPEN_API_KEY"}, ensure_ascii=False))
        return 2

    rows = json.loads(args.laws.read_text(encoding="utf-8"))
    client = LawOpenApiClient(api_key=api_key)
    summary = {"requested": 0, "fetched": 0, "updated_rows": 0, "added_rows": 0, "missing_local_rows": [], "fetch_failed": []}

    for law_name, article_no in load_targets(args.targets_json, rows):
        summary["requested"] += 1
        fetched = client.fetch_article(law_name, article_no)
        if not fetched:
            summary["fetch_failed"].append({"law_name": law_name, "article_no": article_no})
            time.sleep(args.sleep)
            continue
        summary["fetched"] += 1
        matches = find_matching_rows(rows, law_name, article_no)
        if not matches:
            if args.add_new:
                rows.append({
                    "law_name": law_name,
                    "article_no": article_no,
                    "title": f"{law_name} 제{article_no}조",
                    "text": fetched.text,
                    "effective_date": fetched.effective_date or "",
                    "source_url": fetched.source_url,
                    "keywords": ["law_open_api", "official_text"],
                })
                summary["added_rows"] += 1
            else:
                summary["missing_local_rows"].append({"law_name": law_name, "article_no": article_no})
            time.sleep(args.sleep)
            continue
        for row in matches:
            # Keep local curated law_name alias stable; update official body/provenance.
            row["title"] = row.get("title") or f"{row['law_name']} 제{article_no}조"
            if "placeholder" in str(row.get("text", "")).lower() or len(str(row.get("text", ""))) < len(fetched.text):
                row["text"] = fetched.text
            else:
                row["text"] = fetched.text
            row["effective_date"] = fetched.effective_date or row.get("effective_date", "")
            row["source_url"] = fetched.source_url
            keywords = set(row.get("keywords") or [])
            keywords.update(["law_open_api", "official_text"])
            row["keywords"] = sorted(keywords)
            summary["updated_rows"] += 1
        time.sleep(args.sleep)

    if args.apply:
        args.laws.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "applied": args.apply, **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
