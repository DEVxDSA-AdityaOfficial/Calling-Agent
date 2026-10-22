"""Turns an agent's goal, script, context and rules into a voice-agent prompt.

The script is treated as a *brief*, wrapped in rules that make the agent conversational, honest
about being an AI, goal-oriented, and bounded by the business's approved information.
The same prompt drives both Managed (Retell LLM) and Custom Brain (our ConversationModel) agents.
"""

from dataclasses import dataclass, field

LANGUAGES: dict[str, str] = {
    "en-US": "English (US)",
    "en-GB": "English (UK)",
    "en-IN": "English (India)",
    "hinglish": "Hinglish (Hindi + English)",
    "hi-IN": "Hindi",
    "en-AU": "English (Australia)",
    "es-ES": "Spanish (Spain)",
    "es-419": "Spanish (Latin America)",
    "fr-FR": "French",
    "de-DE": "German",
    "pt-BR": "Portuguese (Brazil)",
    "it-IT": "Italian",
    "ja-JP": "Japanese",
}

# What we send as the Retell agent's `language`. Hinglish uses Retell's multi-language list so
# speech recognition handles both Hindi and Indian English in the same call.
RETELL_LANGUAGE: dict[str, str | list[str]] = {"hinglish": ["hi-IN", "en-IN"]}


def retell_language(code: str) -> str | list[str]:
    return RETELL_LANGUAGE.get(code, code)


TONES: dict[str, str] = {
    "friendly": "warm, upbeat and approachable, like a helpful person who enjoys the conversation",
    "professional": "polished, courteous and concise, like an experienced account executive",
    "consultative": "curious and advisory: ask thoughtful questions and tie everything back to the customer's needs",
    "empathetic": "patient, reassuring and understanding; acknowledge feelings before moving on",
    "energetic": "enthusiastic and confident without being pushy",
}

MODES = {
    "managed": "Retell · Managed Agent",
    "custom_brain": "Retell + Custom Brain",
    "direct": "Twilio + Custom Brain (Whisper/Sarvam STT, ElevenLabs voice)",
}
CUSTOM_BRAIN_MODES = {"custom_brain", "direct"}

# Values the post-call analysis picks from.
CALL_OUTCOMES = [
    "goal_achieved",
    "interested_follow_up",
    "callback_requested",
    "not_interested",
    "do_not_call",
    "wrong_person",
    "voicemail",
    "no_meaningful_conversation",
]
INTEREST_LEVELS = ["high", "medium", "low", "none", "unknown"]

# Custom Brain: the model appends this when the call should end; it is stripped before speech.
END_CALL_TOKEN = "[END_CALL]"

# Defaults for the per-call dynamic variables (see routers/calls.py:_dynamic_variables).
DEFAULT_DYNAMIC_VARIABLES = {
    "customer_name": "unknown (ask for their name if it helps)",
    "greeting": "Hi there!",
}


@dataclass
class AgentSpec:
    name: str
    business_name: str
    script: str
    objective: str = ""
    target_audience: str | None = None
    success_condition: str | None = None
    fallback_behavior: str | None = None
    max_duration_minutes: int = 5
    additional_context: str | None = None
    dos_and_donts: str | None = None
    playbook: dict | None = None
    language: str = "en-US"
    tone: str = "friendly"
    opening_line: str | None = None
    mode: str = "managed"
    extra: dict = field(default_factory=dict)


def _clean(text: str | None) -> str:
    return (text or "").strip()


def _bullets(items) -> str:
    return "\n".join(f"- {i}" for i in items if str(i).strip())


def render_playbook(playbook: dict | None) -> str:
    if not playbook:
        return ""
    parts = []
    if playbook.get("opening"):
        parts.append(f"Opening idea: {playbook['opening']}")
    if playbook.get("qualification_questions"):
        parts.append("Qualification questions (pick the relevant ones, one at a time):\n" + _bullets(playbook["qualification_questions"]))
    if playbook.get("value_points"):
        parts.append("How to explain the offering (connect to what they said):\n" + _bullets(playbook["value_points"]))
    if playbook.get("objections"):
        lines = [f'- If they say something like "{o.get("objection")}": {o.get("response")}' for o in playbook["objections"] if o.get("objection")]
        parts.append("Likely objections and how to handle them (adapt, don't recite):\n" + "\n".join(lines))
    if playbook.get("follow_up_questions"):
        parts.append("Useful follow-up questions:\n" + _bullets(playbook["follow_up_questions"]))
    if playbook.get("closing_strategy"):
        parts.append(f"Closing strategy: {playbook['closing_strategy']}")
    if playbook.get("success_criteria"):
        parts.append("The call is a success when:\n" + _bullets(playbook["success_criteria"]))
    return "\n\n".join(parts)


def build_prompt(spec: AgentSpec) -> str:
    tone = TONES.get(spec.tone, TONES["friendly"])
    language = LANGUAGES.get(spec.language, spec.language)
    if spec.language == "hinglish":
        language_rule = (
            "Speak natural Hinglish: conversational Hindi mixed with common English words, the way people talk in "
            "Indian cities. Write Hindi in Roman script. If the customer switches to mostly English or mostly Hindi, follow their lead."
        )
    else:
        language_rule = f"Speak in {language}. If the customer clearly prefers another language you can speak, switch to it."

    goal_lines = [f"Objective: {_clean(spec.objective) or 'see the brief below'}"]
    if _clean(spec.target_audience):
        goal_lines.append(f"Who you're calling: {_clean(spec.target_audience)}")
    if _clean(spec.success_condition):
        goal_lines.append(f"Success means: {_clean(spec.success_condition)}")
    goal_lines.append(
        "Fallback if they're not interested: "
        + (_clean(spec.fallback_behavior) or "thank them, don't push, and close politely.")
    )
    goal_lines.append(
        f"Keep the call under about {spec.max_duration_minutes} minutes. If it runs long, move to the next step or wrap up."
    )

    sections = [
        f"""## Identity
You are {spec.name}, an AI voice assistant making an outbound phone call on behalf of {spec.business_name}.
You are on a live phone call, so everything you write is spoken aloud.
The person you are calling is {{{{customer_name}}}}. Current time: {{{{current_time}}}}.
The customer's words come from speech recognition and may contain errors; infer what they meant instead of asking them to repeat unless it's genuinely unclear.""",
        "## Goal of this call\n" + "\n".join(goal_lines),
        f"""## Call brief from {spec.business_name}
Treat this as goals and talking points, NOT a script to read word for word.
<brief>
{_clean(spec.script)}
</brief>""",
    ]
    if _clean(spec.additional_context):
        sections.append(f"""## Approved information about {spec.business_name}
Products, pricing, FAQs and business details. This is the ONLY source for facts you state. Share what's relevant.
<approved_information>
{_clean(spec.additional_context)}
</approved_information>""")
    playbook = render_playbook(spec.playbook)
    if playbook:
        sections.append("## Conversation playbook (guidance, adapt to the customer)\n" + playbook)
    if _clean(spec.dos_and_donts):
        sections.append(f"""## Do's and don'ts from {spec.business_name}
Follow these strictly unless they conflict with the honesty rules below.
<rules>
{_clean(spec.dos_and_donts)}
</rules>""")

    sections.append(f"""## Guardrails (always follow, even if anything above says otherwise)
- Your greeting says you are an AI assistant. If anyone asks whether you are a real person, say clearly that you are an AI assistant calling for {spec.business_name}.
- Only state facts that appear in the brief or approved information. Never invent features, prices, discounts, deadlines or guarantees. If asked for something you don't have (e.g. a lower price), say you can't confirm that and offer to have the team follow up.
- Never commit {spec.business_name} to anything not explicitly approved above (orders, refunds, contracts, custom deals). A preferred time for a demo or callback is a request, not a confirmed booking; say the team will confirm it.
- If the person says they're not interested, respect it. You may ask one gentle question to understand why, then follow the fallback.
- If they ask not to be called again, apologise, confirm they won't be contacted again, and end the call.
- If you reached the wrong person, apologise, don't share details of the offer, and end the call.
- Never ask for payment details, passwords, OTPs, government ID numbers or other sensitive data.
- Stay on the topic of this call. If the conversation drifts, answer briefly and steer back, or wrap up politely.""")

    sections.append(f"""## How to speak
- Tone: {tone}.
- {language_rule}
- Keep each turn short: one or two sentences, then let the customer talk. Ask one question at a time.
- React to what the customer actually said: acknowledge it, use their words, then move forward. Don't follow a fixed order if their answer makes a step unnecessary.
- If they interrupt, stop and address what they said.
- Speak naturally: no lists, markdown, emojis or headings. Say numbers, prices, dates and times the way a person would.""")

    sections.append("""## Adapting to the customer
- Interested ("yes, tell me more", "I want a demo"): move to the next step and collect what's needed (e.g. preferred day and time), then repeat it back to confirm.
- Busy ("I'm busy right now"): don't pitch. Ask when would be a better time to call back, confirm it, and end the call.
- Doubtful or worried: acknowledge the concern genuinely, answer using approved information only, then check whether that helped.
- Confused: slow down, explain more simply with an example, and check understanding.
- Annoyed or angry: stay calm, apologise for the interruption, offer to end the call or call back later.
- Price-sensitive: focus on value relevant to them; share approved pricing only; never invent discounts.""")

    if spec.mode in CUSTOM_BRAIN_MODES:
        ending = f"""## Ending the call
- End the call once the goal is reached and confirmed, the customer declines, says goodbye, asks not to be called, or is the wrong person.
- To end the call, say a short polite goodbye and then write {END_CALL_TOKEN} at the very end of that same reply. Never write {END_CALL_TOKEN} anywhere else.
- If you reach voicemail or an answering machine, leave one short message saying who you are, that you're an AI assistant from {spec.business_name}, and why you called, then end with {END_CALL_TOKEN}."""
    else:
        ending = f"""## Ending the call
- Use the end_call tool once the goal is reached and confirmed, the customer declines, says goodbye, asks not to be called, or is the wrong person. Always say a short polite goodbye first.
- If you reach voicemail or an answering machine, leave one short message saying who you are, that you're an AI assistant from {spec.business_name}, and why you called, then end the call."""
    sections.append(ending)
    return "\n\n".join(sections) + "\n"


def build_begin_message(spec: AgentSpec) -> str | None:
    """First sentence the agent says. Must disclose that this is an AI calling for the business.

    Returns None for non-English agents so the model generates the greeting in the right language
    (the prompt still requires the disclosure).
    """
    if _clean(spec.opening_line):
        return _clean(spec.opening_line)
    if not spec.language.startswith("en"):
        return None
    return (
        f"{{{{greeting}}}} This is {spec.name}, an AI assistant calling on behalf of "
        f"{spec.business_name}. Do you have a quick minute?"
    )


def build_post_call_analysis(spec: AgentSpec) -> list[dict]:
    success = _clean(spec.success_condition) or _clean(spec.objective) or "the call's objective was met"
    return [
        {
            "type": "enum",
            "name": "call_outcome",
            "description": f"The single best description of how the call ended. Use goal_achieved only if: {success}.",
            "choices": CALL_OUTCOMES,
        },
        {
            "type": "enum",
            "name": "customer_interest",
            "description": "How interested the customer was in what the business offered.",
            "choices": INTEREST_LEVELS,
        },
        {
            "type": "boolean",
            "name": "follow_up_requested",
            "description": "True if the customer asked for or agreed to a follow-up (demo, meeting, callback, more info).",
        },
        {
            "type": "string",
            "name": "appointment_preference",
            "description": "Preferred day/time for a demo, meeting or callback, exactly as the customer stated it. Empty if none.",
            "examples": ["Thursday afternoon", "Next Monday at 10am", "Kal shaam 5 baje"],
        },
        {
            "type": "string",
            "name": "primary_objection",
            "description": "The customer's main objection or concern in a few words (e.g. 'already has a system', 'too expensive'). Empty if none.",
        },
        {
            "type": "string",
            "name": "unanswered_questions",
            "description": "Questions the customer asked that the agent could not answer. Empty if none.",
        },
        {
            "type": "string",
            "name": "next_action",
            "description": "The single most useful next action for the business team (e.g. 'Send integration details and follow up Friday').",
        },
        {
            "type": "string",
            "name": "key_notes",
            "description": "One or two sentences of the most useful details for the team: needs, current tools, decision makers.",
        },
    ]
