"""Robot tools run one at a time, and listen never records Grace's own voice.

OpenCode + gemma called speak and listen in parallel (26 Nov 2026): listen started while
the first sentence was still being synthesised and recorded Grace herself."""

import threading
import time

from drivers import speaker
from mcp_server import server


def test_parallel_speak_and_listen_never_overlap(monkeypatch):
    monkeypatch.setattr(server, "_speak_refused", False)
    monkeypatch.setattr(server.capslock, "set_mode", lambda mode: None)
    monkeypatch.setattr(server.transcript, "add", lambda *a, **k: None)
    events = []

    def say(text, wait=False):
        events.append("speak start")
        time.sleep(0.3)  # synthesis of the first sentence
        events.append("speak end")
        return 1.0
    monkeypatch.setattr(server.speaker, "say", say)
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: False)
    monkeypatch.setattr(server.mic, "record", lambda max_s: (events.append("record"), (b"", "silence"))[1])
    monkeypatch.setattr(server.mic, "transcribe", lambda pcm, context="": "")

    t1 = threading.Thread(target=server.TOOLS["speak"], args=("Hello there.",))
    t2 = threading.Thread(target=server.TOOLS["listen"])
    t1.start()
    time.sleep(0.05)  # listen arrives 50 ms after speak, as in the OpenCode run
    t2.start()
    t1.join(); t2.join()
    assert events == ["speak start", "speak end", "record"]


def test_say_is_speaking_during_synthesis(monkeypatch):
    seen = []

    def synth(sentence, spec=speaker.VOICE):
        seen.append(speaker.is_speaking())
        return b"", 22050
    monkeypatch.setattr(speaker, "_synth_sentence", synth)
    monkeypatch.setattr(speaker, "_stream", lambda sentences, first: speaker._lock.release())
    speaker.say("One sentence.", wait=True)
    assert seen == [True]
    assert not speaker.is_speaking()


def test_failed_synthesis_releases_the_voice(monkeypatch):
    def boom(sentence, spec=speaker.VOICE):
        raise RuntimeError("no model")
    monkeypatch.setattr(speaker, "_synth_sentence", boom)
    try:
        speaker.say("Hello.")
    except RuntimeError:
        pass
    assert not speaker.is_speaking()


def test_camera_found_by_stable_name(monkeypatch):
    from drivers import camera
    monkeypatch.setattr(camera.glob, "glob", lambda pattern: ["/dev/v4l/by-id/usb-Cam-video-index0"])
    assert camera.device() == "/dev/v4l/by-id/usb-Cam-video-index0"
    monkeypatch.setattr(camera.glob, "glob", lambda pattern: [])
    assert camera.device() == "/dev/video0"


def test_see_says_no_picture_instead_of_crashing(monkeypatch):
    import subprocess
    monkeypatch.setattr(server.capslock, "set_mode", lambda mode: None)
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: False)

    def broken():
        raise subprocess.CalledProcessError(1, "ffmpeg", stderr=b"Cannot open video device")
    monkeypatch.setattr(server.camera, "photo", broken)
    out = server.TOOLS["see"]()
    assert out.startswith("NO PICTURE") and "Cannot open video device" in out


def _fake_voice(monkeypatch, events):
    monkeypatch.setattr(server, "_speak_refused", False)
    monkeypatch.setattr(server.capslock, "set_mode", lambda mode: None)
    monkeypatch.setattr(server.transcript, "add", lambda *a, **k: None)

    def say(text, wait=False):
        events.append(f"say {text}")
        time.sleep(0.3)
        return 1.0
    monkeypatch.setattr(server.speaker, "say", say)
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: False)
    monkeypatch.setattr(server.mic, "record", lambda max_s: (events.append("record"), (b"", "silence"))[1])
    monkeypatch.setattr(server.mic, "transcribe", lambda pcm, context="": "")


def test_batched_done_claim_is_refused(monkeypatch):
    """gemma, 27 Nov 2026: speak "I'll create it", write, speak "Done!", listen, in one batch.
    The second speak arrives while the first still runs: refused, and the listen with it."""
    events, out = [], {}
    _fake_voice(monkeypatch, events)
    calls = [("speak", ("I'll create it now.",)), ("speak", ("Done! I've written the file.",)),
             ("listen", ())]
    threads = []
    for i, (tool, args) in enumerate(calls):
        t = threading.Thread(target=lambda i=i, tool=tool, args=args: out.__setitem__(i, server.TOOLS[tool](*args)))
        threads.append(t); t.start(); time.sleep(0.05)
    for t in threads:
        t.join()
    assert events == ["say I'll create it now."]
    assert out[1].startswith("NOT SPOKEN: this speak was sent together")
    assert out[2].startswith("NOT LISTENING")


def test_step_by_step_speaks_are_not_refused(monkeypatch):
    events = []
    _fake_voice(monkeypatch, events)
    assert server.TOOLS["speak"]("One.").startswith("speaking")
    assert server.TOOLS["speak"]("Two.").startswith("speaking")
    assert events == ["say One.", "say Two."]


def test_queue_keeps_arrival_order(monkeypatch):
    events = []
    _fake_voice(monkeypatch, events)
    monkeypatch.setattr(server.settings, "load", lambda: {"ears": {"vocabulary": []}, "voice": {"max_words": 50}})
    monkeypatch.setattr(server.mic, "record", lambda max_s: (time.sleep(0.1), (b"", "silence"))[1])
    monkeypatch.setattr(server.mic, "transcribe", lambda pcm, context="": events.append(context) or "")
    ts = [threading.Thread(target=server.TOOLS["listen"], kwargs={"context": str(i)}) for i in range(5)]
    for t in ts:
        t.start(); time.sleep(0.01)
    for t in ts:
        t.join()
    assert events == ["0", "1", "2", "3", "4"]


def test_cue_is_not_refused_when_see_arrives_first(monkeypatch):
    """27 Nov 2026: gemma sent speak (cue) + see; see reached the server 4 ms first and the
    first version refused the cue. Only a speak behind another speak is a batched claim."""
    events, out = [], {}
    _fake_voice(monkeypatch, events)
    monkeypatch.setattr(server.camera, "photo", lambda: (events.append("photo"), time.sleep(0.2), b"\xff\xd8")[2])
    monkeypatch.setattr(server, "thinking_line", lambda: "")
    t1 = threading.Thread(target=lambda: out.__setitem__("see", server.TOOLS["see"]()))
    t2 = threading.Thread(target=lambda: out.__setitem__("speak", server.TOOLS["speak"]("Hold it up.")))
    t1.start(); time.sleep(0.02); t2.start()
    t1.join(); t2.join()
    assert out["speak"].startswith("speaking")
    assert server._speaks_in_flight == 0
