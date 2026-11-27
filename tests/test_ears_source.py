"""Which mic Grace listens through: Bluetooth warning, pinning, EARS TROUBLE hint.
Run 2 of the clean-user test (25 Nov 2026): a JBL speaker's phone mic took over."""

import pytest

from drivers import mic, settings
from mcp_server import server, tuneup

PACTL = """Source #51
	Name: alsa_output.pci-0000.HiFi__sink.monitor
	Description: Monitor of Speaker
	Properties:
		device.bus = "pci"
Source #56
	Name: alsa_input.pci-0000.HiFi__hw_sofhdadsp_6__source
	Description: Digital Microphone
	Properties:
		device.bus = "pci"
Source #60
	Name: alsa_input.usb-PC-LM1E_Camera-02.mono-fallback
	Description: PC-LM1E Camera Mono
	Properties:
		device.bus = "usb"
Source #71
	Name: bluez_input.AA_BB_CC_DD_EE_FF.0
	Description: JBL Flip 5
	Properties:
		device.bus = "bluetooth"
"""
SOURCES = mic.parse_sources(PACTL)
JBL, CAM = SOURCES[2], SOURCES[1]


def test_parse_sources_skips_monitors_and_spots_bluetooth():
    assert [s["description"] for s in SOURCES] == ["Digital Microphone", "PC-LM1E Camera Mono", "JBL Flip 5"]
    assert [s["bluetooth"] for s in SOURCES] == [False, False, True]


def test_choose_default_pinned_and_missing_pin():
    assert mic.choose(SOURCES, JBL["name"], "") == (JBL, False)
    assert mic.choose(SOURCES, JBL["name"], "pc-lm1e") == (CAM, False)   # pin by part of the description
    assert mic.choose(SOURCES, JBL["name"], "logitech") == (JBL, True)   # pin unplugged: default, and say so


def test_usb_mic_beats_bluetooth():
    assert mic.better_than_bluetooth(SOURCES) == CAM


def test_pinned_mic_records_with_parecord():
    assert mic.record_command(CAM["name"])[:2] == ["parecord", "--raw"]
    assert CAM["name"] in mic.record_command(CAM["name"])
    assert mic.record_command(None)[0] == "arecord"


def bt_status(alt=CAM):
    return {"source": JBL, "pin_missing": False, "pin": "", "alternative": alt,
            "sink": "bluez_output.AA_BB.1", "sink_bluetooth": True}


def test_warning_names_the_bluetooth_mic_and_the_way_out():
    w = server.ears_warning(bt_status())
    assert "JBL Flip 5" in w and "Bluetooth" in w and "PC-LM1E Camera Mono" in w
    assert "webcam or USB mic" in server.ears_warning(bt_status(alt=None))


def test_no_warning_for_a_wired_mic():
    st = {"source": CAM, "pin_missing": False, "pin": "", "alternative": None}
    assert server.ears_warning(st) == ""


def test_warning_when_the_pinned_mic_is_gone():
    st = {"source": CAM, "pin_missing": True, "pin": "Logitech", "alternative": None}
    assert "Logitech" in server.ears_warning(st)


def test_hello_says_the_bluetooth_warning_and_reports_mic_and_speaker(monkeypatch):
    said = []
    monkeypatch.setattr(server.speaker, "say", lambda text, wait=False: said.append(text) or 0.0)
    monkeypatch.setattr(server.capslock, "set_mode", lambda m: None)
    monkeypatch.setattr(server.mic, "status", bt_status)
    monkeypatch.setattr(server.intro, "save_seen", lambda seen: None)
    out = server.hello()
    assert "JBL Flip 5, a Bluetooth phone mic" in said[0]
    assert "mic: JBL Flip 5, Bluetooth" in out and "speaker: bluez_output.AA_BB.1, Bluetooth" in out


# --- two bad listens in a row -------------------------------------------------

@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(server.speaker, "say", lambda text, wait=False: 0.0)
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: False)
    monkeypatch.setattr(server.capslock, "set_mode", lambda m: None)
    monkeypatch.setattr(server, "_speak_refused", False)
    monkeypatch.setattr(server, "_failed_listens", 0)
    monkeypatch.setattr(server.mic, "record", lambda max_s: (b"", "silence"))


def hear(monkeypatch, text, score):
    def fake(pcm, context=""):
        server.mic.last_score = score
        return text
    monkeypatch.setattr(server.mic, "transcribe", fake)


def test_listen_failed():
    assert server.listen_failed("", None)
    assert server.listen_failed("disconnect the GBs", -1.4)
    assert not server.listen_failed("Show me the mug.", -0.3)
    assert not server.listen_failed("Yes.", None)


def test_two_bad_listens_give_the_ears_hint_once(quiet, monkeypatch):
    hear(monkeypatch, "", None)
    assert "EARS TROUBLE" not in server.listen()
    hear(monkeypatch, "it's a forever after disconnect the GBs", -1.5)
    out = server.listen()
    assert "EARS TROUBLE" in out and "step 'ears'" in out and "PC-LM1E Camera Mono" in out
    hear(monkeypatch, "", None)
    assert "EARS TROUBLE" not in server.listen()   # counter starts again


def test_a_good_listen_resets_the_count(quiet, monkeypatch):
    hear(monkeypatch, "", None)
    server.listen()
    hear(monkeypatch, "Take a look at this.", -0.2)
    server.listen()
    hear(monkeypatch, "", None)
    assert "EARS TROUBLE" not in server.listen()


# --- tune_up ears switches away from Bluetooth --------------------------------

@pytest.fixture
def silent_tuneup(monkeypatch):
    monkeypatch.setattr(tuneup.speaker, "say", lambda text, wait=False: 0.0)
    monkeypatch.setattr(tuneup.capslock, "set_mode", lambda m: None)
    monkeypatch.setattr(tuneup.mic, "record", lambda max_s=8: (b"\x00\x00", "silence"))
    monkeypatch.setattr(tuneup.mic, "transcribe", lambda pcm, context="": tuneup.EAR_TARGET)


def test_ears_switches_from_bluetooth_to_the_usb_mic(silent_tuneup, monkeypatch):
    monkeypatch.setattr(tuneup.mic, "status", bt_status)
    out = tuneup.ears()
    assert settings.load()["ears"]["source"] == CAM["name"]
    assert "switched from JBL Flip 5 (Bluetooth) to PC-LM1E Camera Mono" in out


def test_ears_keeps_bluetooth_when_there_is_nothing_better(silent_tuneup, monkeypatch):
    monkeypatch.setattr(tuneup.mic, "status", lambda: bt_status(alt=None))
    out = tuneup.ears()
    assert settings.load()["ears"]["source"] == ""
    assert "JBL Flip 5" in out and "switched" not in out


def test_tune_up_can_run_one_step(silent_tuneup, monkeypatch):
    monkeypatch.setattr(server.speaker, "wait_until_quiet", lambda timeout=120: None)
    assert server.tune_up(step="ears").startswith("ears: ok on try 1")


def test_hello_names_the_mic_when_the_webcam_is_missing(monkeypatch):
    said = []
    monkeypatch.setattr(server.speaker, "say", lambda text, wait=False: said.append(text) or 0.0)
    monkeypatch.setattr(server.capslock, "set_mode", lambda m: None)
    monkeypatch.setattr(server.intro, "save_seen", lambda seen: None)
    monkeypatch.setattr(server.intro, "load_seen", lambda: {"camera", "mic", "speaker", "capslock"})
    monkeypatch.setattr(server, "check_devices", lambda: {"camera": False, "mic": True,
                                                          "speaker": True, "capslock": True})
    dmic = {"name": "alsa_input.pci", "description": "Digital Microphone", "bus": "pci", "bluetooth": False}
    monkeypatch.setattr(server.mic, "status", lambda: {
        "source": dmic, "pin_missing": False, "pin": "", "alternative": None,
        "sink": "x", "sink_bluetooth": False})
    server.hello()
    assert "All my blocks are ready" not in said[0]
    assert "My camera isn't answering" in said[0] and "listening through Digital Microphone" in said[0]


# --- unplug the webcam = deaf, no fallback (a tester, 26 Nov 2026) ---------------

GONE = {"source": None, "pin_missing": True, "pin": "PC-LM1E", "alternative": None,
        "sink": "x", "sink_bluetooth": False}


def test_record_refuses_when_the_pinned_mic_is_gone(monkeypatch):
    settings.update("ears", source="PC-LM1E")
    monkeypatch.setattr(mic, "status", lambda: GONE)
    monkeypatch.setattr(mic.subprocess, "Popen", lambda *a, **k: pytest.fail("must not record"))
    assert mic.record(max_s=1) == (b"", "mic unplugged")


def test_listen_says_the_ears_are_unplugged(quiet, monkeypatch):
    said = []
    monkeypatch.setattr(server.speaker, "say", lambda text, wait=False: said.append(text) or 0.0)
    monkeypatch.setattr(server.mic, "record", lambda max_s: (b"", "mic unplugged"))
    assert server.listen().startswith("NOT LISTENING")
    assert said == ["My ears are unplugged. I can't hear anything."]


def test_mic_check_fails_when_the_pin_is_missing(monkeypatch):
    monkeypatch.setattr(server.mic, "status", lambda: GONE)
    assert server.check_devices()["mic"] is False


def test_unplug_promise_only_for_a_pinned_webcam_mic():
    pinned = {"source": CAM, "pin_missing": False, "pin": "PC-LM1E"}
    assert mic.unplug_makes_deaf(pinned)
    assert not mic.unplug_makes_deaf({**pinned, "pin": ""})            # not pinned: falls back
    assert not mic.unplug_makes_deaf({**pinned, "source": JBL})        # not the webcam


def test_intro_says_unplug_only_when_true(monkeypatch):
    said = []
    monkeypatch.setattr(server.speaker, "say", lambda text, wait=False: said.append(text) or 0.0)
    monkeypatch.setattr(server.capslock, "set_mode", lambda m: None)
    monkeypatch.setattr(server.intro, "save_seen", lambda seen: None)
    monkeypatch.setattr(server, "check_devices", lambda: dict.fromkeys(["camera", "mic", "speaker", "capslock"], True))
    for pin, want in (("PC-LM1E", True), ("", False)):
        monkeypatch.setattr(server.mic, "status", lambda: {
            "source": CAM, "pin_missing": False, "pin": pin, "alternative": None,
            "sink": "x", "sink_bluetooth": False})
        server.hello(full=True)
        assert ("Unplug the webcam and I can't see or hear you." in said[-1]) is want
