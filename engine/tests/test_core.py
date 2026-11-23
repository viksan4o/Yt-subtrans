"""Core tests. All subtitle text here is made up; no third-party captions."""

import json

import pytest

from subtrans import cli
from subtrans.chunking import make_batches
from subtrans.models import Cue
from subtrans.srt import parse_srt, write_srt
from subtrans.translate import TranslationError, Translator, ValidationError, parse_response
from subtrans.wrap import chars_per_second, too_fast, wrap_text

SAMPLE = """1
00:00:01,000 --> 00:00:03,500
Hello there, friend.

2
00:00:04,000 --> 00:00:07,250
This is a made-up line that is clearly longer than forty-two characters.

3
00:01:02,005 --> 00:01:04,000
[Music]
"""


def test_srt_roundtrip():
    cues = parse_srt(SAMPLE)
    assert [c.id for c in cues] == [1, 2, 3]
    assert cues[2].start == pytest.approx(62.005)
    assert parse_srt(write_srt(cues)) == cues


def test_srt_tolerates_bom_crlf_and_dot_millis():
    cues = parse_srt("﻿1\r\n00:00:01.5 --> 00:00:02.000\r\nHi\r\n")
    assert cues == [Cue(1, 1.5, 2.0, "Hi")]


def test_wrap_balanced_and_lossless():
    text = "This is a made-up line that is clearly longer than forty-two characters."
    wrapped = wrap_text(text)
    lines = wrapped.split("\n")
    assert len(lines) == 2 and all(len(ln) <= 42 for ln in lines)
    assert abs(len(lines[0]) - len(lines[1])) < 15
    assert " ".join(lines) == text


def test_wrap_keeps_short_dialogue_and_splits_huge_word():
    assert wrap_text("- Hi.\n- Hello.") == "- Hi.\n- Hello."
    assert wrap_text("x" * 100).replace("\n", "") == "x" * 100
    assert all(len(ln) <= 42 for ln in wrap_text("x" * 100).split("\n"))


def test_cps():
    assert chars_per_second("abcd\nefgh", 0, 2) == 4.0
    assert too_fast(chars_per_second("x" * 50, 0, 2))


def test_batching_with_context():
    cues = [Cue(i, i, i + 1, f"line {i}") for i in range(1, 11)]
    batches = make_batches(cues, size=4, context_size=2)
    assert [len(b.cues) for b in batches] == [4, 4, 2]
    assert batches[0].context == [] and [c.id for c in batches[1].context] == [3, 4]


def test_parse_response_fenced_and_wrapped():
    raw = '```json\n[{"id": 1, "text": "Здравей"}]\n```'
    assert parse_response(raw, [1]) == {1: "Здравей"}
    assert parse_response('{"cues": [{"id": 1, "text": "a"}]}', [1]) == {1: "a"}
    with pytest.raises(ValidationError):
        parse_response('[{"id": 2, "text": "a"}]', [1])
    with pytest.raises(ValidationError):
        parse_response('[{"id": 1, "text": " "}]', [1])


class ScriptedProvider:
    """Fails (wrong ids) whenever a request holds more than `max_ok` cues; `bad_id` always fails."""
    name = model = "scripted"

    def __init__(self, max_ok=99, bad_id=None):
        self.max_ok, self.bad_id, self.calls = max_ok, bad_id, []

    def complete(self, system, user):
        cues = json.loads(user)["cues"]
        self.calls.append([c["id"] for c in cues])
        if len(cues) > self.max_ok or any(c["id"] == self.bad_id for c in cues):
            return json.dumps([{"id": 999, "text": "x"}])
        return json.dumps([{"id": c["id"], "text": "BG " + c["text"]} for c in cues])


def test_wrong_ids_retry_then_split():
    cues = [Cue(i, i, i + 1, f"line {i}") for i in range(1, 5)]
    prov = ScriptedProvider(max_ok=2)
    out = Translator(prov, batch_size=4).translate(cues)
    assert [c.text for c in out] == [f"BG line {i}" for i in range(1, 5)]
    assert prov.calls[:3] == [[1, 2, 3, 4]] * 3  # 1 try + 2 retries, then split
    assert prov.calls[3:] == [[1, 2], [3, 4]]


def test_single_cue_failure_is_clear():
    prov = ScriptedProvider(bad_id=2)
    with pytest.raises(TranslationError, match="id 2"):
        Translator(prov).translate([Cue(1, 0, 1, "a"), Cue(2, 1, 2, "b")])


def test_prompt_inserts_language_names():
    t = Translator(ScriptedProvider(), source="en", target="de")
    assert "from English to German" in t.system


def test_cli_translate_srt(tmp_path, capsys):
    src = tmp_path / "sample.srt"
    src.write_text(SAMPLE, encoding="utf-8")
    assert cli.main(["translate-srt", str(src)]) == 0
    events = [json.loads(ln) for ln in capsys.readouterr().out.splitlines()]
    assert events[-1]["event"] == "done" and len(events[-1]["cues"]) == 3
    out = parse_srt((tmp_path / "sample.bg.srt").read_text(encoding="utf-8"))
    orig = parse_srt(SAMPLE)
    assert [(c.start, c.end) for c in out] == [(c.start, c.end) for c in orig]
    assert all(len(ln) <= 42 for c in out for ln in c.text.split("\n"))
