from abc import ABC, abstractmethod


class QuotaExceeded(Exception):
    """The provider refused the request because a rate or daily quota is used up (HTTP 429)."""


class TranslationProvider(ABC):
    """Takes a system prompt and a JSON user message, returns the model's raw text reply."""

    name = "base"
    model = ""

    @abstractmethod
    def complete(self, system: str, user: str) -> str: ...
