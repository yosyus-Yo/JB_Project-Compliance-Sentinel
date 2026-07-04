"""골든셋 자동 환류 테스트 — 가이드 함정(골든셋 정체) 방지.

프로덕션 오심(/feedback 👎 등)을 evals/production_failures.jsonl에 PII 제거 후
append하고, load_golden_cases가 회귀 케이스로 포함하는지 검증.
PROJECT_ROOT를 tmp로 monkeypatch해 실제 repo 골든셋을 오염시키지 않는다.
"""
from __future__ import annotations

import pytest

from compliance_sentinel import golden_regression as gr


@pytest.fixture
def _tmp_root(monkeypatch, tmp_path):
    monkeypatch.setattr(gr, "PROJECT_ROOT", tmp_path)
    return tmp_path


def test_capture_appends_red_team_schema(_tmp_root):
    cid = gr.capture_production_failure("원금 보장! 누구나 승인되는 대출")
    assert cid and cid.startswith("prod-fail-")
    cases = gr._read_jsonl(_tmp_root / "evals" / "production_failures.jsonl")
    assert len(cases) == 1
    c = cases[0]
    assert c["category"] == "production_failure"
    assert c["expected"] == "verifier_fail_or_human_review"  # 금융 안전편향
    assert c["flagged_by"] == "human_feedback"
    assert {"id", "input", "expected", "priority"} <= set(c)  # red_team 스키마 호환


def test_capture_dedup(_tmp_root):
    gr.capture_production_failure("동일한 위험 광고 문구")
    second = gr.capture_production_failure("동일한 위험 광고 문구")
    assert second is None  # 같은 입력 → dedup
    cases = gr._read_jsonl(_tmp_root / "evals" / "production_failures.jsonl")
    assert len(cases) == 1


def test_capture_pii_redacted(_tmp_root):
    gr.capture_production_failure("문의 홍길동 010-1234-5678 hong@example.com 원금보장")
    cases = gr._read_jsonl(_tmp_root / "evals" / "production_failures.jsonl")
    blob = cases[0]["input"]
    assert "010-1234-5678" not in blob
    assert "hong@example.com" not in blob


def test_capture_cap(monkeypatch, _tmp_root):
    monkeypatch.setattr(gr, "MAX_PRODUCTION_FAILURES", 2)
    assert gr.capture_production_failure("케이스 A")
    assert gr.capture_production_failure("케이스 B")
    assert gr.capture_production_failure("케이스 C") is None  # 상한 도달


def test_capture_loaded_as_golden_case(_tmp_root):
    """환류된 케이스가 load_golden_cases에 회귀 케이스로 포함된다."""
    gr.capture_production_failure("위험한 금융 광고")
    loaded = gr.load_golden_cases()  # tmp엔 red_team/marketing 없음 → production_failures만
    prod = [c for c in loaded if c.get("category") == "production_failure"]
    assert len(prod) == 1
    assert prod[0]["source_file"] == "evals/production_failures.jsonl"


def test_capture_empty_input_noop(_tmp_root):
    assert gr.capture_production_failure("   ") is None
    assert not (_tmp_root / "evals" / "production_failures.jsonl").exists()


def test_capture_never_raises(_tmp_root, monkeypatch):
    """환류 실패가 호출자(피드백)를 중단시키지 않는다."""
    monkeypatch.setattr(gr, "_read_jsonl", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert gr.capture_production_failure("x") is None  # 예외 전파 없이 None
