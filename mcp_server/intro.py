"""Grace introduces herself, built from robot.yaml + devices/*.yaml.

- first start:            full intro (every block, what she won't do), then a question
- a new block since last: only the new block(s)
- nothing new:            one line, plus any device that does not answer
- full=True:              the full intro again, on request

Pure functions here; the server does the device checks, the speaking and the saving.
"""

import json
import os
import random
from pathlib import Path

STATE_FILE = Path(os.environ.get(
    "LAPTOP_ROBOT_STATE", Path.home() / ".config/laptop-robot/state.json"))


def load_seen(path: Path = STATE_FILE) -> set[str]:
    try:
        return set(json.loads(path.read_text()).get("introduced", []))
    except (OSError, ValueError):
        return set()


def save_seen(seen: set[str], path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"introduced": sorted(seen)}, indent=2) + "\n")


def _wont_lines(items, checks: dict[str, bool]) -> list[str]:
    out = []
    for w in items or []:
        if isinstance(w, str):
            out.append(w)
        elif checks.get(w.get("needs", ""), True):
            out.append(w["text"])
    return out


def build(robot: dict, devices: list[dict], seen: set[str], checks: dict[str, bool],
          full: bool = False, rng: random.Random | None = None,
          notes: list[str] | None = None) -> tuple[str, set[str]]:
    """Returns (what Grace says, the devices she has now introduced)."""
    rng = rng or random.Random()
    order = robot.get("order", [])
    devices = sorted(devices, key=lambda d: (order.index(d["name"]) if d["name"] in order
                                             else len(order), d["name"]))
    working = [d for d in devices if checks.get(d["name"], True)]
    broken = [d for d in devices if not checks.get(d["name"], True)]
    new = [d for d in working if d["name"] not in seen]
    first = full or not seen
    parts = []

    if first:
        parts.append(robot["greeting_first"].strip())
        parts += [d["intro"].strip() for d in working]
        parts += _wont_lines(robot.get("wont"), checks)
        for d in working:
            parts += _wont_lines(d.get("wont"), checks)
    else:
        parts.append(robot["greeting_again"].strip())
        if new:
            names = " and ".join(d["name"] for d in new)
            parts.append(f"New since last time: {names}.")
            parts += [d["intro"].strip() for d in new]
            for d in new:
                parts += _wont_lines(d.get("wont"), checks)
        elif not broken:
            parts.append("All my blocks are ready.")

    for d in broken:
        parts.append(f"My {d['name']} isn't answering right now.")

    parts += notes or []  # e.g. "I'm keeping a written transcript", always said, every start
    if first and not full and robot.get("tune_question"):
        parts.append(robot["tune_question"].strip())
    else:
        pool = list(robot["questions"])
        if checks.get("camera", True):
            pool += robot.get("look_questions", [])
        parts.append(rng.choice(pool))
    return " ".join(parts), seen | {d["name"] for d in working}
