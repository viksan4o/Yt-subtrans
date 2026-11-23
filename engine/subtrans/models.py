"""Plain data types shared by every module."""

from dataclasses import dataclass


@dataclass
class Cue:
    """One subtitle cue. Times are in seconds."""

    id: int
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)
