"""Parse and write SubRip (.srt) files."""

import re

from .models import Cue

_TIME = r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
_TIMING_RE = re.compile(_TIME + r"\s*-->\s*" + _TIME)


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def format_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    h, rest = divmod(total_ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(text: str) -> list[Cue]:
    """Parse SRT text. Tolerates a BOM, CRLF line endings, '.' millis and missing index lines."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.split("\n")]
        timing_idx = next((i for i, ln in enumerate(lines) if _TIMING_RE.search(ln)), None)
        if timing_idx is None:
            continue
        m = _TIMING_RE.search(lines[timing_idx])
        start = _to_seconds(*m.groups()[:4])
        end = _to_seconds(*m.groups()[4:])
        cue_id = len(cues) + 1
        if timing_idx > 0 and lines[timing_idx - 1].strip().isdigit():
            cue_id = int(lines[timing_idx - 1].strip())
        body = "\n".join(ln.rstrip() for ln in lines[timing_idx + 1:]).strip()
        cues.append(Cue(id=cue_id, start=start, end=end, text=body))
    return cues


def write_srt(cues: list[Cue]) -> str:
    """Serialise cues to SRT text (cues are renumbered 1..N in the given order)."""
    out = []
    for n, cue in enumerate(cues, start=1):
        out.append(f"{n}\n{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}\n{cue.text}\n")
    return "\n".join(out)
