"""Hardware-free tests: endpointing, ffmpeg arguments, LED discovery, device registry."""

import array
from pathlib import Path

import pytest

from drivers import camera, capslock, mic
from mcp_server import server

PER_S = 1000 // mic.CHUNK_MS  # chunks per second (33)


def feed_all(ep, levels):
    for i, lv in enumerate(levels):
        if ep.feed(lv):
            return i
    return None


# --- mic endpointing --------------------------------------------------------

def test_stops_after_one_second_of_silence():
    ep = mic.Endpointer(silence_s=1.0)
    levels = [50] * 10 + [2000] * PER_S * 2 + [50] * PER_S * 3
    stop = feed_all(ep, levels)
    assert ep.reason == "silence"
    speech_end = 10 + PER_S * 2
    assert speech_end + PER_S - 2 <= stop <= speech_end + PER_S + 1


def test_short_pause_does_not_stop():
    ep = mic.Endpointer()
    levels = [50] * 10 + [2000] * PER_S + [50] * (PER_S // 2) + [2000] * PER_S
    assert feed_all(ep, levels) is None
    assert ep.started


def test_gives_up_with_no_speech():
    ep = mic.Endpointer(no_speech_s=2)
    stop = feed_all(ep, [50] * PER_S * 5)
    assert ep.reason == "no speech" and stop < PER_S * 3


def test_max_length():
    ep = mic.Endpointer(max_s=2)
    stop = feed_all(ep, [50] * 10 + [2000] * PER_S * 5)
    assert ep.reason == "max length" and stop < PER_S * 3


def test_threshold_follows_noise_floor():
    ep = mic.Endpointer()
    feed_all(ep, [500] * 10)
    assert ep.threshold == 1500  # 3x the floor
    ep2 = mic.Endpointer()
    feed_all(ep2, [10] * 10)
    assert ep2.threshold == 300  # never below the minimum


def test_rms():
    assert mic.rms(array.array("h", [3, -3, 3, -3]).tobytes()) == 3
    assert mic.rms(b"") == 0


# --- camera -----------------------------------------------------------------

def test_photo_args_warm_up():
    a = camera.photo_args("/tmp/x.jpg")
    assert "select=gte(n\\,30)" in a and a[-1] == "/tmp/x.jpg"
    assert a[a.index("-input_format") + 1] == "mjpeg"


def test_watch_args_grid():
    a = camera.watch_args("/tmp/x.jpg", seconds=6, cols=3, rows=3)
    vf = a[a.index("-vf") + 1]
    assert "fps=1.5" in vf and "scale=426:240" in vf and "tile=3x3" in vf
    assert a[a.index("-t") + 1] == "7.5"


def test_controls_args():
    assert camera.controls_args("/dev/video9", {"gamma": 140, "brightness": -2}) == [
        "v4l2-ctl", "-d", "/dev/video9", "-c", "gamma=140", "-c", "brightness=-2"]


def test_watch_note():
    assert "9 webcam frames from 6 seconds" in camera.watch_note()


# --- capslock ---------------------------------------------------------------

def test_led_paths(tmp_path):
    for n in ("input0::capslock", "input23::capslock", "input0::numlock"):
        (tmp_path / n).mkdir()
        (tmp_path / n / "brightness").write_text("0")
    found = capslock.led_paths(str(tmp_path / "*::capslock/brightness"))
    assert [Path(p).parent.name for p in found] == ["input0::capslock", "input23::capslock"]


def test_bad_mode():
    with pytest.raises(ValueError):
        capslock.set_mode("disco")


# --- registry ---------------------------------------------------------------

def test_every_device_file_maps_to_a_tool():
    devices = server.load_devices()
    assert sorted(d["tool"] for d in devices) == ["capslock", "listen", "see", "speak"]


def test_unknown_tool_is_refused():
    with pytest.raises(ValueError, match="unknown tool"):
        server.build_server([{"name": "neck", "tool": "turn", "description": "x"}])


def test_missing_description_is_refused(tmp_path):
    (tmp_path / "x.yaml").write_text("name: x\ntool: see\n")
    with pytest.raises(ValueError, match="description"):
        server.load_devices(tmp_path)


# --- context and pauses -----------------------------------------------------

def test_context_reaches_whisper(monkeypatch):
    seen = {}

    class FakeModel:
        def transcribe(self, audio, **kw):
            seen.update(kw)
            return iter([]), None
    monkeypatch.setattr(mic, "_get_model", lambda: FakeModel())
    mic.transcribe(b"\x00\x00" * 160, "polka-dot mug, cup")
    assert seen["initial_prompt"] == "polka-dot mug, cup"
    mic.transcribe(b"\x00\x00" * 160)
    assert seen["initial_prompt"] is None


def test_listen_tool_passes_context(monkeypatch):
    got = {}
    monkeypatch.setattr(server.capslock, "set_mode", lambda m: None)
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: False)
    monkeypatch.setattr(server.mic, "record", lambda max_s: (b"", "silence"))
    monkeypatch.setattr(server.mic, "transcribe", lambda pcm, context="": got.setdefault("c", context) or "x")
    server.TOOLS["listen"](context="mug")
    assert got["c"] == "mug"


def test_sentences_and_voice_spec():
    from drivers import speaker
    assert speaker.split_sentences("Hi, I'm Grace. Is that a mug? Yes!") == ["Hi, I'm Grace.", "Is that a mug?", "Yes!"]
    assert speaker.split_sentences("  ") == []
    assert speaker.parse_voice("kokoro:af_bella") == ("kokoro", "af_bella")
    with pytest.raises(ValueError):
        speaker.parse_voice("af_bella")


def test_float_to_int16_clips():
    import array
    from drivers import speaker
    out = array.array("h", speaker.float_to_int16([0.0, 1.0, -2.0]))
    assert list(out) == [0, 32767, -32767]


def test_default_waits_through_a_one_second_pause():
    ep = mic.Endpointer()
    levels = [50] * 10 + [2000] * PER_S + [50] * PER_S + [2000] * PER_S
    assert feed_all(ep, levels) is None
