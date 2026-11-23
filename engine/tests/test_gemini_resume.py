"""Gemini provider, throttling, 429 handling and cache/resume. No real network calls."""

import json

import pytest

from subtrans import cli
from subtrans.cache import TranslationCache, cache_key
from subtrans.config import gemini_settings, load_dotenv
from subtrans.models import Cue
from subtrans.providers import QuotaExceeded
from subtrans.providers.gemini import GeminiProvider
from subtrans.throttle import RateLimiter
from subtrans.translate import Translator


class FakeClock:
    def __init__(self):
        self.t, self.slept = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 3))
        self.t += s


def test_rate_limiter_spaces_requests_and_caps_per_day():
    clock = FakeClock()
    lim = RateLimiter(rpm=6, rpd=3, clock=clock, sleep=clock.sleep)
    lim.wait(); lim.wait(); clock.t += 4; lim.wait()
    assert clock.slept == [10.0, 6.0]
    with pytest.raises(QuotaExceeded):
        lim.wait()


class _Resp:
    def __init__(self, text):
        self.text = text


class _Err(Exception):
    def __init__(self, code):
        super().__init__(f"{code} RESOURCE_EXHAUSTED GenerateRequestsPerDay" if code == 429 else str(code))
        self.code = code


class FakeGenAIClient:
    """Mimics client.models.generate_content; fails with 429 after `ok_calls` successful calls."""

    def __init__(self, ok_calls=99, error_code=429):
        self.models, self.ok_calls, self.error_code, self.requests = self, ok_calls, error_code, []

    def generate_content(self, model, contents, config):
        self.requests.append((model, config))
        if len(self.requests) > self.ok_calls:
            raise _Err(self.error_code)
        cues = json.loads(contents)["cues"]
        return _Resp(json.dumps([{"id": c["id"], "text": "BG " + c["text"]} for c in cues]))


def _provider(client):
    clock = FakeClock()
    return GeminiProvider("test-model", 60, 1000, client=client,
                          limiter=RateLimiter(60, 1000, clock=clock, sleep=clock.sleep))


def test_gemini_provider_sends_system_prompt_and_maps_429():
    client = FakeGenAIClient(ok_calls=1)
    prov = _provider(client)
    out = prov.complete("SYS", json.dumps({"cues": [{"id": 1, "text": "hi"}]}))
    assert json.loads(out) == [{"id": 1, "text": "BG hi"}]
    model, config = client.requests[0]
    assert model == "test-model" and config["system_instruction"] == "SYS"
    with pytest.raises(QuotaExceeded):
        prov.complete("SYS", json.dumps({"cues": [{"id": 1, "text": "hi"}]}))


def test_gemini_other_errors_are_not_quota():
    prov = _provider(FakeGenAIClient(ok_calls=0, error_code=500))
    with pytest.raises(_Err):
        prov.complete("SYS", json.dumps({"cues": []}))


def test_missing_key_gives_clear_bulgarian_error():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiProvider("m", 5, 20)


def test_settings_defaults_env_and_dotenv(tmp_path, monkeypatch):
    assert gemini_settings() == {"model": "gemini-3.5-flash-lite", "rpm": 15, "rpd": 500}
    (tmp_path / ".env").write_text("GEMINI_PRESET=quality\nGEMINI_RPM=9\n", encoding="utf-8")
    load_dotenv(tmp_path / ".env")
    assert gemini_settings() == {"model": "gemini-3.8-flash", "rpm": 9, "rpd": 20}
    assert gemini_settings(model="custom", rpd=7)["model"] == "custom"


def test_cache_keying(tmp_path):
    base = ("vid", "en", "bg", "gemini", "m1")
    assert cache_key(*base) == cache_key(*base)
    for i, other in enumerate(["vid2", "de", "de", "fake", "m2"]):
        changed = list(base); changed[i] = other
        assert cache_key(*changed) != cache_key(*base)
    c = TranslationCache(*base, root=tmp_path)
    c.save({1: "а", 2: "б"})
    assert TranslationCache(*base, root=tmp_path).load() == {1: "а", 2: "б"}
    assert TranslationCache("vid", "en", "bg", "gemini", "m2", root=tmp_path).load() == {}


def test_429_saves_progress_and_second_run_resumes(tmp_path):
    cues = [Cue(i, i, i + 1, f"line {i}") for i in range(1, 7)]
    cache = TranslationCache("vid", "en", "bg", "gemini", "test-model", root=tmp_path)

    first = FakeGenAIClient(ok_calls=1)
    with pytest.raises(QuotaExceeded):
        Translator(_provider(first), batch_size=2).translate(cues, done=cache.load(), on_batch=cache.save)
    assert len(first.requests) == 2  # one success, then a single 429 with no retry hammering
    assert cache.load() == {1: "BG line 1", 2: "BG line 2"}

    second = FakeGenAIClient()
    out = Translator(_provider(second), batch_size=2).translate(cues, done=cache.load(), on_batch=cache.save)
    assert len(second.requests) == 2  # only the two unfinished batches
    assert [c.text for c in out] == [f"BG line {i}" for i in range(1, 7)]


def test_cli_emits_quota_event_then_resumes(tmp_path, capsys, monkeypatch):
    src = tmp_path / "s.srt"
    src.write_text("".join(f"{i}\n00:00:0{i},000 --> 00:00:0{i},900\nmade-up line {i}\n\n"
                           for i in range(1, 5)), encoding="utf-8")
    clients = iter([FakeGenAIClient(ok_calls=1), FakeGenAIClient()])
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-test-key")

    def fake_init(self, model, rpm, rpd, api_key=None, client=None, limiter=None):
        self.model, self._client = model, next(clients)
        self.limiter = RateLimiter(10_000, 10_000, sleep=lambda s: None)
    monkeypatch.setattr(GeminiProvider, "__init__", fake_init)
    monkeypatch.setattr(GeminiProvider, "batch_size", 2)
    monkeypatch.setattr("subtrans.translate.DEFAULT_BATCH_SIZE", 2)
    monkeypatch.setattr(Translator.__init__, "__defaults__",
                        ("en", "bg", "", None, 2, 5))

    assert cli.main(["translate-srt", str(src)]) == 2
    events = [json.loads(ln) for ln in capsys.readouterr().out.splitlines()]
    assert events[-1] == {"event": "quota", "message": cli.QUOTA_MESSAGE}
    assert "dummy-test-key" not in json.dumps(events)

    assert cli.main(["translate-srt", str(src)]) == 0
    events = [json.loads(ln) for ln in capsys.readouterr().out.splitlines()]
    assert events[0] == {"event": "progress", "done": 2, "total": 4}
    assert events[-1]["event"] == "done" and len(events[-1]["cues"]) == 4
