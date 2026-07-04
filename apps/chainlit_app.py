"""Optional Chainlit demo app.

Run after installing chainlit:
  chainlit run apps/chainlit_app.py
"""
from __future__ import annotations

try:
    import chainlit as cl
except Exception:  # pragma: no cover
    cl = None

try:  # .env의 ANTHROPIC_API_KEY / CS_ENABLE_LLM_RUNTIME 주입 (compliance_sentinel 사용 전)
    from compliance_sentinel.env_bootstrap import load_env_file

    load_env_file()
except Exception:  # pragma: no cover
    pass

from compliance_sentinel.engine import analyze_with_engine
from compliance_sentinel.reporting import render_markdown

if cl is not None:

    @cl.on_message
    async def on_message(message):
        result = analyze_with_engine(message.content)
        prefix = f"`engine={result.engine}`"
        if result.fallback_reason:
            prefix += f" `fallback={result.fallback_reason}`"
        await cl.Message(content=f"{prefix}\n\n{render_markdown(result.state.final_report)}").send()
