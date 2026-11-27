"""Conversation flow: longer listening, Whisper loop guard, progress lines, opt-in transcript."""

import json
import random
import time

import pytest
import yaml

from drivers import mic, settings
from mcp_server import intro, server, transcript

REAL_TRANSCRIBE = mic.transcribe  # the fixture below replaces it for the other tests


@pytest.fixture(autouse=True)
def quiet_robot(monkeypatch):
    said = []
    monkeypatch.setattr(server.speaker, "say", lambda text, wait=False: said.append(text) or 0.0)
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: False)
    monkeypatch.setattr(server.capslock, "set_mode", lambda m: None)
    monkeypatch.setattr(server, "_speak_refused", False)
    monkeypatch.setattr(server.mic, "record", lambda max_s: (b"", "silence"))
    monkeypatch.setattr(server.mic, "transcribe", lambda pcm, context="": "Yes.")
    return said


def test_listen_defaults_to_30_seconds():
    assert mic.Endpointer().max_chunks == int(30 * 1000 / mic.CHUNK_MS)
    import inspect
    assert inspect.signature(server.listen).parameters["max_seconds"].default == 30


def test_whisper_loop_guard(monkeypatch):
    seen = {}

    class Fake:
        def transcribe(self, audio, **kw):
            seen.update(kw)
            return iter([]), None
    monkeypatch.setattr(mic, "_get_model", lambda: Fake())
    REAL_TRANSCRIBE(b"\x00\x00" * 10)
    assert seen["condition_on_previous_text"] is False and seen["no_repeat_ngram_size"] == 3


# --- progress lines ----------------------------------------------------------

def test_progress_lines_while_the_person_waits(quiet_robot, monkeypatch):
    monkeypatch.setattr(server, "PROGRESS_S", 0.05)
    server.TOOLS["listen"]()           # the person spoke, Grace has not answered yet
    time.sleep(0.4)
    lines = yaml.safe_load(server.ROBOT_FILE.read_text())["progress_lines"]
    assert quiet_robot == lines[:3] + [server.stalled_line()]  # three, then "my brain has stopped"


def test_no_progress_line_after_grace_answered(quiet_robot, monkeypatch):
    monkeypatch.setattr(server, "PROGRESS_S", 0.05)
    server.TOOLS["listen"]()
    server.TOOLS["speak"]("Goodbye.")  # answered: nothing left to wait for
    time.sleep(0.3)
    assert quiet_robot == ["Goodbye."]


# --- transcript --------------------------------------------------------------

def day_lines():
    f = transcript.directory() / f"{time.strftime('%Y-%m-%d')}.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


def test_transcript_is_off_by_default():
    server.TOOLS["listen"]()
    server.TOOLS["speak"]("Hello.")
    assert day_lines() == []


def test_transcript_when_switched_on():
    settings.update("transcript", enabled=True)
    server.TOOLS["listen"]()
    server.TOOLS["speak"]("Hello there.")
    assert [(l["who"], l["text"]) for l in day_lines()] == [("person", "Yes."), ("grace", "Hello there.")]


def test_intro_says_it_keeps_a_transcript():
    robot = yaml.safe_load(server.ROBOT_FILE.read_text())
    devices = server.load_devices()
    ok = {d["name"]: True for d in devices}
    text, _ = intro.build(robot, devices, set(ok), ok, rng=random.Random(1), notes=[transcript.NOTE])
    assert transcript.NOTE in text


def test_transcript_page_escapes_html():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))
    import transcript as page
    out = page.render([{"time": "19:00:00", "who": "person", "text": "<script>x</script>"}], "2026-11-25")
    assert "<script>x" not in out and "&lt;script&gt;" in out


def test_busy_announcement_keeps_progress_lines(quiet_robot, monkeypatch):
    monkeypatch.setattr(server, "PROGRESS_S", 0.05)
    server.TOOLS["speak"]("Let me look that up.", busy=True)
    time.sleep(0.3)
    lines = yaml.safe_load(server.ROBOT_FILE.read_text())["progress_lines"]
    assert quiet_robot[0] == "Let me look that up." and quiet_robot[1] == lines[0]


def test_vocabulary_joins_every_context(monkeypatch):
    got = {}
    monkeypatch.setattr(server.mic, "transcribe", lambda pcm, context="": got.setdefault("c", context) or "x")
    settings.update("ears", vocabulary=["Oaxaca", "Taranaki"])
    server.TOOLS["listen"](context="weather")
    assert got["c"] == "weather, Oaxaca, Taranaki"


def test_stalled_agent_gets_a_wake_up_line_and_the_light_goes_off(quiet_robot, monkeypatch):
    """26-27 Nov 2026: the agent stopped after a listen; the LED blinked 'thinking' for 5 min."""
    modes = []
    monkeypatch.setattr(server.capslock, "set_mode", modes.append)
    monkeypatch.setattr(server, "PROGRESS_S", 0.05)
    server.TOOLS["listen"]()
    time.sleep(0.4)
    assert quiet_robot[-1] == server.stalled_line() and "hi grace" in quiet_robot[-1]
    assert modes[-1] == server.IDLE


def test_idle_after_90_seconds_not_5_minutes():
    assert server.IDLE_S == 90.0
