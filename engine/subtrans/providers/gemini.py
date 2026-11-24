"""Google Gemini through the google-genai SDK, using the user's own API key."""

import os
import time

from ..throttle import RateLimiter
from .base import QuotaExceeded, TranslationProvider


# Tried in this order when the chosen model is unknown for the key (404), stays busy (503) or has
# used up its own daily quota (quotas are per model). Flash models first: flash-lite translated
# into Bulgarian with invented words in real clips (Nov 2026), so it is only the last resort.
FALLBACK_MODELS = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
                   "gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
# Seconds to wait before each retry of the same model after a per-minute limit (429).
# After the last one a 429 counts as the daily quota (progress is kept).
BUSY_RETRIES = (5, 10, 20, 40, 60)
# A busy model (503) gets this many waits before switching to the next fallback model; the last
# model in the chain gets all of BUSY_RETRIES.
BUSY_BEFORE_SWITCH = 2
# An overloaded model can leave a request hanging for many minutes (seen Nov 2026), so every
# request gets a time limit; a model that does not answer in time is skipped for the next one.
REQUEST_TIMEOUT_S = int(os.environ.get("GEMINI_TIMEOUT") or 60)


class _ModelUnavailable(Exception):
    pass


def list_models(api_key: str | None = None, client=None) -> list[str]:
    """Gemini models this key may call with generateContent (one ListModels request)."""
    if client is None:
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ValueError("Липсва Gemini API ключ. Задай GEMINI_API_KEY или подай --api-key.")
        from google import genai
        client = genai.Client(api_key=key)
    return sorted(m.name.removeprefix("models/") for m in client.models.list()
                  if "generateContent" in (getattr(m, "supported_actions", None) or [])
                  and "gemini" in m.name)


def _wait(seconds: float) -> None:  # module level so tests can replace it
    time.sleep(seconds)


def _code(e: Exception):
    return getattr(e, "code", None) or getattr(e, "status_code", None)


def _is_timeout(e: Exception) -> bool:
    return (isinstance(e, TimeoutError) or "Timeout" in type(e).__name__ or "timed out" in str(e).lower()
            or _code(e) == 504 or "DEADLINE_EXCEEDED" in str(e))


def _is_quota_error(e: Exception) -> bool:
    return _code(e) == 429 or "RESOURCE_EXHAUSTED" in str(e)


class GeminiProvider(TranslationProvider):
    name = "gemini"
    # Smaller than the generic 90: on long batches translations drifted by a cue or more.
    batch_size = int(os.environ.get("GEMINI_BATCH") or 40)

    def __init__(self, model: str, rpm: int, rpd: int, api_key: str | None = None,
                 client=None, limiter: RateLimiter | None = None, sleep=None,
                 fallbacks: tuple[str, ...] = FALLBACK_MODELS):
        self.model, self._sleep = model, sleep
        self.fallbacks = fallbacks
        self._failed: set[str] = set()
        self.on_wait = None  # optional callback(message) shown while waiting before a retry
        self.limiter = limiter or RateLimiter(rpm, rpd)
        self.limiter.on_wait = self._say
        if client is None:
            key = api_key or os.environ.get("GEMINI_API_KEY")
            if not key:
                raise ValueError("Липсва Gemini API ключ. Задай GEMINI_API_KEY или подай --api-key. "
                                 "Без ключ ползвай локалния модел: --provider ollama")
            from google import genai  # imported lazily so tests and other providers do not need it
            client = genai.Client(api_key=key, http_options={"timeout": REQUEST_TIMEOUT_S * 1000})
        self._client = client

    def _say(self, message: str) -> None:
        on_wait = getattr(self, "on_wait", None)
        if on_wait:
            on_wait(message)

    def _next_model(self) -> str | None:
        failed = getattr(self, "_failed", set()) | {self.model}
        return next((m for m in getattr(self, "fallbacks", ()) if m not in failed), None)

    def complete(self, system: str, user: str) -> str:
        while True:
            try:
                return self._complete_with(self.model, system, user)
            except _ModelUnavailable as e:
                nxt = self._next_model()
                if nxt is None:
                    raise RuntimeError(f"{e} Няма друг наличен Gemini модел. Напредъкът е запазен: "
                                       "опитай пак по-късно (list-models показва моделите).") from e
                self._failed = getattr(self, "_failed", set()) | {self.model}
                self._say(f"{e} Минавам на „{nxt}“.")
                self.model = nxt

    def _complete_with(self, model: str, system: str, user: str) -> str:
        config = {"system_instruction": system, "response_mime_type": "application/json", "temperature": 0.3}
        busy_limit = BUSY_BEFORE_SWITCH if self._next_model() else len(BUSY_RETRIES)
        busy = 0
        if model not in getattr(self, "_announced", set()):
            self._announced = getattr(self, "_announced", set()) | {model}
            self._say(f"Превеждам с „{model}“…")
        for attempt in range(len(BUSY_RETRIES) + 1):
            self.limiter.wait()
            try:
                resp = self._client.models.generate_content(model=model, contents=user, config=config)
                return resp.text or ""
            except Exception as e:
                quota, code = _is_quota_error(e), _code(e)
                if _is_timeout(e):
                    if self._next_model():
                        raise _ModelUnavailable(f"„{model}“ не отговори за {REQUEST_TIMEOUT_S} с.") from e
                    code = 503  # last model: treat like a busy reply and retry
                if code == 404:
                    raise _ModelUnavailable(f"Моделът „{model}“ не е наличен за този ключ.") from e
                if not quota and code != 503:
                    raise
                if quota and "PerDay" in str(e):  # daily quota: waiting minutes will not help
                    if self._next_model():  # each model has its own daily quota
                        raise _ModelUnavailable(f"Дневният лимит на „{model}“ е изчерпан.") from e
                    raise QuotaExceeded(str(e)) from e
                if code == 503 and not quota:
                    if busy >= busy_limit:
                        raise _ModelUnavailable(f"Моделът „{model}“ е претоварен.") from e
                    busy += 1
                elif attempt == len(BUSY_RETRIES):
                    raise QuotaExceeded(str(e)) from e
                delay = BUSY_RETRIES[attempt]
                why = "лимитът на минута е достигнат" if quota else f"„{model}“ е претоварен"
                self._say(f"{why}, чакам {delay} с и опитвам пак...")
                (getattr(self, "_sleep", None) or _wait)(delay)
        raise _ModelUnavailable(f"Моделът „{model}“ не отговаря.")
