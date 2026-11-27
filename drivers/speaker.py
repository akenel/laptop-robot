"""Voice: text-to-speech played with aplay. Write-only: say(text, wait=False).

Default voice "Grace" = Kokoro af_bella (chosen by ear, 25 Nov 2026). Piper is the
light fallback. Pick with LAPTOP_ROBOT_VOICE="kokoro:af_bella" or "piper:en_US-lessac-medium".

Speech is generated one sentence at a time and streamed into a single aplay, so the
first word comes after ~1 sentence of synthesis, not the whole text.
"""

import io
import os
import queue
import re
import subprocess
import threading
import wave

VOICE = os.environ.get("LAPTOP_ROBOT_VOICE", "kokoro:af_bella")
PIPER_DIR = os.path.expanduser("~/.local/share/piper-voices")
KOKORO_DIR = os.path.expanduser("~/.local/share/kokoro")
SENTENCE_PAUSE_S = 0.15

_engines: dict = {}
_lock = threading.Lock()          # one utterance at a time


def parse_voice(spec: str) -> tuple[str, str]:
    engine, _, name = spec.partition(":")
    if engine not in ("kokoro", "piper") or not name:
        raise ValueError(f"voice must look like 'kokoro:af_bella' or 'piper:en_US-lessac-medium', not {spec!r}")
    return engine, name


def voice_file_ok(spec: str = VOICE) -> bool:
    engine, name = parse_voice(spec)
    if engine == "kokoro":
        return all(os.path.exists(f"{KOKORO_DIR}/{f}") for f in ("kokoro-v1.0.onnx", "voices-v1.0.bin"))
    return os.path.exists(f"{PIPER_DIR}/{name}.onnx")


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def float_to_int16(samples) -> bytes:
    import numpy as np
    return (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


def _synth_sentence(sentence: str, spec: str = VOICE) -> tuple[bytes, int]:
    """Raw 16-bit mono PCM and its sample rate."""
    engine, name = parse_voice(spec)
    if engine == "kokoro":
        if "kokoro" not in _engines:
            from kokoro_onnx import Kokoro
            _engines["kokoro"] = Kokoro(f"{KOKORO_DIR}/kokoro-v1.0.onnx", f"{KOKORO_DIR}/voices-v1.0.bin")
        from drivers import settings
        speed = settings.load()["voice"]["speed"]  # tune_up: 0.9 slower, 1.1 faster
        samples, rate = _engines["kokoro"].create(sentence, voice=name, speed=speed, lang="en-us")
        return float_to_int16(samples), rate
    if name not in _engines:
        from piper import PiperVoice
        _engines[name] = PiperVoice.load(f"{PIPER_DIR}/{name}.onnx")
    chunks = list(_engines[name].synthesize(sentence))
    return b"".join(c.audio_int16_bytes for c in chunks), chunks[0].sample_rate


def synth(text: str, spec: str = VOICE) -> bytes:
    """Whole text as WAV bytes (for files and tests); say() streams instead."""
    pcm, rate = [], 22050
    for s in split_sentences(text):
        p, rate = _synth_sentence(s, spec)
        pcm.append(p)
    silence = b"\x00\x00" * int(rate * SENTENCE_PAUSE_S)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(silence.join(pcm))
    return buf.getvalue()


def _stream(sentences: list[str], first: tuple[bytes, int]) -> None:
    """Runs in a thread; the caller holds _lock. Synthesises sentence n+1 while n plays."""
    try:
        pcm, rate = first
        player = subprocess.Popen(
            ["aplay", "-q", "-f", "S16_LE", "-r", str(rate), "-c", "1", "-t", "raw", "-"],
            stdin=subprocess.PIPE)
        silence = b"\x00\x00" * int(rate * SENTENCE_PAUSE_S)
        q: queue.Queue = queue.Queue()

        def produce():
            for s in sentences:
                q.put(_synth_sentence(s)[0])
            q.put(None)
        threading.Thread(target=produce, daemon=True).start()
        try:
            player.stdin.write(pcm)
            while (nxt := q.get()) is not None:
                player.stdin.write(silence + nxt)
            player.stdin.close()
        except BrokenPipeError:
            pass
        player.wait()
    finally:
        _lock.release()


def say(text: str, wait: bool = False) -> float:
    """Speak `text`. Returns roughly how long it will take, in seconds.
    wait=False returns as soon as the first sentence starts playing.
    A second call waits for the first utterance to finish."""
    sentences = split_sentences(text)
    if not sentences:
        return 0.0
    # Taken BEFORE synthesis: the first sentence takes ~0.6-1.4 s to synthesise, and a
    # listen in that gap would record Grace's own voice (26 Nov 2026).
    _lock.acquire()
    try:
        first = _synth_sentence(sentences[0])
    except BaseException:
        _lock.release()
        raise
    t = threading.Thread(target=_stream, args=(sentences[1:], first), daemon=True)
    t.start()
    if wait:
        t.join()
    return len(text.split()) / 2.6  # ~2.6 words per second


def is_speaking() -> bool:
    return _lock.locked()


def wait_until_quiet(timeout: float = 120) -> None:
    if _lock.acquire(timeout=timeout):
        _lock.release()
