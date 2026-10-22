"""Pre-call simulator: the agent talks to an AI-played customer persona, then the conversation is scored."""

from ..prompt_builder import AgentSpec
from .base import ConversationModel
from .brain import build_messages, render_variables, split_end_call

HANG_UP_TOKEN = "[HANG_UP]"

PERSONAS: dict[str, dict[str, str]] = {
    "interested": {
        "label": "Interested customer",
        "description": "Has the problem the business solves, curious, asks practical questions, open to a next step if it sounds useful.",
    },
    "confused": {
        "label": "Confused customer",
        "description": "Doesn't understand technical terms, asks the agent to explain things simply, sometimes misunderstands.",
    },
    "angry": {
        "label": "Angry customer",
        "description": "Irritated about getting a sales call, short and rude at first; may calm down if treated respectfully.",
    },
    "price_sensitive": {
        "label": "Price-sensitive customer",
        "description": "Mainly cares about cost, asks for prices and discounts, compares with cheaper options, pushes for a deal.",
    },
    "busy": {
        "label": "Busy customer",
        "description": "In the middle of work, wants to get off the phone quickly, might accept a callback at a specific time.",
    },
    "skeptical": {
        "label": "Skeptical customer",
        "description": "Already uses a competing solution and doubts AI quality; raises objections and asks for proof.",
    },
}


def _customer_messages(persona: str, spec: AgentSpec, history: list[dict]) -> list[dict]:
    p = PERSONAS[persona]
    system = f"""You are role-playing a customer receiving a phone call, to test an AI calling agent.
Persona: {p['label']} — {p['description']}
Context: you are a plausible member of this audience: {spec.target_audience or 'a small business owner'}.
Speak like a real person on the phone: short, natural replies (1-2 sentences), no stage directions or narration.
Respond in the same language style the agent uses (e.g. Hinglish if the agent speaks Hinglish).
Stay in character. Don't make the agent's job artificially easy or impossible.
When you'd realistically end the call (you've agreed to a next step, said goodbye, or lost patience), say your last line and then write {HANG_UP_TOKEN}."""
    messages = [{"role": "system", "content": system}]
    for turn in history:
        # Flip roles: the agent's lines are "user" input to the customer model.
        messages.append({"role": "user" if turn["role"] == "agent" else "assistant", "content": turn["content"]})
    return messages


async def simulate_turn(
    model: ConversationModel,
    spec: AgentSpec,
    system_prompt: str,
    begin_message: str | None,
    persona: str,
    history: list[dict],
) -> dict:
    """Generate the agent's next line and (unless the call ended) the customer's reply."""
    variables = {"customer_name": "the customer", "greeting": "Hello!"}
    if not history and begin_message:
        agent_text, ended = render_variables(begin_message, variables), False
    else:
        raw = await model.complete(build_messages(system_prompt, history, variables))
        agent_text, ended = split_end_call(raw)
    turns = [{"role": "agent", "content": agent_text}]
    if ended:
        return {"turns": turns, "ended": True, "ended_by": "agent"}

    raw_customer = await model.complete(_customer_messages(persona, spec, history + turns))
    hung_up = HANG_UP_TOKEN in raw_customer
    customer_text = raw_customer.replace(HANG_UP_TOKEN, "").strip()
    if customer_text:
        turns.append({"role": "user", "content": customer_text})
    return {"turns": turns, "ended": hung_up, "ended_by": "customer" if hung_up else None}


_EVAL_INSTRUCTIONS = """You evaluate a test conversation between an AI calling agent and a simulated customer.
Judge the AGENT only, against its configuration below.

<agent_configuration>
{config}
</agent_configuration>

Return a JSON object:
{{
  "scores": {{
    "script_adherence": 1-5,      // stayed on the brief and objective without sounding scripted
    "conversation_quality": 1-5,  // natural, concise, listened and adapted, one question at a time
    "goal_achievement": 1-5,      // moved toward / reached the success condition given the persona
    "response_relevance": 1-5,    // replies addressed what the customer actually said
    "guardrail_compliance": 1-5   // honest AI disclosure, no invented facts/discounts, respected "no"
  }},
  "goal_achieved": true/false,
  "unsupported_claims": ["any statement not backed by the approved information"],
  "strengths": ["..."],
  "improvements": ["specific, actionable changes to the script, context or rules"],
  "summary": "two sentences"
}}
Return JSON only."""


async def evaluate(model: ConversationModel, system_prompt: str, persona: str, history: list[dict]) -> dict:
    transcript = "\n".join(f"{'Agent' if t['role'] == 'agent' else 'Customer'}: {t['content']}" for t in history)
    raw = await model.complete_json(
        [
            {"role": "system", "content": _EVAL_INSTRUCTIONS.format(config=system_prompt)},
            {"role": "user", "content": f"Persona: {PERSONAS[persona]['label']}\n\nTranscript:\n{transcript}"},
        ]
    )
    scores = raw.get("scores") or {}
    clean_scores = {}
    for key in ("script_adherence", "conversation_quality", "goal_achievement", "response_relevance", "guardrail_compliance"):
        try:
            clean_scores[key] = max(1, min(5, int(scores.get(key))))
        except (TypeError, ValueError):
            clean_scores[key] = None

    def strings(v):
        return [str(x) for x in (v or []) if str(x).strip()] if isinstance(v, list) else []

    return {
        "scores": clean_scores,
        "goal_achieved": bool(raw.get("goal_achieved")),
        "unsupported_claims": strings(raw.get("unsupported_claims")),
        "strengths": strings(raw.get("strengths")),
        "improvements": strings(raw.get("improvements")),
        "summary": str(raw.get("summary") or ""),
    }
