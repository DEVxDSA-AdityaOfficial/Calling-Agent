"""The conversation-model interface.

Everything that needs an LLM (Custom Brain calls, playbook generation, the simulator) goes through
`ConversationModel`, so swapping OpenAI for a self-hosted SLM is a configuration change
(CONVERSATION_PROVIDER=local_slm), not a rewrite.
"""

from collections.abc import AsyncIterator
from typing import Protocol, TypedDict


class Message(TypedDict):
    role: str  # system | user | assistant
    content: str


class ConversationModelError(Exception):
    pass


class ConversationModel(Protocol):
    name: str

    def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        """Yield the reply as text chunks (used on live calls for low latency)."""
        ...

    async def complete(self, messages: list[Message]) -> str:
        """Return the full reply."""
        ...

    async def complete_json(self, messages: list[Message]) -> dict:
        """Return the reply parsed as a JSON object."""
        ...
