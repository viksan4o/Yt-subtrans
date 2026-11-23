# BG Subs (work in progress)

Translates YouTube subtitles into Bulgarian. MIT license. This is the first small slice:
the engine core only, with an offline `fake` provider (no API key, no network).

## Try it (Windows)

```
cd engine
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m pytest
python -m subtrans.cli translate-srt sample.srt
```

This writes `sample.bg.srt` with the same timings, lines wrapped at 42 characters,
and prints JSON progress events. The `fake` provider only prefixes text with `[BG]`;
the real Gemini provider comes in the next step.
