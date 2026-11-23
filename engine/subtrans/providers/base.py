from abc import ABC, abstractmethod


class TranslationProvider(ABC):
    """Takes a system prompt and a JSON user message, returns the model's raw text reply."""

    name = "base"
    model = ""

    @abstractmethod
    def complete(self, system: str, user: str) -> str: ...
