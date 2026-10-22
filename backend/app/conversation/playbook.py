"""Script-to-Agent intelligence: expand a short objective + script into a conversation playbook."""

from ..prompt_builder import AgentSpec, LANGUAGES
from .base import ConversationModel, ConversationModelError

PLAYBOOK_KEYS = [
    "opening",
    "qualification_questions",
    "value_points",
    "objections",
    "follow_up_questions",
    "closing_strategy",
    "success_criteria",
]

_INSTRUCTIONS = """You design outbound phone-call strategies for AI voice agents.
Given a business's calling objective, script and approved information, write a conversation playbook
the agent will use as guidance (not a rigid script).

Rules:
- Use ONLY facts present in the input. Never invent prices, features, discounts, statistics or customer names.
  If information is missing, make the agent ask or offer a follow-up instead of stating facts.
- Everything will be spoken on a phone call: short, natural sentences.
- Write the spoken lines in {language}.
- Objection responses acknowledge the concern, answer with approved info, then ask a question that moves forward.

Return a JSON object with exactly these keys:
{{
  "opening": "one or two sentences: greeting, AI disclosure for {business}, reason for calling, permission to continue",
  "qualification_questions": ["3-5 short questions to understand the customer's situation and fit"],
  "value_points": ["3-5 ways to explain the offering, each tied to a customer need"],
  "objections": [{{"objection": "likely objection", "response": "how to handle it"}}],
  "follow_up_questions": ["2-4 questions that keep the conversation moving"],
  "closing_strategy": "how to ask for the next step and confirm details",
  "success_criteria": ["observable conditions that mean this call achieved its goal"]
}}
Include 4-6 objections. Return JSON only."""


def _input(spec: AgentSpec) -> str:
    parts = [
        f"Business: {spec.business_name}",
        f"Agent name: {spec.name}",
        f"Objective: {spec.objective}",
        f"Target audience: {spec.target_audience or 'not specified'}",
        f"Success condition: {spec.success_condition or 'not specified'}",
        f"Fallback if not interested: {spec.fallback_behavior or 'close politely'}",
        f"Script / brief:\n{spec.script}",
    ]
    if spec.additional_context:
        parts.append(f"Approved information (products, pricing, FAQs):\n{spec.additional_context}")
    if spec.dos_and_donts:
        parts.append(f"Do's and don'ts:\n{spec.dos_and_donts}")
    return "\n\n".join(parts)


def _normalize(raw: dict) -> dict:
    def strings(value) -> list[str]:
        if isinstance(value, str):
            value = [value]
        return [str(v).strip() for v in (value or []) if str(v).strip()][:8]

    objections = []
    for item in raw.get("objections") or []:
        if isinstance(item, dict) and item.get("objection") and item.get("response"):
            objections.append({"objection": str(item["objection"]).strip(), "response": str(item["response"]).strip()})
    playbook = {
        "opening": str(raw.get("opening") or "").strip(),
        "qualification_questions": strings(raw.get("qualification_questions")),
        "value_points": strings(raw.get("value_points")),
        "objections": objections[:8],
        "follow_up_questions": strings(raw.get("follow_up_questions")),
        "closing_strategy": str(raw.get("closing_strategy") or "").strip(),
        "success_criteria": strings(raw.get("success_criteria")),
    }
    if not playbook["opening"] and not playbook["qualification_questions"]:
        raise ConversationModelError("The model returned an empty playbook. Try again.")
    return playbook


async def generate_playbook(model: ConversationModel, spec: AgentSpec) -> dict:
    language = LANGUAGES.get(spec.language, spec.language)
    if spec.language == "hinglish":
        language = "Hinglish (Hindi in Roman script mixed with English)"
    raw = await model.complete_json(
        [
            {"role": "system", "content": _INSTRUCTIONS.format(language=language, business=spec.business_name)},
            {"role": "user", "content": _input(spec)},
        ]
    )
    return _normalize(raw)
