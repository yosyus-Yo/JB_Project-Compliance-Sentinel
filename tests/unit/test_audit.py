"""Audit Log 단위 테스트.

대상: src/compliance_sentinel/audit.py
  - AuditStore(path) — JSONL append writer
  - AuditStore.write(state) -> audit_id
  - AuditStore.audit_id(input_text) -> "AUD-<12char>"
  - sha256(value) -> 64-char hex

보안: 원본 PII 절대 노출 안 됨. redacted_text + replacement만 저장.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from compliance_sentinel.audit import AuditStore, sha256
from compliance_sentinel.models import ComplianceState, PIIFinding


class TestSha256:
    def test_returns_64_char_hex(self):
        h = sha256("hello")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self):
        assert sha256("same input") == sha256("same input")

    def test_different_input_different_hash(self):
        assert sha256("a") != sha256("b")

    def test_handles_korean_text(self):
        h = sha256("개인정보보호법")
        assert len(h) == 64

    def test_empty_string(self):
        h = sha256("")
        assert len(h) == 64
        # e3b0c44298... is sha256("")
        assert h.startswith("e3b0c44298fc1c14")


class TestAuditId:
    def test_format(self):
        store = AuditStore()
        aid = store.audit_id("test input")
        assert aid.startswith("AUD-")
        assert len(aid) == 16  # "AUD-" + 12 hex chars

    def test_same_input_same_id(self):
        store = AuditStore()
        assert store.audit_id("same") == store.audit_id("same")

    def test_different_input_different_id(self):
        store = AuditStore()
        assert store.audit_id("a") != store.audit_id("b")


class TestAuditStoreWrite:
    def test_write_creates_jsonl_file(self, tmp_audit_path: Path, sample_state):
        store = AuditStore(tmp_audit_path)
        aid = store.write(sample_state)
        assert tmp_audit_path.exists()
        assert aid.startswith("AUD-")

    def test_write_appends_line(self, tmp_audit_path: Path, sample_state):
        store = AuditStore(tmp_audit_path)
        store.write(sample_state)
        store.write(sample_state)
        lines = tmp_audit_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        # 각 라인은 유효 JSON
        for line in lines:
            entry = json.loads(line)
            assert "audit_log_id" in entry
            assert "created_at" in entry
            assert "input_hash" in entry

    def test_write_does_not_leak_raw_pii(self, tmp_audit_path: Path):
        raw_pii_text = "홍길동 010-1234-5678"
        state = ComplianceState(
            input_text=raw_pii_text,
            redacted_text="홍길동 [PHONE_REDACTED_1]",
            pii_findings=[PIIFinding("phone", "010-1234-5678", 4, 17, "[PHONE_REDACTED_1]")],
            input_type="advertisement",
        )
        store = AuditStore(tmp_audit_path)
        store.write(state)

        log_content = tmp_audit_path.read_text(encoding="utf-8")
        # 원본 PII가 audit 로그에 절대 노출 안 됨
        assert "010-1234-5678" not in log_content, "원본 PII가 audit log에 누출됨"
        # redacted_text는 노출됨 (정상)
        assert "[PHONE_REDACTED_1]" in log_content

    def test_write_creates_parent_dirs(self, tmp_path: Path, sample_state):
        nested = tmp_path / "deeply" / "nested" / "audit.jsonl"
        store = AuditStore(nested)
        store.write(sample_state)
        assert nested.exists()

    def test_input_hash_field_uses_sha256(self, tmp_audit_path: Path):
        state = ComplianceState(
            input_text="determinable text",
            redacted_text="determinable text",
            input_type="advertisement",
        )
        store = AuditStore(tmp_audit_path)
        store.write(state)
        entry = json.loads(tmp_audit_path.read_text(encoding="utf-8").strip())
        assert entry["input_hash"] == sha256("determinable text")
