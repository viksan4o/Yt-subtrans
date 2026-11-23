"""Offline provider for tests and development: 'translates' by prefixing each cue with [BG]."""

import json

from .base import TranslationProvider


class FakeProvider(TranslationProvider):
    name = "fake"
    model = "fake"

    def complete(self, system: str, user: str) -> str:
        cues = json.loads(user)["cues"]
        return json.dumps([{"id": c["id"], "text": "[BG] " + c["text"]} for c in cues], ensure_ascii=False)
