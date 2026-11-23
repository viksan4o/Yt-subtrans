"""YouTube id parsing, caption fetching and the `translate` command. Fake sources only, no network."""

import json
from types import SimpleNamespace as S

import pytest
from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled

from subtrans import cli, youtube
from subtrans.models import Cue
from subtrans.youtube import NoCaptions, fetch_captions, parse_video_id, snippets_to_cues

VID = "abcDEF12345"  # made-up id


@pytest.mark.parametrize("url", [
    VID,
    f"https://www.youtube.com/watch?v={VID}&t=42s",
    f"https://m.youtube.com/watch?feature=share&v={VID}",
    f"https://youtu.be/{VID}?si=xyz",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/embed/{VID}",
    f"https://www.youtube.com/live/{VID}?feature=share",
    f"youtube.com/watch?v={VID}",
])
def test_parse_video_id(url):
    assert parse_video_id(url) == VID


@pytest.mark.parametrize("bad", ["", "https://example.com/watch?v=abcDEF12345", "https://youtu.be/short"])
def test_parse_video_id_rejects(bad):
    with pytest.raises(ValueError, match="YouTube"):
        parse_video_id(bad)


SNIPS = [S(text="made-up one", start=0.0, duration=4.0), S(text="  ", start=1.0, duration=1.0),
         S(text="made-up two", start=2.5, duration=4.0), S(text="made-up three", start=5.0, duration=1.5)]


def test_auto_captions_end_clamped_to_next_start():
    assert snippets_to_cues(SNIPS, generated=True) == [
        Cue(1, 0.0, 2.5, "made-up one"), Cue(2, 2.5, 5.0, "made-up two"), Cue(3, 5.0, 6.5, "made-up three")]
    assert snippets_to_cues(SNIPS, generated=False)[0].end == 4.0


class FakeListing:
    def __init__(self, manual=None, auto=None):
        self.manual, self.auto = manual, auto

    def _find(self, which, langs):
        if which is None:
            raise NoTranscriptFound(VID, langs, None)
        return S(fetch=lambda: which)

    def find_manually_created_transcript(self, langs):
        return self._find(self.manual, langs)

    def find_generated_transcript(self, langs):
        return self._find(self.auto, langs)


class FakeApi:
    def __init__(self, listing=None):
        self.listing = listing

    def list(self, video_id):
        if self.listing is None:
            raise TranscriptsDisabled(video_id)
        return self.listing


def test_prefers_manual_then_falls_back_to_auto():
    manual = [S(text="manual line", start=0, duration=1)]
    cues, generated = fetch_captions(VID, "en", FakeApi(FakeListing(manual=manual, auto=SNIPS)))
    assert [c.text for c in cues] == ["manual line"] and not generated
    cues, generated = fetch_captions(VID, "en", FakeApi(FakeListing(auto=SNIPS)))
    assert len(cues) == 3 and generated


def test_no_captions_gives_bulgarian_message():
    for api in (FakeApi(FakeListing()), FakeApi(None)):
        with pytest.raises(NoCaptions, match="няма субтитри"):
            fetch_captions(VID, "en", api)


def _events(capsys):
    return [json.loads(ln) for ln in capsys.readouterr().out.splitlines()]


def test_cli_translate_then_second_run_from_cache(capsys, monkeypatch):
    calls = []

    def fake_fetch(video_id, lang):
        calls.append((video_id, lang))
        return snippets_to_cues(SNIPS, generated=True), True
    monkeypatch.setattr(youtube, "fetch_captions", fake_fetch)

    url = f"https://youtu.be/{VID}"
    assert cli.main(["translate", url, "--provider", "fake"]) == 0
    first = _events(capsys)
    assert first[-1]["event"] == "done" and [c["tgt"] for c in first[-1]["cues"]][0] == "[BG] made-up one"

    class Boom:  # any provider use on the second run would fail the test
        def complete(self, *a):
            raise AssertionError("provider called on cached run")
    monkeypatch.setattr(cli, "get_provider", lambda *a, **k: Boom())
    assert cli.main(["translate", VID, "--provider", "fake"]) == 0
    second = _events(capsys)
    assert calls == [(VID, "en")]  # captions fetched once
    assert second[-1]["cues"] == first[-1]["cues"]


def test_cli_translate_reports_errors_as_events(capsys, monkeypatch):
    def no_caps(video_id, lang):
        raise NoCaptions(youtube.NO_CAPTIONS.format(lang=lang))
    monkeypatch.setattr(youtube, "fetch_captions", no_caps)
    assert cli.main(["translate", VID, "--provider", "fake"]) == 1
    assert _events(capsys)[-1]["event"] == "error"
    assert cli.main(["translate", "not a link", "--provider", "fake"]) == 1
    assert "YouTube" in _events(capsys)[-1]["message"]
