"""공식 법령 원문 확대 — fetch 도구의 KB 자동 타겟 추출 테스트.

fetch_law_open_api_articles.py의 default_targets_from_kb / load_targets 강화
(하드코딩 13 → laws.json 법령형 조문 자동 확대 + DEFAULT 병합)를 검증.
실제 law.go.kr fetch는 LAW_OPEN_API_KEY가 필요하므로 여기서는 타겟 선정 로직만.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

flo = pytest.importorskip("fetch_law_open_api_articles")


def test_default_targets_picks_statutes_only():
    rows = [
        {"law_name": "금융소비자보호법", "article_no": "19", "source_url": "local://x"},
        {"law_name": "개인정보보호법", "article_no": "15", "source_url": ""},
        {"law_name": "전자금융감독규정", "article_no": "2", "source_url": "local://y"},
        {"law_name": "금융위 금융광고규제 가이드라인", "article_no": "1", "source_url": "local://z"},  # 비법령형 제외
        {"law_name": "JB 마케팅 콘텐츠 심의 기준", "article_no": "3", "source_url": "local://w"},  # 내부기준 제외
    ]
    targets = flo.default_targets_from_kb(rows)
    laws = {t[0] for t in targets}
    assert "금융소비자보호법" in laws
    assert "개인정보보호법" in laws
    assert "전자금융감독규정" in laws  # ~규정 = 법령형
    assert "금융위 금융광고규제 가이드라인" not in laws  # 가이드라인 제외
    assert "JB 마케팅 콘텐츠 심의 기준" not in laws  # 내부 기준 제외


def test_default_targets_skips_already_official():
    rows = [
        {"law_name": "은행법", "article_no": "34", "source_url": "https://www.law.go.kr/..."},  # 이미 공식 → skip
        {"law_name": "보험업법", "article_no": "95", "source_url": "local://internal"},  # 미공식 → 포함
    ]
    targets = flo.default_targets_from_kb(rows)
    assert ("은행법", "34") not in targets
    assert ("보험업법", "95") in targets


def test_default_targets_dedup():
    rows = [
        {"law_name": "은행법", "article_no": "34", "source_url": "local://a"},
        {"law_name": "은행법", "article_no": "34", "source_url": "local://b"},  # 중복
    ]
    assert flo.default_targets_from_kb(rows) == [("은행법", "34")]


def test_load_targets_merges_default_and_kb():
    rows = [{"law_name": "보험업법", "article_no": "95", "source_url": "local://x"}]
    merged = flo.load_targets(None, rows)
    assert len(merged) >= len(flo.DEFAULT_TARGETS)  # DEFAULT 보존
    assert ("보험업법", "95") in merged  # KB 자동 추가
    # DEFAULT 핵심 1건 포함 확인
    assert flo.DEFAULT_TARGETS[0] in merged


def test_load_targets_real_kb_expands_beyond_hardcoded():
    import json

    kb = Path(__file__).resolve().parents[2] / "data" / "laws.json"
    rows = json.loads(kb.read_text(encoding="utf-8"))
    merged = flo.load_targets(None, rows)
    # 강화 전(하드코딩 15)보다 실제 KB 병합이 더 많아야 함
    assert len(merged) > len(flo.DEFAULT_TARGETS)
