"""settings camera.keep_pictures: off = nothing saved and the intro promises it; on = every
see image saved for inspection, and the intro says so instead (27 Nov 2026, rehearsals)."""

import pytest

from drivers import camera, settings
from mcp_server import server


@pytest.fixture
def robot(monkeypatch, tmp_path):
    monkeypatch.setenv("LAPTOP_ROBOT_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("LAPTOP_ROBOT_PICTURES", str(tmp_path / "pictures"))
    monkeypatch.setattr(server.capslock, "set_mode", lambda m: None)
    monkeypatch.setattr(server.speaker, "is_speaking", lambda: False)
    monkeypatch.setattr(server.speaker, "say", lambda text, wait=False: 0.0)
    monkeypatch.setattr(server.camera, "photo", lambda: b"\xff\xd8photo")
    return tmp_path


def test_off_by_default_nothing_saved(robot):
    server.TOOLS["see"]()
    assert not (robot / "pictures").exists()


def test_on_saves_what_the_model_saw(robot):
    settings.update("camera", keep_pictures=True)
    server.TOOLS["see"]()
    saved = list((robot / "pictures").glob("*-photo.jpg"))
    assert len(saved) == 1 and saved[0].read_bytes() == b"\xff\xd8photo"


def test_intro_never_promises_what_is_not_true(robot, monkeypatch):
    monkeypatch.setattr(server.intro, "load_seen", lambda: set())
    monkeypatch.setattr(server.intro, "save_seen", lambda seen: None)
    monkeypatch.setattr(server, "check_devices", lambda: {"camera": True, "mic": True, "speaker": True, "capslock": True})
    said = []
    monkeypatch.setattr(server.speaker, "say", lambda text, wait=False: said.append(text) or 0.0)
    server.hello(full=True)
    assert "I don't keep pictures" in said[-1] and server.KEEP_NOTE not in said[-1]
    settings.update("camera", keep_pictures=True)
    server.hello(full=True)
    assert "I don't keep pictures" not in said[-1] and server.KEEP_NOTE in said[-1]


def test_keep_pictures_is_never_sent_to_the_webcam():
    args = camera.controls_args(dev="/dev/video9", controls={"gamma": 140, "keep_pictures": True})
    assert args == ["v4l2-ctl", "-d", "/dev/video9", "-c", "gamma=140"]


def test_see_tells_the_model_where_the_picture_is(robot):
    """27 Nov 2026: asked where, gemma invented "the media folder" and offered an old file."""
    settings.update("camera", keep_pictures=True)
    out = server.TOOLS["see"]()
    saved = next((robot / "pictures").glob("*-photo.jpg"))
    assert isinstance(out, list) and f"kept as {saved}" in out[0]


def test_no_path_note_when_not_keeping(robot):
    out = server.TOOLS["see"]()
    assert not isinstance(out, list)
