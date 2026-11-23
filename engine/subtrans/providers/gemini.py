"""Google Gemini through the google-genai SDK, using the user's own API key."""

import os

from ..throttle import RateLimiter
from .base import QuotaExceeded, TranslationProvider


def _is_quota_error(e: Exception) -> bool:
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    return code == 429 or "RESOURCE_EXHAUSTED" in str(e)


class GeminiProvider(TranslationProvider):
    name = "gemini"

    def __init__(self, model: str, rpm: int, rpd: int, api_key: str | None = None,
                 client=None, limiter: RateLimiter | None = None):
        self.model = model
        self.limiter = limiter or RateLimiter(rpm, rpd)
        if client is None:
            key = api_key or os.environ.get("GEMINI_API_KEY")
            if not key:
                raise ValueError("Липсва Gemini API ключ. Задай GEMINI_API_KEY (или го въведи в настройките).")
            from google import genai  # imported lazily so tests and other providers do not need it
            client = genai.Client(api_key=key)
        self._client = client

    def complete(self, system: str, user: str) -> str:
        self.limiter.wait()
        try:
            resp = self._client.models.generate_content(
                model=self.model, contents=user,
                config={"system_instruction": system, "response_mime_type": "application/json",
                        "temperature": 0.3})
        except Exception as e:
            if _is_quota_error(e):
                raise QuotaExceeded(str(e)) from e
            raise
        return resp.text or ""
