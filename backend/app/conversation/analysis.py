"""Post-call analysis for calls we run ourselves (Twilio pipeline).

Retell analyses Managed/Custom Brain calls. For our own pipeline the same fields (the agent's
post_call_analysis_data plus summary/sentiment/success) are extracted with the ConversationModel and
returned in Retell's `call_analysis` shape, so `call_sync.apply_retell_call` stores them unchanged.
"""

from __future__ import annotations

import json

from ..prompt_builder import AgentSpec, build_post_call_analysis
from .base import ConversationModel

_INSTRUCTIONS = """You analyse a finished outbound sales/support phone call between an AI agent and a customer.
Return a JSON object with exactly these keys:
- "call_summary": 2-3 sentence summary of what happened.
- "user_sentiment": one of "Positive", "Neutral", "Negative".
- "call_successful": true if the call's goal was achieved.
{fields}
Base everything only on the transcript. Use "" for text fields that don't apply. Return JSON only."""


def _field_lines(spec: AgentSpec) -> str:
    lines = []
    for f in build_post_call_analysis(spec):
        if f["type"] == "enum":
            lines.append(f'- "{f["name"]}": one of {json.dumps(f["choices"])}. {f["description"]}')
        elif f["type"] == "boolean":
            lines.append(f'- "{f["name"]}": true or false. {f["description"]}')
        else:
            lines.append(f'- "{f["name"]}": string. {f["description"]}')
    return "\n".join(lines)


async def analyze_transcript(model: ConversationModel, spec: AgentSpec, transcript: list[dict]) -> dict:
    text = "\n".join(f"{'Agent' if t.get('role') == 'agent' else 'Customer'}: {t.get('content')}" for t in transcript if t.get("content"))
    raw = await model.complete_json(
        [
            {"role": "system", "content": _INSTRUCTIONS.format(fields=_field_lines(spec))},
            {"role": "user", "content": f"Goal: {spec.objective}\nSuccess condition: {spec.success_condition or '-'}\n\nTranscript:\n{text or '(no speech)'}"},
        ]
    )
    custom = {}
    for f in build_post_call_analysis(spec):
        value = raw.get(f["name"])
        if f["type"] == "enum" and value not in f["choices"]:
            value = None
        custom[f["name"]] = value
    sentiment = raw.get("user_sentiment") if raw.get("user_sentiment") in ("Positive", "Neutral", "Negative") else None
    return {
        "call_summary": str(raw.get("call_summary") or "").strip() or None,
        "user_sentiment": sentiment,
        "call_successful": bool(raw.get("call_successful")) if raw.get("call_successful") is not None else None,
        "custom_analysis_data": custom,
    }
