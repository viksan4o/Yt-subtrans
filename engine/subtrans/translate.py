"""Prompt building, response validation and batch translation with retry/split fallback."""

import difflib
import json
import re
from typing import Callable

from .chunking import DEFAULT_BATCH_SIZE, DEFAULT_CONTEXT_SIZE, make_batches
from .models import Cue
from .providers.base import TranslationProvider
from .wrap import wrap_text

LANGUAGE_NAMES = {"en": "English", "bg": "Bulgarian", "de": "German", "es": "Spanish",
                  "fr": "French", "it": "Italian", "ru": "Russian"}

SYSTEM_TEMPLATE = """You translate subtitle cues from {source} to {target}.
Rules:
- Output JSON only: a list of {{"id": n, "src": "...", "text": "..."}} with exactly one item per input cue, the same ids, no merged or split cues. "src" is that cue's source text copied exactly; "text" is its translation.
- Cues are often fragments of a sentence that continues in the next cue. Each "text" must translate ONLY the words of its own "src": never pull words from the next cue or push them into the previous one, even if {target} word order differs. Split the translated sentence at the matching point so every cue stays in sync with its timing.
- Exactly ONE translation per cue. No notes, no variants, no transliteration or pronunciation.
- Translate slang and idioms by meaning, using a real equivalent in {target}. If you do not know a genuine idiom, use plain neutral language. NEVER invent an idiom and never translate an idiom word for word.
- Keep the speaker's tone and the intensity of profanity. No asterisk censoring; do not soften or intensify.
- Gaming slang: "sweat"/"sweaty" means a try-hard player (Bulgarian: "потен").
- Follow the glossary for slang and proper names, and keep names consistent.
- Keep terminology consistent: once a thing has a {target} name (see the context translations), reuse exactly that word and grammatical gender everywhere.
- Use the informal "ти" form by default. Render [Music] as [Музика] when translating into Bulgarian.
- Keep each line short enough to read as a subtitle.
The input is JSON with: title, glossary, context (previous cues as src/tgt pairs, read-only, do not output them) and cues (translate these)."""

MAX_ATTEMPTS = 3  # first try + 2 retries

_MUSIC_RE = re.compile(r"\[\s*(?:music|музика)\s*\]", re.IGNORECASE)


def normalize_tags(text: str, target: str) -> str:
    """Spec: sound tags in Bulgarian output are written [Музика], whatever the model returned."""
    return _MUSIC_RE.sub("[Музика]", text) if target == "bg" else text


class ValidationError(Exception):
    pass


class TranslationError(Exception):
    pass


def lang_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


def build_system_prompt(source: str, target: str) -> str:
    return SYSTEM_TEMPLATE.format(source=lang_name(source), target=lang_name(target))


def build_user_payload(cues: list[Cue], context: list[tuple[str, str]], title: str = "",
                       glossary: dict | None = None) -> str:
    return json.dumps({
        "title": title,
        "glossary": glossary or {},
        "context": [{"src": s, "tgt": t} for s, t in context],
        "cues": [{"id": c.id, "text": c.text} for c in cues],
    }, ensure_ascii=False)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def src_matches(echo: str, source: str) -> bool:
    """True when the model's copy of a cue's source text is (nearly) that cue's text."""
    a, b = _norm(echo), _norm(source)
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def parse_response(raw: str, expected_ids: list[int], sources: dict[int, str] | None = None) -> dict[int, str]:
    """Parse the model reply; tolerate ``` fences. Raise ValidationError on any mismatch.

    When `sources` is given, an item's optional "src" echo must match that cue's source text, so a
    reply whose translations slid onto neighbouring cues is rejected and retried.
    """
    text = raw.strip()
    fence = re.match(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```$", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValidationError(f"invalid JSON: {e}") from e
    if isinstance(data, dict) and "id" in data and "text" in data:  # single cue without a list
        data = [data]
    elif isinstance(data, dict):  # accept {"cues": [...]} style wrappers, even if the input is echoed
        lists = [v for v in data.values() if isinstance(v, list) and v]
        data = data.get("cues") if isinstance(data.get("cues"), list) else (lists[0] if lists else None)
    if not isinstance(data, list):
        raise ValidationError("expected a JSON list")
    result: dict[int, str] = {}
    for item in data:
        if not isinstance(item, dict) or "id" not in item or not isinstance(item.get("text"), str):
            raise ValidationError(f"bad item: {item!r}")
        if not item["text"].strip():
            raise ValidationError(f"empty text for id {item['id']}")
        try:
            cue_id = int(item["id"])
        except (TypeError, ValueError) as e:
            raise ValidationError(f"bad id: {item['id']!r}") from e
        echo = item.get("src")
        if sources and isinstance(echo, str) and cue_id in sources and not src_matches(echo, sources[cue_id]):
            raise ValidationError(f"cue {cue_id} out of sync: src {echo!r} != {sources[cue_id]!r}")
        result[cue_id] = item["text"].strip()
    if len(data) != len(expected_ids) or set(result) != set(expected_ids):
        raise ValidationError(f"ids mismatch: expected {sorted(expected_ids)}, got {sorted(result)}")
    return result


class Translator:
    def __init__(self, provider: TranslationProvider, source: str = "en", target: str = "bg",
                 title: str = "", glossary: dict | None = None,
                 batch_size: int = DEFAULT_BATCH_SIZE, context_size: int = DEFAULT_CONTEXT_SIZE):
        self.provider = provider
        self.system = build_system_prompt(source, target)
        self.target = target
        self.title = title
        self.glossary = glossary or {}
        self.batch_size = batch_size
        self.context_size = context_size

    def _context_pairs(self, ctx: list[Cue], done: dict[int, str]) -> list[tuple[str, str]]:
        return [(c.text, done.get(c.id, "")) for c in ctx]

    def translate_batch(self, cues: list[Cue], context: list[Cue], done: dict[int, str]) -> dict[int, str]:
        """Translate one batch: retry twice, then split in half and recurse."""
        ids = [c.id for c in cues]
        last_error = None
        for _ in range(MAX_ATTEMPTS):
            payload = build_user_payload(cues, self._context_pairs(context, done), self.title, self.glossary)
            try:
                return parse_response(self.provider.complete(self.system, payload), ids,
                                      {c.id: c.text for c in cues})
            except ValidationError as e:
                last_error = e
        if len(cues) == 1:
            raise TranslationError(f"Репликата с id {cues[0].id} не можа да бъде преведена: {last_error}")
        mid = len(cues) // 2
        first = self.translate_batch(cues[:mid], context, done)
        merged = {**done, **first}
        second_ctx = (context + cues[:mid])[-self.context_size:] if self.context_size else []
        second = self.translate_batch(cues[mid:], second_ctx, merged)
        return {**first, **second}

    def translate(self, cues: list[Cue],
                  on_progress: Callable[[int, int], None] | None = None,
                  done: dict[int, str] | None = None,
                  on_batch: Callable[[dict[int, str]], None] | None = None) -> list[Cue]:
        """Translate all cues; returns new cues with wrapped target text and identical timings.

        `done` holds translations from an earlier run; batches already fully translated are skipped.
        `on_batch` is called after every finished batch (used to save progress). A QuotaExceeded
        from the provider is not retried: it propagates so the caller can stop and resume later.
        """
        done = dict(done or {})
        for batch in make_batches(cues, self.batch_size, self.context_size):
            if all(c.id in done for c in batch.cues):
                continue
            result = self.translate_batch(batch.cues, batch.context, done)
            done.update({i: normalize_tags(t, self.target) for i, t in result.items()})
            if on_batch:
                on_batch(done)
            if on_progress:
                on_progress(sum(c.id in done for c in cues), len(cues))
        return [Cue(c.id, c.start, c.end, wrap_text(done[c.id])) for c in cues]
