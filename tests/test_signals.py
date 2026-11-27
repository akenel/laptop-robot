"""The LED signal standard: solid = your turn, slow = thinking, fast = Grace acting."""

import threading
import time

import pytest

from mcp_server import server


@pytest.fixture(autouse=True)
def silent(monkeypatch):
    """No test may make a sound: the real voice is replaced unless a test patches it itself."""
    monkeypatch.setattr(server.speaker, "say", lambda text, wait=False: 0.0)
    monkeypatch.setattr(server, "_speak_refused", False)


@pytest.fixture
def modes(monkeypatch):
    seen = []
    monkeypatch.setattr(server.capslock, "set_mode", seen.append)
    return seen


def settle():
    time.sleep(0.1)  # let the after-tool thread run


def test_listen_is_your_turn_then_thinking(modes, monkeypatch):
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: False)
    monkeypatch.setattr(server.mic, "record", lambda max_s: (b"", "silence"))

    def transcribe(pcm, context=""):
        assert modes[-1] == "slow"  # transcribing is thinking, not your turn
        return "hello"
    monkeypatch.setattr(server.mic, "transcribe", transcribe)

    out = server.TOOLS["listen"]()
    settle()
    assert "hello" in out
    assert modes == ["on", "slow", "slow"]


def test_listen_waits_for_grace_to_finish(modes, monkeypatch):
    talking = [True]
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: talking[0])
    monkeypatch.setattr(server.speaker, "wait_until_quiet", lambda: talking.__setitem__(0, False))
    monkeypatch.setattr(server.mic, "record", lambda max_s: (b"", "silence"))
    monkeypatch.setattr(server.mic, "transcribe", lambda pcm, context="": "")
    server.TOOLS["listen"]()
    assert modes[:2] == ["fast", "on"]  # still acting while she speaks, then your turn


def test_speaking_stays_fast_until_quiet(modes, monkeypatch):
    quiet = threading.Event()
    monkeypatch.setattr(server.speaker, "say", lambda text, wait=False: 2.0)
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: not quiet.is_set())
    monkeypatch.setattr(server.speaker, "wait_until_quiet", lambda: quiet.wait(2))

    server.TOOLS["speak"]("Hello")
    settle()
    assert modes == ["fast"]  # tool returned, but she is still talking
    quiet.set()
    settle()
    assert modes == ["fast", "slow"]


def test_see_is_acting(modes, monkeypatch):
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: False)
    monkeypatch.setattr(server.camera, "photo", lambda: b"\xff\xd8jpeg")
    server.TOOLS["see"]("photo")
    settle()
    assert modes == ["fast", "slow"]


def test_watch_is_ready_action_cut(modes, monkeypatch):
    calls = []
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: False)
    monkeypatch.setattr(server.speaker, "say", lambda text, wait=False: calls.append(("say", text)) or 0.5)

    def watch():
        calls.append(("watch", list(modes)))
        return b"\xff\xd8grid"
    monkeypatch.setattr(server.camera, "watch", watch)

    out = server.TOOLS["see"]("watch", ready_seconds=0.01)
    settle()
    assert calls[0] == ("watch", ["on", "fast"])  # ready, then action, then record
    assert calls[1][1].startswith("Got it. ")     # cut, then a thinking line
    assert "9 webcam frames" in out[0]


def test_photo_has_no_ready_phase(modes, monkeypatch):
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: False)
    monkeypatch.setattr(server.camera, "photo", lambda: b"\xff\xd8jpeg")
    server.TOOLS["see"]("photo")
    assert "on" not in modes


def test_speak_refuses_long_text(modes, monkeypatch):
    spoken = []
    monkeypatch.setattr(server.speaker, "say", lambda text, wait=False: spoken.append(text) or 1.0)
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: False)
    limit = server.max_words()
    out = server.TOOLS["speak"](" ".join(["word"] * (limit + 1)))
    assert out.startswith(f"NOT SPOKEN: {limit + 1} words, the limit is {limit}")
    assert spoken == []
    server.TOOLS["speak"](" ".join(["word"] * limit))
    assert len(spoken) == 1


def test_thinking_line_fills_dead_air_and_never_repeats(modes, monkeypatch):
    import yaml
    lines = yaml.safe_load(server.ROBOT_FILE.read_text())["thinking_lines"]
    said = [server.thinking_line() for _ in range(30)]
    assert all(l in lines for l in said)
    assert all(a != b for a, b in zip(said, said[1:]))


def test_photo_thinks_aloud_unless_told_not_to(modes, monkeypatch):
    spoken = []
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: False)
    monkeypatch.setattr(server.speaker, "say", lambda text, wait=False: spoken.append(text) or 1.0)
    monkeypatch.setattr(server.camera, "photo", lambda: b"\xff\xd8jpeg")
    server.TOOLS["see"]("photo")
    server.TOOLS["see"]("photo", think_aloud=False)
    assert len(spoken) == 1


def fake_ears(monkeypatch, text):
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: False)
    monkeypatch.setattr(server.mic, "record", lambda max_s: (b"", "silence"))
    monkeypatch.setattr(server.mic, "transcribe", lambda pcm, context="": text)


def test_refused_speak_blocks_the_next_listen(modes, monkeypatch):
    fake_ears(monkeypatch, "hello")
    server.TOOLS["speak"](" ".join(["word"] * 200))
    assert server.TOOLS["listen"]().startswith("NOT LISTENING")
    server.TOOLS["speak"]("Shorter now.")
    assert "hello" in server.TOOLS["listen"]()


def test_pondering_line_after_a_real_question(modes, monkeypatch):
    spoken = []
    monkeypatch.setattr(server.speaker, "say", lambda text, wait=False: spoken.append(text) or 1.0)
    fake_ears(monkeypatch, "How would I wire the servo to the Pico?")
    server.TOOLS["listen"]()
    assert len(spoken) == 1
    fake_ears(monkeypatch, "Yes, thanks.")
    server.TOOLS["listen"]()
    assert len(spoken) == 1  # short answers get no filler


@pytest.mark.parametrize("text,want", [
    ("How would I wire the servo to the Pico?", True),
    ("Tell me a story about my desk", True),
    ("Is it big?", False),          # too short to need thinking time
    ("I like the polka dots a lot", False),
    ("", False),
])
def test_is_real_question(text, want):
    assert server.is_real_question(text) is want


# --- the LED never says "your turn" when nobody listens (spec, 26 Nov 2026) ----

def test_capslock_tool_only_switches_off(modes):
    assert server.TOOLS["capslock"]("on").startswith("REFUSED")
    assert server.TOOLS["capslock"]("fast").startswith("REFUSED")
    assert modes == []
    assert server.TOOLS["capslock"]("off") == "capslock off"
    assert modes == ["off"]


def test_capslock_tool_schema_offers_only_off():
    import asyncio
    tools = asyncio.run(server.build_server().list_tools())
    schema = next(t for t in tools if t.name == "capslock").input_schema
    assert "off" in str(schema) and "fast" not in str(schema) and "slow" not in str(schema)
