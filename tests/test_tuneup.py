"""tune_up: measured decisions, short answers, settings that stick. All silent."""

import random

import pytest
import yaml

from drivers import camera, settings
from mcp_server import intro, server, tuneup


@pytest.fixture(autouse=True)
def silent(monkeypatch):
    monkeypatch.setattr(tuneup.speaker, "say", lambda text, wait=False: 0.0)
    monkeypatch.setattr(tuneup.capslock, "set_mode", lambda m: None)


def hears(monkeypatch, text, reason="silence"):
    monkeypatch.setattr(tuneup.mic, "record", lambda max_s=8: (b"\x00\x00", reason))
    monkeypatch.setattr(tuneup.mic, "transcribe", lambda pcm, context="": text)


# --- answers ----------------------------------------------------------------

@pytest.mark.parametrize("text,want", [
    ("That was a bit too fast.", "fast"),
    ("Slow down please", "fast"),
    ("Too slow!", "slow"),
    ("Just right.", "right"),
    ("It's fine.", "right"),
    ("Hmm, the weather?", None),
    ("", None),
])
def test_voice_answers(text, want):
    assert tuneup.parse_answer(text, tuneup.VOICE_ANSWERS) == want


@pytest.mark.parametrize("text,want", [
    ("Yes.", "yes"), ("Yeah, I can.", "yes"), ("No.", "no"),
    ("I can't see it", "no"), ("No, I don't see it blinking", "no"),
    ("Yes and no", None), ("", None),
])
def test_yes_no(text, want):
    assert tuneup.parse_yes_no(text) == want


def test_word_match():
    assert tuneup.word_match("I'll show you something else", tuneup.EAR_TARGET) == 1.0
    assert tuneup.word_match("I'm in a few cents an hour", tuneup.EAR_TARGET) < 0.5


# --- eyes -------------------------------------------------------------------

def test_next_controls():
    c = {"gamma": 140, "brightness": -2}
    assert camera.next_controls({"mean": 120, "clipped": 0.0}, c) == (c, "ok")
    assert camera.next_controls({"mean": 200, "clipped": 0.2}, c) == ({"gamma": 120, "brightness": -3}, "darker")
    assert camera.next_controls({"mean": 30, "clipped": 0.0}, c) == ({"gamma": 160, "brightness": -1}, "brighter")
    assert camera.next_controls({"mean": 30, "clipped": 0}, {"gamma": 200, "brightness": 10})[1] == "too dark"
    assert camera.next_controls({"mean": 250, "clipped": 0.9}, {"gamma": 100, "brightness": -10})[1] == "too bright"


def test_eyes_steps_down_until_ok_and_saves(monkeypatch):
    shots = iter([{"mean": 200, "clipped": 0.2}, {"mean": 150, "clipped": 0.01}])
    monkeypatch.setattr(tuneup.camera, "photo", lambda: b"jpeg")
    monkeypatch.setattr(tuneup.camera, "brightness_stats", lambda jpeg: next(shots))
    out = tuneup.eyes()
    assert out.startswith("eyes: ok")
    assert settings.load()["camera"] == {"gamma": 120, "brightness": -3, "keep_pictures": False}


# --- voice, heartbeat, ears ---------------------------------------------------

def test_too_fast_slows_down_and_sticks(monkeypatch):
    hears(monkeypatch, "A bit too fast.")
    tuneup.voice()
    assert settings.load()["voice"]["speed"] == 0.9


def test_unclear_voice_answer_changes_nothing(monkeypatch):
    hears(monkeypatch, "Pizza.")
    tuneup.voice()
    assert settings.load()["voice"]["speed"] == 1.0


def test_led_not_seen_drops_the_promise(monkeypatch):
    monkeypatch.setattr(tuneup.capslock, "led_paths", lambda: ["/x"])
    hears(monkeypatch, "No, I can't see it.")
    tuneup.heartbeat()
    assert settings.load()["capslock"]["visible"] is False
    monkeypatch.setattr(server.capslock, "led_paths", lambda: [])
    assert server.check_devices()["capslock"] is False


def test_ears_ok_first_try(monkeypatch):
    hears(monkeypatch, "I'll show you something else.")
    assert tuneup.ears().startswith("ears: ok on try 1")


def test_ears_retries_once_after_a_miss(monkeypatch):
    answers = iter(["Okay, like this?", "I'll show you something else."])
    monkeypatch.setattr(tuneup.mic, "record", lambda max_s=8: (b"\x00\x00", "silence"))
    monkeypatch.setattr(tuneup.mic, "transcribe", lambda pcm, context="": next(answers))
    assert tuneup.ears().startswith("ears: ok on try 2")


def test_ears_weak_after_two_misses(monkeypatch):
    hears(monkeypatch, "", reason="no speech")
    assert tuneup.ears().startswith("ears: weak")


# --- settings and intro --------------------------------------------------------

def test_settings_defaults_and_round_trip():
    assert settings.load() == settings.DEFAULTS
    settings.update("voice", speed=1.1)
    assert settings.load()["voice"]["speed"] == 1.1
    assert settings.load()["camera"] == settings.DEFAULTS["camera"]


def test_first_intro_offers_the_tune_up():
    robot = yaml.safe_load(server.ROBOT_FILE.read_text())
    devices = server.load_devices()
    ok = {d["name"]: True for d in devices}
    first, _ = intro.build(robot, devices, set(), ok, rng=random.Random(1))
    assert first.endswith(robot["tune_question"])
    again, _ = intro.build(robot, devices, set(ok), ok, rng=random.Random(1))
    assert robot["tune_question"] not in again
