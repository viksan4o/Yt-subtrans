"""Translation providers."""

from .base import QuotaExceeded, TranslationProvider
from .fake import FakeProvider


def get_provider(name: str, model: str | None = None, rpm: int | None = None,
                 rpd: int | None = None) -> TranslationProvider:
    if name == "fake":
        return FakeProvider()
    if name == "gemini":
        from ..config import gemini_settings
        from .gemini import GeminiProvider
        return GeminiProvider(**gemini_settings(model, rpm, rpd))
    if name == "claude":
        from ..config import claude_settings
        from .claude import ClaudeProvider
        return ClaudeProvider(**claude_settings(model, rpm, rpd))
    if name == "ollama":
        from ..config import ollama_settings
        from .ollama import OllamaProvider
        return OllamaProvider(**ollama_settings(model))
    raise ValueError(f"Непознат доставчик: {name} (налични: gemini, claude, ollama, fake)")
