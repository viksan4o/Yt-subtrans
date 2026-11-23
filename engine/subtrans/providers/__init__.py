"""Translation providers. Only the offline `fake` provider exists in this first slice."""

from .base import TranslationProvider
from .fake import FakeProvider


def get_provider(name: str, model: str | None = None) -> TranslationProvider:
    if name == "fake":
        return FakeProvider()
    raise ValueError(f"Непознат доставчик: {name} (засега е наличен само 'fake')")
