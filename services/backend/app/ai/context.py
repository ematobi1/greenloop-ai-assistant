import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.ai.errors import AiError
from app.ai.prompts import PromptManager
from app.ai.providers.base import ChatMessage, GenerationRequest
from app.ai.providers.transcript import escape_markup
from app.redaction import Redactor

CHARS_PER_TOKEN = 4


class HistoryItem(Protocol):
    role: str
    content: str
    status: str


@dataclass(frozen=True)
class ContextLimits:
    token_limit: int
    history_message_limit: int
    max_output_tokens: int
    temperature: float | None = None


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


class ContextBuilder:
    def __init__(self, prompts: PromptManager, redactor: Redactor, limits: ContextLimits):
        self._prompts = prompts
        self._redactor = redactor
        self._limits = limits

    def build(
        self,
        history: Sequence[HistoryItem],
        user_message: str,
        instructions: str | None = None,
    ) -> GenerationRequest:
        preferences = escape_markup(self._redactor.redact(instructions)) if instructions else None
        system = self._prompts.chat_system(preferences)
        budget = self._limits.token_limit - estimate_tokens(system)

        newest = ChatMessage("user", self._redactor.redact(user_message))
        budget -= estimate_tokens(newest.content)
        if budget < 0:
            raise AiError("context_too_large")

        kept = self._newest_history_that_fits(history, budget)
        return GenerationRequest(
            system=system,
            messages=[*kept, newest],
            max_output_tokens=self._limits.max_output_tokens,
            temperature=self._limits.temperature,
        )

    def _newest_history_that_fits(
        self, history: Sequence[HistoryItem], budget: int
    ) -> list[ChatMessage]:
        usable = [
            item
            for item in history
            if item.status == "complete" and item.role in {"user", "assistant"}
        ][-self._limits.history_message_limit :]
        kept: list[ChatMessage] = []
        for item in reversed(usable):
            content = self._redactor.redact(item.content)
            budget -= estimate_tokens(content)
            if budget < 0:
                break
            kept.append(ChatMessage(item.role, content))  # type: ignore[arg-type]
        kept.reverse()
        return kept
