import pytest


@pytest.fixture(autouse=True)
def private_settings(tmp_path, monkeypatch):
    """No test reads or writes the real ~/.config/laptop-robot/settings.json."""
    monkeypatch.setenv("LAPTOP_ROBOT_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("LAPTOP_ROBOT_TRANSCRIPTS", str(tmp_path / "transcripts"))


WEBCAM = {"name": "alsa_input.usb-cam", "description": "PC-LM1E Camera Mono", "bus": "usb",
          "bluetooth": False}


@pytest.fixture(autouse=True)
def plain_mic(monkeypatch):
    """No test asks the real PipeWire which mic is plugged in."""
    from drivers import mic
    monkeypatch.setattr(mic, "status", lambda: {
        "source": WEBCAM, "pin_missing": False, "pin": "", "alternative": None,
        "sink": "alsa_output.pci-speaker", "sink_bluetooth": False})
    monkeypatch.setattr(mic, "last_score", None)
