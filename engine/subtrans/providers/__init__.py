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
    raise ValueError(f"Непознат доставчик: {name} (налични: gemini, fake)")
