"""Anthropic Claude through the official `anthropic` SDK, using the user's own API key (paid)."""

import os

from ..throttle import RateLimiter
from .base import QuotaExceeded, TranslationProvider

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeProvider(TranslationProvider):
    name = "claude"

    def __init__(self, model: str, rpm: int, rpd: int, api_key: str | None = None,
                 client=None, limiter: RateLimiter | None = None):
        self.model = model
        self.limiter = limiter or RateLimiter(rpm, rpd)
        if client is None:
            key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise ValueError("Липсва Anthropic API ключ. Задай ANTHROPIC_API_KEY (или го въведи в настройките).")
            import anthropic  # imported lazily so tests and other providers do not need it
            client = anthropic.Anthropic(api_key=key)
        self._client = client

    def complete(self, system: str, user: str) -> str:
        self.limiter.wait()
        kwargs = dict(model=self.model, max_tokens=16000, system=system,
                      messages=[{"role": "user", "content": user}],
                      output_config={"effort": os.environ.get("ANTHROPIC_EFFORT", "medium")})
        if not self.model.startswith("claude-haiku"):  # Haiku has no server-side refusal fallback
            kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
        try:
            resp = self._client.beta.messages.create(**kwargs)
        except Exception as e:
            status = getattr(e, "status_code", None)
            if status in (429, 529) or type(e).__name__ in ("RateLimitError", "OverloadedError"):
                raise QuotaExceeded(str(e)) from e
            raise
        if resp.stop_reason == "refusal":
            return ""  # empty reply fails validation, so the batch is retried and then split
        return "".join(b.text for b in resp.content if b.type == "text")
