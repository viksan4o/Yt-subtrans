"""Line wrapping and reading-speed checks for subtitles."""

import math

MAX_LINE = 42
MAX_CPS = 21.0


def _split_long_word(word: str, width: int) -> list[str]:
    return [word[i:i + width] for i in range(0, len(word), width)]


def _balanced(words: list[str], n_lines: int) -> list[str] | None:
    """Split words into exactly n_lines lines minimising the longest line (DP)."""
    n = len(words)
    if n_lines > n:
        return None
    lens = [len(w) for w in words]

    def width(i: int, j: int) -> int:  # words[i:j] joined by spaces
        return sum(lens[i:j]) + (j - i - 1)

    # best[k][j]: minimal max-width splitting words[:j] into k lines; tie-break by sum of squares
    INF = (math.inf, math.inf)
    best = [[INF] * (n + 1) for _ in range(n_lines + 1)]
    back = [[0] * (n + 1) for _ in range(n_lines + 1)]
    best[0][0] = (0, 0)
    for k in range(1, n_lines + 1):
        for j in range(k, n + 1):
            for i in range(k - 1, j):
                if best[k - 1][i] == INF:
                    continue
                w = width(i, j)
                cand = (max(best[k - 1][i][0], w), best[k - 1][i][1] + w * w)
                if cand < best[k][j]:
                    best[k][j] = cand
                    back[k][j] = i
    if best[n_lines][n] == INF:
        return None
    lines, j = [], n
    for k in range(n_lines, 0, -1):
        i = back[k][j]
        lines.append(" ".join(words[i:j]))
        j = i
    return lines[::-1]


def wrap_text(text: str, max_len: int = MAX_LINE) -> str:
    """Wrap subtitle text into balanced lines of at most `max_len` chars. Never drops text.

    Existing line breaks are kept when every line already fits (e.g. two-speaker dialogue).
    """
    lines = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
    if not lines:
        return ""
    if all(len(ln) <= max_len for ln in lines):
        return "\n".join(" ".join(ln.split()) for ln in lines)
    words: list[str] = []
    for w in " ".join(lines).split():
        words.extend(_split_long_word(w, max_len) if len(w) > max_len else [w])
    total = len(" ".join(words))
    n_lines = max(1, math.ceil(total / max_len))
    while True:
        result = _balanced(words, n_lines)
        if result is not None and all(len(ln) <= max_len for ln in result):
            return "\n".join(result)
        n_lines += 1


def chars_per_second(text: str, start: float, end: float) -> float:
    """Reading speed: visible characters (line breaks excluded) per second."""
    chars = len(text.replace("\n", ""))
    duration = end - start
    if duration <= 0:
        return float("inf") if chars else 0.0
    return round(chars / duration, 1)


def too_fast(cps: float, limit: float = MAX_CPS) -> bool:
    return cps > limit
