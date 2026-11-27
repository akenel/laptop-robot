"""Eyes: USB webcam via ffmpeg. Read-only: photo() and watch() return JPEG bytes."""

import glob
import subprocess
import tempfile
from pathlib import Path

FALLBACK_DEVICE = "/dev/video0"


def device() -> str:
    """The webcam by its stable name. /dev/videoN renumbers when the camera is replugged
    (video0 became video1 on 26 Nov 2026 and see failed for the rest of the session)."""
    links = sorted(glob.glob("/dev/v4l/by-id/*-video-index0"))
    return links[0] if links else FALLBACK_DEVICE

SIZE = (1280, 720)
WARMUP_FRAMES = 30  # the first frames are overexposed; ~1 s at 30 fps
# MJPEG, not the default raw YUYV: 1.3 s vs 3.7 s per photo (raw runs at ~10 fps)


# Exposure controls come from settings (tune_up adjusts them). The default, gamma 140 /
# brightness -2, was picked by eye on 25 Nov 2026: gamma 188 blew out white objects
# under a desk lamp, 110 was too dark.
LIMITS = {"gamma": (100, 200), "brightness": (-10, 10)}
TOO_BRIGHT_CLIPPED = 0.03   # more than 3 % of pixels at full white
TOO_DARK_MEAN = 60          # mean grey level out of 255


def current_controls() -> dict:
    from drivers import settings
    return settings.load()["camera"]


# Settings in the camera section that are NOT webcam controls; never sent to v4l2-ctl.
NOT_CONTROLS = {"keep_pictures"}


def controls_args(dev: str | None = None, controls: dict | None = None) -> list[str]:
    args = ["v4l2-ctl", "-d", dev or device()]
    for k, v in (controls if controls is not None else current_controls()).items():
        if k not in NOT_CONTROLS:
            args += ["-c", f"{k}={v}"]
    return args


def apply_controls(controls: dict | None = None) -> None:
    """Best effort: a camera without these controls still takes pictures."""
    subprocess.run(controls_args(controls=controls), capture_output=True, timeout=5)


def brightness_stats(jpeg: bytes) -> dict:
    """Mean grey level (0-255) and the share of blown-out pixels, from a small grey copy."""
    import numpy as np
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", "-", "-vf", "scale=160:90,format=gray",
         "-f", "rawvideo", "-"], input=jpeg, capture_output=True, check=True, timeout=10).stdout
    px = np.frombuffer(raw, dtype=np.uint8)
    return {"mean": float(px.mean()), "clipped": float((px >= 250).mean())}


def next_controls(stats: dict, controls: dict) -> tuple[dict, str]:
    """One tuning step. Returns (new controls, verdict): 'ok', 'brighter', 'darker',
    'too dark' or 'too bright' (the last two: at the limit, the room needs a change)."""
    c = dict(controls)
    lo_g, hi_g = LIMITS["gamma"]
    lo_b, hi_b = LIMITS["brightness"]
    if stats["clipped"] > TOO_BRIGHT_CLIPPED:
        if c["gamma"] <= lo_g and c["brightness"] <= lo_b:
            return c, "too bright"
        c["gamma"] = max(lo_g, c["gamma"] - 20)
        c["brightness"] = max(lo_b, c["brightness"] - 1)
        return c, "darker"
    if stats["mean"] < TOO_DARK_MEAN:
        if c["gamma"] >= hi_g and c["brightness"] >= hi_b:
            return c, "too dark"
        c["gamma"] = min(hi_g, c["gamma"] + 20)
        c["brightness"] = min(hi_b, c["brightness"] + 1)
        return c, "brighter"
    return c, "ok"


def photo_args(out: str, dev: str | None = None) -> list[str]:
    w, h = SIZE
    dev = dev or device()
    return [
        "ffmpeg", "-loglevel", "error",
        "-f", "v4l2", "-input_format", "mjpeg", "-video_size", f"{w}x{h}", "-i", dev,
        "-vf", f"select=gte(n\\,{WARMUP_FRAMES})",
        "-frames:v", "1", "-y", out,
    ]


def watch_args(out: str, seconds: float = 6, cols: int = 3, rows: int = 3,
               dev: str | None = None) -> list[str]:
    """cols*rows frames spread evenly over `seconds`, stitched into one SIZE image."""
    w, h = SIZE
    dev = dev or device()
    frames = cols * rows
    fps = frames / seconds
    vf = (f"select=gte(n\\,{WARMUP_FRAMES}),fps={fps:g},"
          f"scale={w // cols}:{h // rows},tile={cols}x{rows}")
    return [
        "ffmpeg", "-loglevel", "error",
        "-f", "v4l2", "-input_format", "mjpeg", "-video_size", f"{w}x{h}", "-i", dev,
        "-t", f"{seconds + 1.5:g}",  # + warm-up and slack
        "-vf", vf, "-frames:v", "1", "-y", out,
    ]


def watch_note(seconds: float = 6, cols: int = 3, rows: int = 3) -> str:
    frames = cols * rows
    return (f"This image is a grid of {frames} webcam frames from {seconds:g} seconds, "
            f"in time order: left to right, top to bottom, about "
            f"{seconds / frames:.1f} s apart. Describe only what is really visible.")


def _capture(args_for, timeout: float) -> bytes:
    apply_controls()
    with tempfile.TemporaryDirectory() as d:
        out = str(Path(d) / "frame.jpg")
        subprocess.run(args_for(out), check=True, capture_output=True, timeout=timeout)
        return Path(out).read_bytes()


def photo() -> bytes:
    return _capture(photo_args, timeout=15)


def watch(seconds: float = 6) -> bytes:
    return _capture(lambda out: watch_args(out, seconds), timeout=seconds + 15)
