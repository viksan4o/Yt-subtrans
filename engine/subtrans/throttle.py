"""Client-side request throttling to stay inside free-tier RPM / RPD limits."""

import time
from typing import Callable

from .providers.base import QuotaExceeded


class RateLimiter:
    """Spaces requests to at most `rpm` per minute and refuses more than `rpd` per run.

    The daily counter only covers this run; Google's own 429 reply is the final authority.
    """

    def __init__(self, rpm: int, rpd: int, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        if rpm < 1 or rpd < 1:
            raise ValueError("RPM and RPD must be >= 1")
        self.interval = 60.0 / rpm
        self.rpd = rpd
        self.clock, self.sleep = clock, sleep
        self.count = 0
        self._last: float | None = None
        self.on_wait: Callable[[str], None] | None = None  # told about long pauses


    def wait(self) -> None:
        if self.count >= self.rpd:
            raise QuotaExceeded(f"daily request limit reached ({self.rpd} RPD)")
        if self._last is not None:
            delay = self._last + self.interval - self.clock()
            if delay > 0:
                if delay >= 3 and self.on_wait:
                    self.on_wait(f"Изчаквам {delay:.0f} с заради лимита от {60 / self.interval:.0f} заявки в минута…")
                self.sleep(delay)
        self._last = self.clock()
        self.count += 1
