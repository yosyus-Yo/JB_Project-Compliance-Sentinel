from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .models import ComplianceState, to_plain

DEFAULT_AUDIT_PATH = Path("audit_logs") / "compliance_audit.jsonl"


class AuditStore:
    def __init__(self, path: str | Path = DEFAULT_AUDIT_PATH) -> None:
        self.path = Path(path)

    def write(self, state: ComplianceState) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        audit_id = self.audit_id(state.input_text)
        event = {
            "audit_log_id": audit_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "input_hash": sha256(state.input_text),
            "redacted_text": state.redacted_text,
            "input_type": state.input_type,
            "pii_findings": [{"kind": item.kind, "replacement": item.replacement} for item in state.pii_findings],
            "retrieved_citations": [to_plain(article) for article in state.retrieved_context],
            "verifier_results": [to_plain(result) for result in state.verifier_results],
            "routing_decision": state.routing_decision,
            "model_plan": state.model_plan,
            "llm_calls": state.llm_calls,
            "cross_model_result": state.cross_model_result,
            "short_term_memory": state.short_term_memory,
            "long_term_memory": state.long_term_memory,
            "rag_metadata": state.rag_metadata,
            "final_status": state.final_report.get("status"),
            "human_review_needed": state.human_review_needed,
            "trace": state.trace,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        return audit_id

    def audit_id(self, input_text: str) -> str:
        return f"AUD-{sha256(input_text)[:12]}"


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
