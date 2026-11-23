"""Gemini key handling (--api-key / GEMINI_API_KEY), default provider, [Музика] and caption dedupe.

No network: the google-genai SDK is replaced with a fake module.
"""

import json
import sys
import types
from types import SimpleNamespace as S

import pytest

from subtrans import cli
from subtrans.models import Cue
from subtrans.providers import get_provider
from subtrans.providers.gemini import GeminiProvider
from subtrans.translate import Translator, normalize_tags
from subtrans.youtube import snippets_to_cues

KEY = "dummy-test-key-123"  # made-up


@pytest.fixture
def fake_genai(monkeypatch):
    """Install a fake `google.genai` whose Client records the key and answers like Gemini."""
    created = []

    class Client:
        def __init__(self, api_key):
            self.api_key, self.models = api_key, self
            created.append(self)

        def generate_content(self, model, contents, config):
            cues = json.loads(contents)["cues"]
            return S(text=json.dumps([{"id": c["id"], "text": "BG " + c["text"]} for c in cues]))

    genai = types.ModuleType("google.genai")
    genai.Client = Client
    google = types.ModuleType("google")
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    return created


def test_key_from_option(fake_genai):
    p = get_provider("gemini", api_key=KEY)
    assert isinstance(p, GeminiProvider) and fake_genai[0].api_key == KEY


def test_key_from_env(fake_genai, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    get_provider("gemini")
    assert fake_genai[0].api_key == KEY


def test_option_wins_over_env(fake_genai, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    get_provider("gemini", api_key=KEY)
    assert fake_genai[0].api_key == KEY


def test_missing_key_points_to_ollama(fake_genai):
    with pytest.raises(ValueError, match="--provider ollama"):
        get_provider("gemini")
    assert fake_genai == []


def test_default_provider(monkeypatch):
    assert cli.default_provider() == "ollama"  # works with no key at all
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    assert cli.default_provider() == "gemini"
    monkeypatch.setenv("SUBTRANS_PROVIDER", "ollama")
    assert cli.default_provider() == "ollama"


def test_cli_api_key_end_to_end(fake_genai, tmp_path, capsys):
    src = tmp_path / "clip.srt"
    src.write_text("1\n00:00:01,000 --> 00:00:02,000\nhello\n", encoding="utf-8")
    assert cli.main(["translate-srt", str(src), "--provider", "gemini", "--api-key", KEY, "--rpm", "10000"]) == 0
    events = [json.loads(ln) for ln in capsys.readouterr().out.splitlines()]
    assert events[-1]["event"] == "done" and events[-1]["cues"][0]["tgt"] == "BG hello"
    assert fake_genai[0].api_key == KEY
    assert KEY not in json.dumps(events)
    assert KEY not in "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "cache").rglob("*") if p.is_file())


def test_cli_error_never_echoes_key(monkeypatch, tmp_path, capsys):
    def boom(*a):
        raise RuntimeError(f"bad key {KEY}")
    monkeypatch.setattr(cli, "get_provider", boom)
    src = tmp_path / "clip.srt"
    src.write_text("1\n00:00:01,000 --> 00:00:02,000\nhello\n", encoding="utf-8")
    assert cli.main(["translate-srt", str(src), "--provider", "gemini", "--api-key", KEY]) == 1
    assert KEY not in capsys.readouterr().out


@pytest.mark.parametrize("raw", ["[music]", "[Music]", "[ MUSIC ]", "[музика]"])
def test_music_tag_normalized(raw):
    assert normalize_tags(f"боксьор, {raw} какъв", "bg") == "боксьор, [Музика] какъв"
    assert normalize_tags(raw, "de") == raw


def test_translator_applies_music_tag():
    class Echo:
        def complete(self, system, user):
            return json.dumps([{"id": c["id"], "text": "[music] " + c["text"]} for c in json.loads(user)["cues"]])
    out = Translator(Echo(), "en", "bg").translate([Cue(1, 0.0, 1.0, "hi")])
    assert out[0].text == "[Музика] hi"


def test_repeated_auto_caption_lines_are_merged():
    snips = [S(text="made-up one", start=0.0, duration=3.0), S(text="made-up one", start=2.0, duration=3.0),
             S(text="Made-up one ", start=4.0, duration=2.0), S(text="made-up two", start=6.0, duration=1.0)]
    assert snippets_to_cues(snips, generated=True) == [
        Cue(1, 0.0, 6.0, "made-up one"), Cue(2, 6.0, 7.0, "made-up two")]
    assert len(snippets_to_cues(snips, generated=False)) == 4  # manual captions are left alone


class _ApiErr(Exception):
    extra = ""

    def __init__(self, code):
        super().__init__(f"{code} error {_ApiErr.extra}")
        self.code = code


def _gemini_with(errors, message=""):
    """Provider whose fake client raises the given error codes first, then answers."""
    from subtrans.throttle import RateLimiter
    calls = []

    def generate_content(model, contents, config):
        calls.append(model)
        if errors:
            raise _ApiErr(errors.pop(0))
        return S(text='[{"id": 1, "text": "здрасти"}]')
    client = S(models=S(generate_content=generate_content))
    slept = []
    p = GeminiProvider("gemini-x", 10_000, 10_000, client=client,
                       limiter=RateLimiter(10_000, 10_000, sleep=lambda s: None), sleep=slept.append)
    return p, calls, slept


def test_busy_model_is_retried():
    p, calls, slept = _gemini_with([503, 429, 503])
    waits = []
    p.on_wait = waits.append
    assert "здрасти" in p.complete("SYS", "{}")
    assert len(calls) == 4 and slept == [5, 10, 20]
    assert "претоварен" in waits[0] and "лимитът на минута" in waits[1] and "(3/5)" in waits[2]


def test_daily_quota_is_not_retried(monkeypatch):
    from subtrans.providers import QuotaExceeded
    monkeypatch.setattr(_ApiErr, "extra", "GenerateRequestsPerDay")
    p, calls, slept = _gemini_with([429])
    with pytest.raises(QuotaExceeded):
        p.complete("SYS", "{}")
    assert len(calls) == 1 and slept == []


def test_minute_limit_becomes_quota_after_retries():
    from subtrans.providers import QuotaExceeded
    p, calls, _ = _gemini_with([429] * 6)
    with pytest.raises(QuotaExceeded):
        p.complete("SYS", "{}")
    assert len(calls) == 6


def test_busy_model_gives_up_with_hint():
    p, calls, _ = _gemini_with([503] * 6)
    with pytest.raises(RuntimeError, match="--model gemini-3.5-flash-lite"):
        p.complete("SYS", "{}")


def test_unknown_model_gives_hint():
    p, calls, _ = _gemini_with([404])
    with pytest.raises(RuntimeError, match="gemini-x.*--model gemini-3.5-flash-lite"):
        p.complete("SYS", "{}")
    assert len(calls) == 1


def test_model_option_reaches_gemini(fake_genai):
    p = get_provider("gemini", "gemini-3.8-flash", api_key=KEY)
    assert p.model == "gemini-3.8-flash"
