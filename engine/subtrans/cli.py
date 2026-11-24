"""Command line entry point. Prints one JSON event per line on stdout.

    python -m subtrans.cli translate <url_or_id> [options]
    python -m subtrans.cli translate-srt <file.srt> [options]
    python -m subtrans.cli list-models [--api-key KEY]   (Gemini models usable with your key)

Options: --src en --tgt bg --provider gemini|claude|ollama|fake --model NAME --rpm N --rpd N
         --api-key KEY --glossary file.json --srt out.srt --fresh (ignore saved progress)
Default provider: SUBTRANS_PROVIDER, else gemini when GEMINI_API_KEY is set, else ollama (no key).
API keys come only from the environment/.env or --api-key; they are never cached or printed.
Progress is cached per (video_id, source, target, provider, model): re-running resumes,
and a finished run is served from the cache without new requests.
"""

import argparse
import dataclasses
import hashlib
import json
import os
import sys
from pathlib import Path

from .cache import TranslationCache
from .config import claude_settings, gemini_settings, load_dotenv, ollama_settings
from .models import Cue
from .providers import QuotaExceeded, get_provider
from .srt import parse_srt, write_srt
from .translate import Translator
from .wrap import chars_per_second, wrap_text

QUOTA_MESSAGE = "Дневният лимит е изчерпан. Продължи утре или смени модела."


def emit(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def default_provider() -> str:
    """Works out of the box without any key: Gemini only when a key is configured."""
    return os.environ.get("SUBTRANS_PROVIDER") or ("gemini" if os.environ.get("GEMINI_API_KEY") else "ollama")


def model_name(provider: str, model: str | None) -> str:
    """Model id for the cache key, known without building the provider (so no key is needed)."""
    settings = {"gemini": gemini_settings, "claude": claude_settings, "ollama": ollama_settings}.get(provider)
    return settings(model)["model"] if settings else (model or provider)


def run(args, video_id: str, title: str, load_cues, default_out: Path) -> int:
    cache = TranslationCache(video_id, args.src, args.tgt, args.provider, model_name(args.provider, args.model))
    done = {} if getattr(args, "fresh", False) else cache.load()
    if getattr(args, "fresh", False):
        cache.cues = []
    if cache.cues:
        cues = [Cue(**c) for c in cache.cues]
    else:
        cues = load_cues()
        cache.cues = [dataclasses.asdict(c) for c in cues]
    used_model = model_name(args.provider, args.model)
    emit("progress", done=sum(c.id in done for c in cues), total=len(cues))
    if cache.complete and all(c.id in done for c in cues):
        out = [Cue(c.id, c.start, c.end, wrap_text(done[c.id])) for c in cues]
    else:
        glossary = json.loads(Path(args.glossary).read_text(encoding="utf-8")) if args.glossary else {}
        provider = get_provider(args.provider, args.model, args.rpm, args.rpd, args.api_key)
        if hasattr(provider, "on_wait"):
            provider.on_wait = lambda message: emit("waiting", message=message)
        extra = {"batch_size": provider.batch_size} if getattr(provider, "batch_size", None) else {}
        translator = Translator(provider, args.src, args.tgt, title=title, glossary=glossary, **extra)
        translator.on_notice = lambda message: emit("waiting", message=message)
        try:
            out = translator.translate(cues, on_progress=lambda d, t: emit("progress", done=d, total=t),
                                       done=done, on_batch=cache.save)
        except QuotaExceeded:
            emit("quota", message=QUOTA_MESSAGE)
            return 2
        cache.save({c.id: t.text for c, t in zip(cues, out)}, complete=True)
        used_model = getattr(provider, "model", used_model)  # a fallback model may have taken over
    out_path = Path(args.srt) if args.srt else default_out
    out_path.write_text(write_srt(out), encoding="utf-8")
    emit("done", srt=str(out_path), provider=args.provider, model=used_model, cues=[
        {"id": s.id, "start": s.start, "end": s.end, "src": s.text, "tgt": t.text,
         "cps": chars_per_second(t.text, t.start, t.end)} for s, t in zip(cues, out)])
    return 0


def cmd_translate_srt(args) -> int:
    src_path = Path(args.file)
    raw = src_path.read_text(encoding="utf-8-sig")
    video_id = "srt-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]  # local files: content hash
    return run(args, video_id, src_path.stem, lambda: parse_srt(raw), src_path.with_suffix(f".{args.tgt}.srt"))


def cmd_translate(args, fetch=None) -> int:
    from .youtube import fetch_captions, parse_video_id
    video_id = parse_video_id(args.url)
    fetch = fetch or fetch_captions
    return run(args, video_id, video_id, lambda: fetch(video_id, args.src)[0],
               Path(f"{video_id}.{args.tgt}.srt"))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="subtrans")
    sub = p.add_subparsers(dest="command", required=True)
    for name, arg, help_ in (("translate", "url", "translate the captions of a YouTube clip"),
                             ("translate-srt", "file", "translate a local .srt file")):
        t = sub.add_parser(name, help=help_)
        t.add_argument(arg)
        t.add_argument("--src", default="en")
        t.add_argument("--tgt", default="bg")
        t.add_argument("--provider", choices=["gemini", "claude", "ollama", "fake"],
                       help="default: SUBTRANS_PROVIDER, else gemini if GEMINI_API_KEY is set, else ollama")
        t.add_argument("--model")
        t.add_argument("--rpm", type=int, help="requests per minute (Gemini)")
        t.add_argument("--rpd", type=int, help="requests per day (Gemini)")
        t.add_argument("--api-key", help="key for gemini/claude (default: GEMINI_API_KEY / ANTHROPIC_API_KEY)")
        t.add_argument("--glossary")
        t.add_argument("--srt", help="output .srt path")
        t.add_argument("--fresh", action="store_true", help="ignore saved progress and translate again")
    lm = sub.add_parser("list-models", help="list the Gemini models your key can use")
    lm.add_argument("--api-key")
    return p


def cmd_list_models(args, client=None) -> int:
    from .providers.gemini import list_models
    emit("models", models=list_models(args.api_key, client=client))
    return 0


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy code page
    args = build_parser().parse_args(argv)
    load_dotenv()
    try:
        if args.command == "list-models":
            return cmd_list_models(args)
        args.provider = args.provider or default_provider()
        return cmd_translate(args) if args.command == "translate" else cmd_translate_srt(args)
    except Exception as e:  # report every failure as a JSON event for the app
        message = str(e)
        if args.api_key:  # never echo a key passed on the command line
            message = message.replace(args.api_key, "***")
        emit("error", message=message)
        return 1


if __name__ == "__main__":
    sys.exit(main())
