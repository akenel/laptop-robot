"""Opt-in conversation transcript: settings transcript.enabled = true.

One JSON line per turn in ~/.config/laptop-robot/transcripts/YYYY-MM-DD.jsonl (local only,
never sent anywhere). examples/transcript.py turns a day into an HTML page.
"""

import json
import os
import time
from pathlib import Path

from drivers import settings

NOTE = "I'm keeping a written transcript of what we say, on this laptop only."


def directory() -> Path:
    return Path(os.environ.get("LAPTOP_ROBOT_TRANSCRIPTS",
                               Path.home() / ".config/laptop-robot/transcripts"))


def enabled() -> bool:
    return bool(settings.load()["transcript"]["enabled"])


def add(who: str, text: str, **extra) -> None:
    if not enabled() or not text:
        return
    d = directory()
    d.mkdir(parents=True, exist_ok=True)
    line = {"time": time.strftime("%H:%M:%S"), "who": who, "text": text, **extra}
    with open(d / f"{time.strftime('%Y-%m-%d')}.jsonl", "a") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
