"""Custom Brain: turns a live call transcript into the agent's next reply."""

from datetime import datetime

from ..prompt_builder import DEFAULT_DYNAMIC_VARIABLES, END_CALL_TOKEN
from .base import Message

REMINDER_INSTRUCTION = (
    "(The customer has been silent for a while. Gently check if they're still there or re-ask your last "
    "question in a shorter way. Don't repeat yourself word for word.)"
)
OPENING_INSTRUCTION = (
    "(The customer just picked up the phone. Say your opening line now: greet them, say you're an AI assistant "
    "calling on behalf of the business, and ask if it's a good time. One or two short sentences.)"
)


def render_variables(text: str, variables: dict[str, str] | None) -> str:
    values = {**DEFAULT_DYNAMIC_VARIABLES, **(variables or {})}
    values.setdefault("current_time", datetime.now().astimezone().strftime("%A, %d %B %Y, %I:%M %p %Z"))
    for key, value in values.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    return text


def build_messages(
    system_prompt: str,
    transcript: list[dict],
    variables: dict[str, str] | None = None,
    reminder: bool = False,
) -> list[Message]:
    """`transcript` is Retell-style: [{"role": "agent" | "user", "content": "..."}]."""
    messages: list[Message] = [{"role": "system", "content": render_variables(system_prompt, variables)}]
    for turn in transcript:
        content = (turn.get("content") or "").strip()
        if content:
            messages.append({"role": "assistant" if turn.get("role") == "agent" else "user", "content": content})
    if len(messages) == 1:
        messages.append({"role": "user", "content": OPENING_INSTRUCTION})
    elif reminder:
        messages.append({"role": "user", "content": REMINDER_INSTRUCTION})
    return messages


class EndCallFilter:
    """Strips END_CALL_TOKEN from a streamed reply and records that the call should end.

    Holds back any trailing text that could be the start of the token so it's never spoken.
    """

    def __init__(self, token: str = END_CALL_TOKEN):
        self.token = token
        self.ended = False
        self._buf = ""

    def feed(self, chunk: str) -> str:
        if self.ended:
            return ""
        self._buf += chunk
        idx = self._buf.find(self.token)
        if idx >= 0:
            self.ended = True
            out, self._buf = self._buf[:idx], ""
            return out
        keep = 0
        for size in range(min(len(self.token) - 1, len(self._buf)), 0, -1):
            if self.token.startswith(self._buf[-size:]):
                keep = size
                break
        out = self._buf[: len(self._buf) - keep]
        self._buf = self._buf[len(self._buf) - keep :]
        return out

    def flush(self) -> str:
        out, self._buf = ("" if self.ended else self._buf), ""
        return out


def split_end_call(text: str) -> tuple[str, bool]:
    f = EndCallFilter()
    out = f.feed(text) + f.flush()
    return out.strip(), f.ended
