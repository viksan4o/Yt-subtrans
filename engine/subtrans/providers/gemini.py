"""Google Gemini through the google-genai SDK, using the user's own API key."""

import os
import time

from ..throttle import RateLimiter
from .base import QuotaExceeded, TranslationProvider


FALLBACK_MODEL = "gemini-3.5-flash-lite"
# Seconds to wait before each retry when Google says the model is busy (503) or a per-minute
# limit is hit (429). After the last one a 429 counts as the daily quota (progress is kept).
BUSY_RETRIES = (5, 10, 20, 40, 60)


def _wait(seconds: float) -> None:  # module level so tests can replace it
    time.sleep(seconds)


def _code(e: Exception):
    return getattr(e, "code", None) or getattr(e, "status_code", None)


def _is_quota_error(e: Exception) -> bool:
    return _code(e) == 429 or "RESOURCE_EXHAUSTED" in str(e)


class GeminiProvider(TranslationProvider):
    name = "gemini"

    def __init__(self, model: str, rpm: int, rpd: int, api_key: str | None = None,
                 client=None, limiter: RateLimiter | None = None, sleep=None):
        self.model, self._sleep = model, sleep
        self.on_wait = None  # optional callback(message) shown while waiting before a retry
        self.limiter = limiter or RateLimiter(rpm, rpd)
        if client is None:
            key = api_key or os.environ.get("GEMINI_API_KEY")
            if not key:
                raise ValueError("Липсва Gemini API ключ. Задай GEMINI_API_KEY или подай --api-key. "
                                 "Без ключ ползвай локалния модел: --provider ollama")
            from google import genai  # imported lazily so tests and other providers do not need it
            client = genai.Client(api_key=key)
        self._client = client

    def complete(self, system: str, user: str) -> str:
        config = {"system_instruction": system, "response_mime_type": "application/json", "temperature": 0.3}
        for attempt in range(len(BUSY_RETRIES) + 1):
            self.limiter.wait()
            try:
                resp = self._client.models.generate_content(model=self.model, contents=user, config=config)
                return resp.text or ""
            except Exception as e:
                quota, code = _is_quota_error(e), _code(e)
                if code == 404:
                    raise RuntimeError(f"Gemini моделът „{self.model}“ не е наличен за този ключ. "
                                       f"Опитай с --model {FALLBACK_MODEL}") from e
                if not quota and code != 503:
                    raise
                if quota and "PerDay" in str(e):  # daily quota: waiting minutes will not help
                    raise QuotaExceeded(str(e)) from e
                if attempt == len(BUSY_RETRIES):
                    if quota:
                        raise QuotaExceeded(str(e)) from e
                    raise RuntimeError(f"Gemini моделът „{self.model}“ е претоварен в момента. Напредъкът "
                                       f"е запазен: опитай пак по-късно или с --model {FALLBACK_MODEL}") from e
                delay = BUSY_RETRIES[attempt]
                on_wait = getattr(self, "on_wait", None)
                if on_wait:
                    why = "лимитът на минута е достигнат" if quota else "Gemini е претоварен"
                    on_wait(f"{why}, чакам {delay} с и опитвам пак "
                    f"({attempt + 1}/{len(BUSY_RETRIES)})...")
                (getattr(self, "_sleep", None) or _wait)(delay)
