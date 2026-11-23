"""Command line entry point. Prints one JSON event per line on stdout.

    python -m subtrans.cli translate-srt <file.srt> [--src en] [--tgt bg] [--provider fake] [--srt out.srt]
"""

import argparse
import json
import sys
from pathlib import Path

from .providers import get_provider
from .srt import parse_srt, write_srt
from .translate import Translator
from .wrap import chars_per_second


def emit(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def cmd_translate_srt(args) -> int:
    src_path = Path(args.file)
    cues = parse_srt(src_path.read_text(encoding="utf-8-sig"))
    glossary = json.loads(Path(args.glossary).read_text(encoding="utf-8")) if args.glossary else {}
    translator = Translator(get_provider(args.provider, args.model), args.src, args.tgt,
                            title=src_path.stem, glossary=glossary)
    emit("progress", done=0, total=len(cues))
    out = translator.translate(cues, on_progress=lambda d, t: emit("progress", done=d, total=t))
    out_path = Path(args.srt) if args.srt else src_path.with_suffix(f".{args.tgt}.srt")
    out_path.write_text(write_srt(out), encoding="utf-8")
    emit("done", srt=str(out_path), cues=[
        {"id": s.id, "start": s.start, "end": s.end, "src": s.text, "tgt": t.text,
         "cps": chars_per_second(t.text, t.start, t.end)} for s, t in zip(cues, out)])
    return 0


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy code page
    p = argparse.ArgumentParser(prog="subtrans")
    sub = p.add_subparsers(dest="command", required=True)
    t = sub.add_parser("translate-srt", help="translate a local .srt file")
    t.add_argument("file")
    t.add_argument("--src", default="en")
    t.add_argument("--tgt", default="bg")
    t.add_argument("--provider", default="fake")
    t.add_argument("--model")
    t.add_argument("--glossary")
    t.add_argument("--srt", help="output path (default: <file>.<tgt>.srt)")
    args = p.parse_args(argv)
    try:
        return cmd_translate_srt(args)
    except Exception as e:  # report every failure as a JSON event for the app
        emit("error", message=str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
