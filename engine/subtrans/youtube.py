"""YouTube caption text via youtube-transcript-api (unofficial). Never downloads video or audio."""

import re
from urllib.parse import parse_qs, urlparse

from .models import Cue

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
NO_CAPTIONS = "Този клип няма субтитри на език „{lang}“. Опитай с друг клип."


class NoCaptions(Exception):
    pass


def parse_video_id(url_or_id: str) -> str:
    """Video id from watch, youtu.be, shorts, embed and live URLs, or a bare 11-char id."""
    s = url_or_id.strip()
    if _ID_RE.match(s):
        return s
    u = urlparse(s if "://" in s else "https://" + s)
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    candidate = None
    if host == "youtu.be":
        candidate = u.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com") or host == "youtube-nocookie.com":
        parts = [p for p in u.path.split("/") if p]
        if parts[:1] == ["watch"]:
            candidate = parse_qs(u.query).get("v", [None])[0]
        elif len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
            candidate = parts[1]
    if candidate and _ID_RE.match(candidate):
        return candidate
    raise ValueError(f"Не мога да разпозная YouTube линка: {url_or_id}")


def snippets_to_cues(snippets, generated: bool) -> list[Cue]:
    """Snippets have .text/.start/.duration. Auto captions overlap, so end = min(start+dur, next start).

    Auto captions also repeat the same line back to back; those are merged into one longer cue.
    """
    items = [s for s in snippets if s.text.strip()]
    spans = []
    for i, s in enumerate(items):
        text, end = s.text.strip(), s.start + s.duration
        if generated and i + 1 < len(items):
            end = min(end, items[i + 1].start)
        if generated and spans and spans[-1][2].casefold() == text.casefold():
            spans[-1][1] = max(spans[-1][1], end)
            continue
        spans.append([s.start, end, text])
    return [Cue(i + 1, round(start, 3), round(end, 3), text) for i, (start, end, text) in enumerate(spans)]


def fetch_captions(video_id: str, lang: str = "en", api=None) -> tuple[list[Cue], bool]:
    """Return (cues, is_auto_generated). Prefers manually created captions."""
    from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, YouTubeTranscriptApi
    api = api or YouTubeTranscriptApi()
    try:
        listing = api.list(video_id)
    except TranscriptsDisabled as e:
        raise NoCaptions(NO_CAPTIONS.format(lang=lang)) from e
    for finder, generated in ((listing.find_manually_created_transcript, False),
                              (listing.find_generated_transcript, True)):
        try:
            transcript = finder([lang])
        except NoTranscriptFound:
            continue
        return snippets_to_cues(transcript.fetch(), generated), generated
    raise NoCaptions(NO_CAPTIONS.format(lang=lang))
