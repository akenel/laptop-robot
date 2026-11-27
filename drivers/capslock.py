"""Heartbeat: the Caps Lock LED. Write-only: set_mode("off"|"on"|"fast"|"slow").

fast = recording (eyes or ears open), slow = thinking.
The LED files are root-only until the udev rule in image/ is installed; without it
this driver warns once on stderr and does nothing, so the head still works.
"""

import glob
import sys
import threading

LED_GLOB = "/sys/class/leds/*::capslock/brightness"
PERIODS = {"fast": 0.1, "slow": 0.5}  # seconds per on/off half-cycle
MODES = ("off", "on", "fast", "slow")

_mode = "off"
_wake = threading.Event()
_thread: threading.Thread | None = None
_warned = False
_lock = threading.Lock()


def led_paths(pattern: str = LED_GLOB) -> list[str]:
    return sorted(glob.glob(pattern))


def _write(on: bool) -> None:
    global _warned
    for p in led_paths():
        try:
            with open(p, "w") as f:
                f.write("1" if on else "0")
        except OSError as e:
            if not _warned:
                print(f"capslock: cannot write {p} ({e}); install image/90-laptop-robot-capslock.rules",
                      file=sys.stderr)
                _warned = True


def _run() -> None:
    lit = False
    while True:
        mode = _mode
        if mode in PERIODS:
            lit = not lit
            _write(lit)
            _wake.wait(PERIODS[mode])
        else:
            lit = mode == "on"
            _write(lit)
            _wake.wait()
        _wake.clear()


def set_mode(mode: str) -> None:
    global _mode, _thread
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
    with _lock:
        _mode = mode
        if _thread is None:
            _thread = threading.Thread(target=_run, daemon=True, name="capslock")
            _thread.start()
    _wake.set()


def get_mode() -> str:
    return _mode
