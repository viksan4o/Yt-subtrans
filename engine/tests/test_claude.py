"""Claude provider with a fake Anthropic client. No real network calls."""

import json
from types import SimpleNamespace as S

import pytest

from subtrans import cli
from subtrans.cache import TranslationCache
from subtrans.config import claude_settings
from subtrans.models import Cue
from subtrans.providers import QuotaExceeded, get_provider
from subtrans.providers.claude import FALLBACK_BETA, ClaudeProvider
from subtrans.throttle import RateLimiter
from subtrans.translate import Translator


class RateLimitError(Exception):  # same name and status as the SDK's class
    status_code = 429


class FakeAnthropic:
    """Mimics client.beta.messages.create; raises `error` after `ok_calls` successes."""

    def __init__(self, ok_calls=99, error=None, refuse_first=False):
        self.beta = S(messages=self)
        self.ok_calls, self.error, self.refuse_first, self.requests = ok_calls, error, refuse_first, []

    def create(self, **kw):
        self.requests.append(kw)
        if len(self.requests) > self.ok_calls:
            raise self.error or RateLimitError("429 rate_limit_error")
        if self.refuse_first and len(self.requests) == 1:
            return S(stop_reason="refusal", content=[])
        cues = json.loads(kw["messages"][0]["content"])["cues"]
        text = json.dumps([{"id": c["id"], "text": "BG " + c["text"]} for c in cues])
        return S(stop_reason="end_turn", content=[S(type="text", text=text)])


def _provider(client, model="claude-opus-5-5"):
    return ClaudeProvider(model, 60, 1000, client=client,
                          limiter=RateLimiter(10_000, 10_000, sleep=lambda s: None))


def test_request_shape_and_fallbacks():
    client = FakeAnthropic()
    out = _provider(client).complete("SYS", json.dumps({"cues": [{"id": 1, "text": "hi"}]}))
    assert json.loads(out) == [{"id": 1, "text": "BG hi"}]
    req = client.requests[0]
    assert req["system"] == "SYS" and req["model"] == "claude-opus-5-5"
    assert req["betas"] == [FALLBACK_BETA] and req["fallbacks"] == "default"
    assert "temperature" not in req and "thinking" not in req

    haiku = FakeAnthropic()
    _provider(haiku, "claude-haiku-5-5").complete("SYS", json.dumps({"cues": []}))
    assert "fallbacks" not in haiku.requests[0]


def test_rate_limit_and_overload_become_quota():
    with pytest.raises(QuotaExceeded):
        _provider(FakeAnthropic(ok_calls=0)).complete("S", "{}")
    overloaded = Exception("overloaded"); overloaded.status_code = 529
    with pytest.raises(QuotaExceeded):
        _provider(FakeAnthropic(ok_calls=0, error=overloaded)).complete("S", "{}")
    other = Exception("bad request"); other.status_code = 400
    with pytest.raises(Exception, match="bad request"):
        _provider(FakeAnthropic(ok_calls=0, error=other)).complete("S", "{}")


def test_refusal_is_retried_via_validation():
    client = FakeAnthropic(refuse_first=True)
    out = Translator(_provider(client)).translate([Cue(1, 0, 1, "made-up line")])
    assert out[0].text == "BG made-up line" and len(client.requests) == 2


def test_missing_key_and_settings(monkeypatch):
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        get_provider("claude")
    assert claude_settings()["model"] == "claude-opus-5-5"
    monkeypatch.setenv("ANTHROPIC_PRESET", "economy")
    assert claude_settings()["model"] == "claude-haiku-5-5"
    monkeypatch.setenv("ANTHROPIC_MODEL", "my-model")
    assert claude_settings()["model"] == "my-model"


def test_429_saves_progress_and_resume(tmp_path):
    cues = [Cue(i, i, i + 1, f"line {i}") for i in range(1, 5)]
    cache = TranslationCache("vid", "en", "bg", "claude", "claude-opus-5-5", root=tmp_path)
    with pytest.raises(QuotaExceeded):
        Translator(_provider(FakeAnthropic(ok_calls=1)), batch_size=2).translate(
            cues, done=cache.load(), on_batch=cache.save)
    assert cache.load() == {1: "BG line 1", 2: "BG line 2"}
    second = FakeAnthropic()
    out = Translator(_provider(second), batch_size=2).translate(cues, done=cache.load(), on_batch=cache.save)
    assert len(second.requests) == 1 and [c.text for c in out][-1] == "BG line 4"


def test_cli_provider_from_env(tmp_path, capsys, monkeypatch):
    src = tmp_path / "s.srt"
    src.write_text("1\n00:00:01,000 --> 00:00:02,000\nmade-up line\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SUBTRANS_PROVIDER=claude\nANTHROPIC_API_KEY=dummy-test-key\n", encoding="utf-8")
    client = FakeAnthropic()
    monkeypatch.setattr(cli, "get_provider", lambda name, *a: _provider(client) if name == "claude" else None)
    assert cli.main(["translate-srt", str(src)]) == 0
    events = [json.loads(ln) for ln in capsys.readouterr().out.splitlines()]
    assert events[-1]["cues"][0]["tgt"] == "BG made-up line"
    assert "dummy-test-key" not in json.dumps(events)
