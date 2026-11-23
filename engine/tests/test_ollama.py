"""Ollama provider with a fake HTTP poster. No real network calls."""

import json
import urllib.error

import pytest

from subtrans import cli
from subtrans.config import OLLAMA_DEFAULT_MODEL
from subtrans.models import Cue
from subtrans.providers import get_provider
from subtrans.providers.ollama import OllamaProvider
from subtrans.translate import Translator, parse_response


class FakePost:
    """Replies like /api/chat. `shapes` picks the JSON form per call: list, wrapped, single, junk."""

    def __init__(self, shapes=("list",), max_ok=99):
        self.shapes, self.max_ok, self.calls = list(shapes), max_ok, []

    def __call__(self, url, body, timeout):
        self.calls.append((url, body))
        cues = json.loads(body["messages"][1]["content"])["cues"]
        shape = self.shapes[min(len(self.calls) - 1, len(self.shapes) - 1)]
        items = [{"id": c["id"], "text": "BG " + c["text"]} for c in cues]
        if len(cues) > self.max_ok or shape == "junk":
            content = "Ето превода: ..."
        elif shape == "wrapped":
            content = json.dumps({"translations": items})
        elif shape == "single":
            content = json.dumps(items[0])
        else:
            content = json.dumps(items)
        return {"message": {"role": "assistant", "content": content}}


def test_request_shape_and_defaults():
    post = FakePost()
    prov = OllamaProvider("bggpt", post=post)
    assert json.loads(prov.complete("SYS", json.dumps({"cues": [{"id": 1, "text": "hi"}]}))) == [
        {"id": 1, "text": "BG hi"}]
    url, body = post.calls[0]
    assert url == "http://localhost:11434/api/chat"
    assert body["options"]["num_ctx"] == 4096
    assert body["model"] == "bggpt" and body["format"] == "json" and body["stream"] is False
    assert body["messages"][0] == {"role": "system", "content": "SYS"}
    p = get_provider("ollama")  # no key needed
    assert p.model == OLLAMA_DEFAULT_MODEL and p.batch_size == 15 and p.num_ctx == 4096


def test_single_object_reply_accepted():
    assert parse_response('{"id": 3, "text": "Здрасти"}', [3]) == {3: "Здрасти"}


def test_echoed_input_with_empty_context_is_accepted():
    raw = json.dumps({"title": "t", "glossary": {}, "context": [], "cues": [{"id": 1, "text": "Здравей"}]})
    assert parse_response(raw, [1]) == {1: "Здравей"}


def test_http_500_shows_ollama_reason_and_memory_hint():
    import io

    def oom(url, body, timeout):
        raise urllib.error.HTTPError(url, 500, "Internal Server Error", None,
                                     io.BytesIO(b'{"error":"model requires more system memory"}'))
    with pytest.raises(RuntimeError, match="more system memory.*2.6B"):
        OllamaProvider("m", post=oom).complete("S", "{}")


def test_weak_json_recovers_with_retry_and_split():
    cues = [Cue(i, i, i + 1, f"line {i}") for i in range(1, 5)]
    post = FakePost(shapes=("junk", "wrapped", "list"), max_ok=2)
    out = Translator(OllamaProvider("m", post=post), batch_size=4).translate(cues)
    assert [c.text for c in out] == [f"BG line {i}" for i in range(1, 5)]


def test_clear_errors_when_ollama_missing_or_model_not_pulled():
    def refused(url, body, timeout):
        raise urllib.error.URLError("connection refused")
    with pytest.raises(RuntimeError, match="Стартирай Ollama"):
        OllamaProvider("m", post=refused).complete("S", "{}")

    def not_found(url, body, timeout):
        raise urllib.error.HTTPError(url, 404, "not found", None, None)
    with pytest.raises(RuntimeError, match="ollama pull m"):
        OllamaProvider("m", post=not_found).complete("S", "{}")


def test_cli_uses_small_batches_and_resumes_from_cache(tmp_path, capsys, monkeypatch):
    src = tmp_path / "s.srt"
    src.write_text("".join(f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},900\nmade-up line {i}\n\n"
                           for i in range(1, 8)), encoding="utf-8")
    post = FakePost()
    monkeypatch.setattr(cli, "get_provider", lambda *a: OllamaProvider("m", batch_size=3, post=post))
    assert cli.main(["translate-srt", str(src), "--provider", "ollama"]) == 0
    assert [len(json.loads(b["messages"][1]["content"])["cues"]) for _, b in post.calls] == [3, 3, 1]
    assert cli.main(["translate-srt", str(src), "--provider", "ollama"]) == 0
    assert len(post.calls) == 3  # second run served from cache
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["event"] == "done"
