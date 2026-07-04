#!/usr/bin/env python3
"""RAG/KB production-readiness report.

This script turns LawKnowledgeBase.coverage_report() into a CI-friendly artifact.
It is deterministic/offline by default and does not mutate the KB.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compliance_sentinel.knowledge_base import LawKnowledgeBase, article_provenance  # noqa: E402


def build_report(*, top: int = 10) -> dict:
    kb = LawKnowledgeBase.from_json()
    coverage = kb.coverage_report()
    provenance = [article_provenance(article) for article in kb.articles]
    unverified = [row for row in provenance if not row.get("status_verified")]
    stale = [row for row in provenance if row.get("freshness_status") == "stale_review_required"]
    placeholders = [
        {
            "law_name": article.law_name,
            "article_no": article.article_no,
            "title": article.title,
            "source_url": article.source_url,
        }
        for article in kb.articles
        if "placeholder" in article.text.lower() or "Phase C" in article.text
    ]
    blockers = []
    if coverage.get("placeholder_count", 0) > 0:
        blockers.append("placeholder_articles_remaining")
    if coverage.get("unverified_count", 0) > 0:
        blockers.append("unverified_articles_remaining")
    if coverage.get("stale_count", 0) > 0:
        blockers.append("stale_articles_require_review")
    if coverage.get("article_count", 0) < 100:
        blockers.append("article_count_below_100")
    return {
        "status": "ready" if coverage.get("production_ready") else "needs_work",
        "production_ready": bool(coverage.get("production_ready")),
        "coverage": coverage,
        "blockers": blockers,
        "top_unverified": unverified[:top],
        "top_stale": stale[:top],
        "top_placeholders": placeholders[:top],
        "recommended_next_steps": _recommendations(blockers),
    }


def _recommendations(blockers: list[str]) -> list[str]:
    mapping = {
        "placeholder_articles_remaining": "Replace placeholder seed articles with official law.go.kr/FSC/FSS/PIPC text or approved internal standards.",
        "unverified_articles_remaining": "Mark each article with verified provenance, effective date, and non-placeholder canonical text.",
        "stale_articles_require_review": "Refresh stale articles via official source fetch and rerun citation/verbatim gates.",
        "article_count_below_100": "Expand the official/internal-standard corpus to at least 100 verified articles before production mode.",
    }
    return [mapping[item] for item in blockers if item in mapping]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit Compliance Sentinel RAG/KB readiness report")
    parser.add_argument("--top", type=int, default=10, help="Number of issue examples to include")
    parser.add_argument("--out", help="Write JSON report to path")
    parser.add_argument("--fail-on-not-ready", action="store_true", help="Exit 2 when production_ready is false")
    args = parser.parse_args(argv)
    report = build_report(top=max(1, args.top))
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if args.fail_on_not_ready and not report["production_ready"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
