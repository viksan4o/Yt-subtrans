"""Google Gemini through the google-genai SDK, using the user's own API key."""

import math
import os
import queue
import threading
import time

from ..throttle import RateLimiter
from .base import QuotaExceeded, TranslationProvider


# Best first. Tried in this order when a model is unknown for the key (404), busy (503), silent,
# or out of its own daily quota (quotas are per model). Flash-lite translated into Bulgarian with
# invented words in real clips (Nov 2026), so it is only the last resort.
FALLBACK_MODELS = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
                   "gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
# Seconds to wait before each retry of the same model after a per-minute limit (429), or while
# no other model is left. After the last one a 429 counts as the daily quota (progress is kept).
BUSY_RETRIES = (5, 10, 20, 40, 60)
# No first piece of the answer within this many seconds: switch to the next model at once.
# Overloaded models can hang for minutes (seen Nov 2026); with low thinking a healthy flash model
# starts answering in about 5 s.
FIRST_REPLY_TIMEOUT_S = float(os.environ.get("GEMINI_FIRST_REPLY_TIMEOUT") or 10)
# Limit for the whole answer once it has started.
REQUEST_TIMEOUT_S = int(os.environ.get("GEMINI_TIMEOUT") or 120)
# A busy or silent model is skipped for this long; after that the next batch tries it again,
# so the best model is used again as soon as it is free.
COOLDOWN_S = float(os.environ.get("GEMINI_COOLDOWN") or 30)


class _ModelUnavailable(Exception):
    """args: (message, temporary). Temporary problems end after COOLDOWN_S."""


class _NoFirstReply(Exception):
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
                 fallbacks: tuple[str, ...] = FALLBACK_MODELS, clock=time.monotonic):
        self.model, self._sleep, self._clock = model, sleep, clock
        self.order = [model] + [m for m in fallbacks if m != model]  # best first
        self._blocked: dict[str, float] = {}  # model -> skipped until this clock time (inf = for good)
        self._no_thinking: set[str] = set()  # models that refused the thinking setting
        self.on_wait = None  # optional callback(message) shown while waiting or switching
        self._rpm, self._rpd = rpm, rpd
        self._limiters: dict[str, RateLimiter] = {}  # Google counts the limits per model
        self._shared_limiter = limiter
        if client is None:
            key = api_key or os.environ.get("GEMINI_API_KEY")
            if not key:
                raise ValueError("Липсва Gemini API ключ. Задай GEMINI_API_KEY или подай --api-key. "
                                 "Без ключ ползвай локалния модел: --provider ollama")
            from google import genai  # imported lazily so tests and other providers do not need it
            client = genai.Client(api_key=key, http_options={"timeout": REQUEST_TIMEOUT_S * 1000})
        self._client = client

    def _say(self, message: str) -> None:
        if self.on_wait:
            self.on_wait(message)

    def _limiter(self, model: str) -> RateLimiter:
        if self._shared_limiter:
            return self._shared_limiter
        if model not in self._limiters:
            self._limiters[model] = RateLimiter(self._rpm, self._rpd)
            self._limiters[model].on_wait = self._say
        return self._limiters[model]

    def _available(self) -> list[str]:
        now = self._clock()
        return [m for m in self.order if self._blocked.get(m, 0) <= now]

    def complete(self, system: str, user: str) -> str:
        best = (self._available() or [self.model])[0]
        if best != self.model:
            if self.order.index(best) < self.order.index(self.model):
                self._say(f"„{best}“ е свободен отново, връщам се на него.")
            self.model = best
        self._say(f"Превеждам с „{self.model}“…")
        while True:
            try:
                return self._complete_with(self.model, system, user)
            except _ModelUnavailable as e:
                message, temporary = e.args
                self._blocked[self.model] = self._clock() + COOLDOWN_S if temporary else math.inf
                rest = self._available()
                if not rest:
                    raise RuntimeError(f"{message} Няма друг наличен Gemini модел. Напредъкът е запазен: "
                                       "опитай пак по-късно (list-models показва моделите).") from e
                self._say(f"{message} Минавам на „{rest[0]}“.")
                self.model = rest[0]

    def _request(self, model: str, system: str, user: str) -> str:
        config = {"system_instruction": system, "response_mime_type": "application/json", "temperature": 0.3}
        if model not in self._no_thinking:
            config["thinking_config"] = {"thinking_level": "LOW"}  # answers start in ~5 s instead of 15
        models = self._client.models
        if not hasattr(models, "generate_content_stream"):  # simple clients (tests)
            return models.generate_content(model=model, contents=user, config=config).text or ""
        # Stream in a worker thread so we can give up when the first piece is late.
        pieces: queue.Queue = queue.Queue()

        def work():
            try:
                for chunk in models.generate_content_stream(model=model, contents=user, config=config):
                    pieces.put(("text", chunk.text or ""))
                pieces.put(("end", None))
            except Exception as e:  # handed over to the caller
                pieces.put(("error", e))

        threading.Thread(target=work, daemon=True).start()
        text: list[str] = []
        timeout, deadline = FIRST_REPLY_TIMEOUT_S, time.monotonic() + REQUEST_TIMEOUT_S
        while True:
            try:
                kind, value = pieces.get(timeout=max(0.1, timeout))
            except queue.Empty:
                raise (_NoFirstReply() if not text else TimeoutError("the answer stopped arriving")) from None
            if kind == "end":
                return "".join(text)
            if kind == "error":
                raise value
            if value:
                text.append(value)
            if text:
                timeout = deadline - time.monotonic()

    def _complete_with(self, model: str, system: str, user: str) -> str:
        for attempt in range(len(BUSY_RETRIES) + 1):
            self._limiter(model).wait()
            try:
                return self._request(model, system, user)
            except _NoFirstReply as e:
                raise _ModelUnavailable(f"„{model}“ не отговори за {FIRST_REPLY_TIMEOUT_S:.0f} с.", True) from e
            except Exception as e:
                quota, code = _is_quota_error(e), _code(e)
                if code == 400 and "thinking" in str(e).lower() and model not in self._no_thinking:
                    self._no_thinking.add(model)  # this model has no thinking setting: ask again without
                    continue
                alone = len(self._available()) <= 1  # no other model to switch to
                if _is_timeout(e):
                    if not alone:
                        raise _ModelUnavailable(f"„{model}“ не отговори навреме.", True) from e
                    code = 503  # last model: treat like a busy reply and retry
                if code == 404:
                    raise _ModelUnavailable(f"Моделът „{model}“ не е наличен за този ключ.", False) from e
                if not quota and code != 503:
                    raise
                if quota and "PerDay" in str(e):  # daily quota: waiting minutes will not help
                    if not alone:  # each model has its own daily quota
                        raise _ModelUnavailable(f"Дневният лимит на „{model}“ е изчерпан.", False) from e
                    raise QuotaExceeded(str(e)) from e
                if code == 503 and not quota and not alone:
                    # Switch at once; this model is tried again after the cooldown.
                    raise _ModelUnavailable(f"„{model}“ е претоварен.", True) from e
                if attempt == len(BUSY_RETRIES):
                    if quota:
                        raise QuotaExceeded(str(e)) from e
                    break
                delay = BUSY_RETRIES[attempt]
                why = "лимитът на минута е достигнат" if quota else f"„{model}“ е претоварен"
                self._say(f"{why}, чакам {delay} с и опитвам пак...")
                (self._sleep or _wait)(delay)
        raise _ModelUnavailable(f"Моделът „{model}“ не отговаря.", True)
