"""Grace's intro: full the first time, only what is new later, honest about broken parts."""

import random
from pathlib import Path

import yaml

from mcp_server import intro, server

ROOT = Path(__file__).resolve().parent.parent
ROBOT = yaml.safe_load((ROOT / "robot.yaml").read_text())
DEVICES = server.load_devices()
ALL_OK = {d["name"]: True for d in DEVICES}


def say(seen, checks=ALL_OK, full=False, seed=1):
    return intro.build(ROBOT, DEVICES, set(seen), checks, full, random.Random(seed))


def test_first_start_is_the_full_intro():
    text, seen = say([])
    assert text.startswith("Hello. My name is Grace.")
    for d in DEVICES:
        assert d["intro"].strip() in text
    assert "I don't keep pictures" in text
    assert "I only listen while my light is on solid." in text
    assert seen == {d["name"] for d in DEVICES}


def test_nothing_new_is_one_line_and_a_question():
    text, _ = say(ALL_OK)
    assert text.startswith("Hi, it's Grace. All my blocks are ready.")
    assert "webcam" not in text
    assert text.split(". ")[-1].rstrip("?.") in " ".join(ROBOT["questions"] + ROBOT["look_questions"])


def test_no_show_me_question_when_the_camera_is_down():
    """26 Nov 2026: "Show me the oldest thing within reach" with the webcam unplugged."""
    for seed in range(30):
        text, _ = say(ALL_OK, {**ALL_OK, "camera": False}, seed=seed)
        assert not any(q in text for q in ROBOT["look_questions"])
        assert any(q in text for q in ROBOT["questions"])


def test_a_new_block_is_introduced_alone():
    neck = {"name": "neck", "tool": "turn", "description": "x",
            "intro": "My neck is a servo. I can look left and right."}
    text, seen = intro.build(ROBOT, DEVICES + [neck], set(ALL_OK), {**ALL_OK, "neck": True},
                             rng=random.Random(1))
    assert "New since last time: neck." in text and "My neck is a servo." in text
    assert "webcam" not in text
    assert "neck" in seen


def test_full_on_request():
    text, _ = say(ALL_OK, full=True)
    assert text.startswith("Hello. My name is Grace.")


def test_broken_part_is_admitted_and_its_promises_dropped():
    checks = {**ALL_OK, "capslock": False}
    text, seen = say([], checks)
    assert "My capslock isn't answering right now." in text
    assert "heartbeat" not in text
    assert "light is on solid" not in text  # that promise needs the LED
    assert "capslock" not in seen            # introduce it once it works


def test_question_varies():
    texts = {say(ALL_OK, seed=s)[0] for s in range(20)}
    assert len(texts) >= 4


def test_state_round_trip(tmp_path):
    p = tmp_path / "state.json"
    assert intro.load_seen(p) == set()
    intro.save_seen({"camera", "mic"}, p)
    assert intro.load_seen(p) == {"camera", "mic"}


def test_intro_order_is_eyes_ears_voice_heartbeat():
    text, _ = say([])
    pos = [text.index(w) for w in ("webcam", "microphone", "Kokoro", "Caps Lock")]
    assert pos == sorted(pos)


def test_instructions_carry_the_character():
    text = server.build_instructions()
    assert text.startswith("You are Grace")
    assert "never creepy" in text and "only what you really saw" in text
    assert "Consider my light blinking a nod." in text
    assert "first speak what you are about to do" in text
    assert "ask out loud and wait for a clear yes" in text
    assert "R1. " in text and "R16. " in text
