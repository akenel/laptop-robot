"""Per-learner settings found by tune_up, in ~/.config/laptop-robot/settings.json.

Defaults are the values tuned by hand on the reference laptop (25 Nov 2026), so a
fresh install behaves like the tested one until tune_up says otherwise.
"""

import copy
import json
import os
from pathlib import Path

DEFAULTS = {
    # keep_pictures: off by default (the intro promises "I don't keep pictures"). On for
    # rehearsals: every see image goes to ~/.config/laptop-robot/pictures/, and the intro
    # says so instead of the promise.
    "camera": {"gamma": 140, "brightness": -2, "keep_pictures": False},
    "voice": {"speed": 1.0, "max_words": 50},  # 35 for the 60-second film
    "capslock": {"visible": True},
    # Off by default: a robot that writes down everything it hears must be switched on
    # on purpose, and then says so in its intro.
    "transcript": {"enabled": False},
    # Names and places this person uses, added to every listen context so Whisper
    # hears "Oaxaca" and "Taranaki", not "wahaka" and "tara nacky".
    # source: pin a mic by part of its name ("PC-LM1E"); empty = the system default.
    "ears": {"vocabulary": [], "source": ""},
}


def path() -> Path:
    return Path(os.environ.get("LAPTOP_ROBOT_SETTINGS",
                               Path.home() / ".config/laptop-robot/settings.json"))


def load() -> dict:
    s = copy.deepcopy(DEFAULTS)
    try:
        saved = json.loads(path().read_text())
    except (OSError, ValueError):
        return s
    for section, values in saved.items():
        if isinstance(values, dict):
            s.setdefault(section, {}).update(values)
    return s


def save(s: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(s, indent=2) + "\n")


def update(section: str, **values) -> dict:
    s = load()
    s.setdefault(section, {}).update(values)
    save(s)
    return s
