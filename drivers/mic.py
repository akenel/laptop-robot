"""Ears: microphone via arecord, stop on silence, transcribe with faster-whisper.
Read-only: listen() -> text."""

import array
import math
import re
import shutil
import subprocess

RATE = 16000
CHUNK_MS = 30
CHUNK_BYTES = RATE * CHUNK_MS // 1000 * 2  # 16-bit mono
MODEL = "base.en"

_model = None
last_score: float | None = None  # mean Whisper avg_logprob of the last transcribe


# --- which microphone ------------------------------------------------------
# A Bluetooth speaker with a mic (a tester's JBL, 25 Nov 2026) becomes the default input
# and drops to the low-quality call profile: Grace heard "disconnect the GBs". So Grace
# says which mic she uses, and settings ears.source can pin one (a part of its name or
# description, e.g. "PC-LM1E"); a pinned mic is recorded with parecord -d.

def parse_sources(text: str) -> list[dict]:
    """`pactl list sources` -> [{name, description, bus, bluetooth}], monitors left out."""
    out = []
    for block in re.split(r"\n(?=Source #)", text):
        name = re.search(r"^\s*Name: (.+)$", block, re.M)
        if not name or name.group(1).endswith(".monitor"):
            continue
        desc = re.search(r"^\s*Description: (.+)$", block, re.M)
        bus = re.search(r'device\.bus = "([^"]+)"', block)
        n = name.group(1).strip()
        b = bus.group(1) if bus else ""
        out.append({"name": n, "description": desc.group(1).strip() if desc else n, "bus": b,
                    "bluetooth": n.startswith("bluez") or b == "bluetooth"})
    return out


def _pactl(*args: str) -> str:
    if not shutil.which("pactl"):
        return ""
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def choose(sources: list[dict], default: str, pin: str) -> tuple[dict | None, bool]:
    """(the mic Grace will use, whether a pin was set but not found)."""
    if pin:
        for s in sources:
            if pin.lower() in s["name"].lower() or pin.lower() in s["description"].lower():
                return s, False
    current = next((s for s in sources if s["name"] == default), None)
    return current, bool(pin)


def better_than_bluetooth(sources: list[dict]) -> dict | None:
    """A USB mic (usually the webcam's) to use instead of a Bluetooth one."""
    return next((s for s in sources if s["bus"] == "usb" and not s["bluetooth"]), None)


def status() -> dict:
    """Which mic Grace listens through: {source, pin_missing, alternative, sink}."""
    from drivers import settings
    srcs = parse_sources(_pactl("list", "sources"))
    pin = settings.load()["ears"].get("source", "")
    src, missing = choose(srcs, _pactl("get-default-source").strip(), pin)
    sink = _pactl("get-default-sink").strip()
    return {"source": src, "pin_missing": missing, "pin": pin,
            "alternative": better_than_bluetooth(srcs) if src and src["bluetooth"] else None,
            "sink": sink, "sink_bluetooth": sink.startswith("bluez")}


def record_command(pinned: str | None) -> list[str]:
    if pinned:
        return ["parecord", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1",
                "-d", pinned]
    return ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"]


class Unplugged(Exception):
    """The pinned mic is not there. No fallback: unplugging the webcam must make Grace
    deaf, not quietly switch to the laptop's own mic (a tester, 26 Nov 2026)."""


def _pinned_source() -> str | None:
    from drivers import settings
    if not settings.load()["ears"].get("source"):
        return None
    st = status()
    if st["pin_missing"] or not st["source"]:
        raise Unplugged(st["pin"])
    return st["source"]["name"]


def unplug_makes_deaf(st: dict) -> bool:
    """True when the ears are pinned to the webcam's own mic: unplug it = blind and deaf."""
    src = st["source"]
    return bool(st["pin"]) and not st["pin_missing"] and bool(src) and src["bus"] == "usb" \
        and "cam" in (src["name"] + src["description"]).lower()


def rms(chunk: bytes) -> float:
    a = array.array("h", chunk)
    if not a:
        return 0.0
    return math.sqrt(sum(x * x for x in a) / len(a))


class Endpointer:
    """Decides when an utterance is over, one chunk level at a time.

    - the first `calib` chunks measure the room's noise floor
    - speech starts after `start_chunks` loud chunks in a row
    - it ends after `silence_s` of quiet once speech started (1.5 s: 1.0 s cut the builder off
      mid-thought, "wire that up to the...")
    - gives up after `no_speech_s` with no speech, or `max_s` in total
    """

    def __init__(self, max_s=30.0, silence_s=1.5, no_speech_s=8.0,
                 calib=10, start_chunks=3, min_threshold=300.0, factor=3.0):
        per_s = 1000 / CHUNK_MS
        self.max_chunks = int(max_s * per_s)
        self.silence_chunks = int(silence_s * per_s)
        self.no_speech_chunks = int(no_speech_s * per_s)
        self.calib, self.start_chunks = calib, start_chunks
        self.min_threshold, self.factor = min_threshold, factor
        self.levels: list[float] = []
        self.threshold = min_threshold
        self.started = False
        self.loud_run = 0
        self.quiet_run = 0
        self.reason = ""

    def feed(self, level: float) -> bool:
        """Returns True when recording should stop."""
        self.levels.append(level)
        n = len(self.levels)
        if n <= self.calib:
            if n == self.calib:
                floor = sum(self.levels) / n
                self.threshold = max(self.min_threshold, floor * self.factor)
            return False
        loud = level >= self.threshold
        if not self.started:
            self.loud_run = self.loud_run + 1 if loud else 0
            if self.loud_run >= self.start_chunks:
                self.started = True
        else:
            self.quiet_run = 0 if loud else self.quiet_run + 1
            if self.quiet_run >= self.silence_chunks:
                self.reason = "silence"
                return True
        if not self.started and n >= self.no_speech_chunks:
            self.reason = "no speech"
            return True
        if n >= self.max_chunks:
            self.reason = "max length"
            return True
        return False


def record(max_s: float = 30.0) -> tuple[bytes, str]:
    """Record until the speaker stops. Returns (raw 16 kHz s16le audio, stop reason).
    Reason "mic unplugged" (and no audio) when the pinned mic is missing."""
    ep = Endpointer(max_s=max_s)
    try:
        pinned = _pinned_source()
    except Unplugged:
        return b"", "mic unplugged"
    p = subprocess.Popen(record_command(pinned), stdout=subprocess.PIPE)
    chunks = []
    try:
        while True:
            c = p.stdout.read(CHUNK_BYTES)
            if not c:
                ep.reason = "mic closed"
                break
            chunks.append(c)
            if ep.feed(rms(c)):
                break
    finally:
        p.terminate()
        p.wait(timeout=5)
    return b"".join(chunks), ep.reason


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    return _model


def transcribe(pcm: bytes, context: str = "") -> str:
    """context: words the person is likely to say ("polka-dot mug, cup"). Whisper uses
    it as initial_prompt, which steers it toward those words ("mug", not "mud")."""
    import numpy as np
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    global last_score
    segs, _ = _get_model().transcribe(
        audio, beam_size=1, language="en", vad_filter=True,
        initial_prompt=context.strip() or None,
        # Guard against the "I I I I I..." loop seen on unclear audio (25 Nov 2026).
        condition_on_previous_text=False, no_repeat_ngram_size=3)
    segs = list(segs)
    scores = [getattr(s, "avg_logprob", 0.0) for s in segs]
    last_score = sum(scores) / len(scores) if scores else None
    return " ".join(s.text.strip() for s in segs).strip()


def listen(max_s: float = 30.0, context: str = "") -> tuple[str, str]:
    """Returns (text, stop reason)."""
    pcm, reason = record(max_s)
    return transcribe(pcm, context), reason
