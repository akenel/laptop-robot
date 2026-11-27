"""laptop-robot MCP server: exposes the head's drivers as tools to any MCP agent.

Registry: every devices/*.yaml names a tool; TOOLS maps that name to a function here.
Adding a device later = one YAML file + one driver + one entry in TOOLS.

Signal standard (Caps Lock LED), "no action without a signal":
    solid       your turn: the person talks or shows something (listen)
    slow blink  Grace is thinking (between tool calls, transcribing)
    fast blink  Grace is acting: watching, speaking, later moving
    off         idle, after IDLE_S without a tool call
"""

import functools
import os
import random
import subprocess
import threading
import time
from pathlib import Path
from typing import Literal

import yaml

from mcp_server import agents_md
from mcp.server.mcpserver import Image, MCPServer

from drivers import camera, capslock, mic, settings, speaker
from mcp_server import intro, transcript, tuneup

ROBOT_FILE = Path(__file__).resolve().parent.parent / "robot.yaml"

DEVICES_DIR = Path(__file__).resolve().parent.parent / "devices"
# Slow blink ("thinking") lasts until the next robot tool call, or IDLE_S. Not too short:
# the agent may be busy with tools the robot cannot see (web search, files), and a dark LED
# after 30 s looked dead (25 Nov 2026). Not 5 min either: twice on 26-27 Nov the agent had
# simply stopped, and the light blinked "thinking" into an empty room. R14 now caps outside
# work at two searches per question, so 90 s.
IDLE_S = 90.0

YOUR_TURN, THINKING, ACTING, IDLE = "on", "slow", "fast", "off"

_idle_timer: threading.Timer | None = None
_timer_lock = threading.Lock()
_call_no = 0  # bumps on every tool call, so a stale "thinking" never overwrites a newer state


def _cancel_idle() -> None:
    global _idle_timer
    with _timer_lock:
        if _idle_timer:
            _idle_timer.cancel()
            _idle_timer = None


# Progress lines: when the person is waiting (the last robot tool was listen or see, so
# Grace has input she has not answered yet) and no robot tool is called for PROGRESS_S,
# the server says "Still working on it." itself, at most PROGRESS_MAX times. After speak,
# Grace has answered, so nothing is said: no "still working" after a goodbye.
PROGRESS_S = 20.0
PROGRESS_MAX = 3
_last_tool = ""


def progress_line(n: int) -> str:
    lines = yaml.safe_load(ROBOT_FILE.read_text()).get("progress_lines") or ["Still working on it."]
    return lines[min(n, len(lines) - 1)]


def stalled_line() -> str:
    return yaml.safe_load(ROBOT_FILE.read_text()).get("stalled_line") or ""


def _progress(call_no: int, n: int) -> None:
    if call_no != _call_no or _last_tool not in ("listen", "see", "speak_busy"):
        return
    if n >= PROGRESS_MAX:
        # Three progress lines and still no tool call: the agent has most likely stopped.
        # Say so, tell the person how to wake it, and stop pretending to think.
        _cancel_idle()
        if stalled_line() and not speaker.is_speaking():
            speaker.say(stalled_line())
        capslock.set_mode(IDLE)
        return
    if not speaker.is_speaking():
        speaker.say(progress_line(n))
        capslock.set_mode(THINKING)
    t = threading.Timer(PROGRESS_S, _progress, args=(call_no, n + 1))
    t.daemon = True
    t.start()


def _thinking(call_no: int | None = None) -> None:
    """Slow blink until the next call, or off after IDLE_S; progress lines if someone waits."""
    global _idle_timer
    capslock.set_mode(THINKING)
    with _timer_lock:
        _idle_timer = threading.Timer(IDLE_S, capslock.set_mode, args=(IDLE,))
        _idle_timer.daemon = True
        _idle_timer.start()
    if call_no is not None:
        t = threading.Timer(PROGRESS_S, _progress, args=(call_no, 0))
        t.daemon = True
        t.start()


def _after_tool(call_no: int) -> None:
    """When a tool returns, Grace is thinking. But if she is still speaking, she is
    still acting: keep the fast blink until she is quiet, then think."""
    def run():
        if speaker.is_speaking():
            speaker.wait_until_quiet()
        if call_no == _call_no:
            _thinking(call_no)
    threading.Thread(target=run, daemon=True).start()


# One robot tool at a time, enforced here, not in the prompt. OpenCode + gemma called
# speak and listen in parallel (49 ms apart, every turn): listen started before the voice
# did and recorded Grace herself, so she thought she was "mirroring" (26 Nov 2026).
# A first-come-first-served queue (a plain lock does not keep arrival order), re-entrant: a
# tool may call another wrapped tool in the same thread.
#
# A speak that ARRIVES while another speak is still queued or running was sent in the same
# batch, before the agent saw the results in between. gemma did exactly that: speak "I'll
# create it", write, speak "Done! I've written the file" in one batch; the write was rejected
# and the file never existed (27 Nov 2026, rule R11). So the second speak is refused, and the
# listen after it too (_speak_refused). Only speak after speak: the first version refused a
# speak arriving behind ANY tool, and blocked the cue "hold it an arm's length" when see
# reached the server 4 ms before it (27 Nov 2026).
_queue = threading.Condition()
_next_ticket = 0
_serving = 0
_owner: int | None = None
_depth = 0
_speaks_in_flight = 0

BATCHED_SPEAK = ("NOT SPOKEN: this speak was sent together with another tool call, before "
                 "you saw its result. Wait for the results, then speak only what really "
                 "happened.")


def _enter(is_speak: bool = False) -> bool:
    """Wait for our turn. Returns True for a speak that arrived while another speak was
    queued or running (sent in the same batch)."""
    global _next_ticket, _owner, _depth, _speaks_in_flight
    me = threading.get_ident()
    with _queue:
        if _owner == me:  # a tool calling another tool: not a batch
            _depth += 1
            _speaks_in_flight += is_speak
            return False
        batched = is_speak and _speaks_in_flight > 0
        if is_speak:
            _speaks_in_flight += 1
        ticket = _next_ticket
        _next_ticket += 1
        while _serving != ticket or _owner is not None:
            _queue.wait()
        _owner, _depth = me, 1
        return batched


def _leave(is_speak: bool = False) -> None:
    global _serving, _owner, _depth, _speaks_in_flight
    with _queue:
        _depth -= 1
        if is_speak:
            _speaks_in_flight -= 1
        if _depth == 0:
            _owner = None
            _serving += 1
            _queue.notify_all()


def heartbeat(fn, think_after: bool = True, name: str = ""):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        global _call_no, _last_tool, _speak_refused
        is_speak = fn is speak
        batched = _enter(is_speak)
        try:
            _cancel_idle()
            _call_no += 1
            _last_tool = name or fn.__name__
            me = _call_no
            try:
                if batched:
                    _speak_refused = True
                    return BATCHED_SPEAK
                return fn(*args, **kwargs)
            finally:
                if think_after:
                    _after_tool(me)
        finally:
            _leave(is_speak)
    return wrapper


# --- tools ------------------------------------------------------------------

CUT_LINE = "Got it."
_last_thinking_line = ""


def thinking_line(rng: random.Random | None = None) -> str:
    """A random 'I'm thinking' line from robot.yaml, never the same twice in a row."""
    global _last_thinking_line
    lines = yaml.safe_load(ROBOT_FILE.read_text()).get("thinking_lines") or [""]
    choices = [l for l in lines if l != _last_thinking_line] or lines
    _last_thinking_line = (rng or random).choice(choices)
    return _last_thinking_line


KEEP_NOTE = "I'm keeping my pictures on this laptop, so you can look at them later."


def pictures_dir() -> Path:
    return Path(os.environ.get("LAPTOP_ROBOT_PICTURES",
                               Path.home() / ".config/laptop-robot/pictures"))


def keeping_pictures() -> bool:
    return bool(settings.load()["camera"].get("keep_pictures"))


def keep_picture(jpeg: bytes, mode: str) -> Path | None:
    """Only with settings camera.keep_pictures on (rehearsals): save what the model saw.
    Returns the path, so see can tell the model where it is: without it, gemma invented
    "the media folder" and offered an old test image instead (27 Nov 2026)."""
    if not keeping_pictures():
        return None
    d = pictures_dir()
    d.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    out = d / f"{stamp}-{mode}.jpg"
    out.write_bytes(jpeg)
    return out


def kept_note(path: Path | None) -> str:
    return f"(This picture is kept as {path}. Say that path if the person asks where.)" if path else ""


def see(mode: Literal["photo", "watch"] = "photo", ready_seconds: float | None = None,
        think_aloud: bool = True):
    """Take a photo, or watch for 6 seconds and get a 3x3 grid of frames.

    Watch runs like a film set: wait until Grace has finished her cue, then READY
    (LED solid, the person gets into position), ACTION (LED fast, recording), CUT
    (Grace says "Got it.", so the person knows they can relax)."""
    if ready_seconds is None:
        ready_seconds = 3.0 if mode == "watch" else 0.0
    if speaker.is_speaking():
        capslock.set_mode(ACTING)
        speaker.wait_until_quiet()
    if ready_seconds > 0:
        capslock.set_mode(YOUR_TURN)
        time.sleep(ready_seconds)
    capslock.set_mode(ACTING)
    try:
        shot = camera.watch() if mode == "watch" else camera.photo()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        why = (getattr(e, "stderr", b"") or b"").decode(errors="replace").strip()[-200:]
        return (f"NO PICTURE: the camera ({camera.device()}) did not deliver an image"
                f"{': ' + why if why else ''}. You saw nothing, so describe nothing. Say "
                "your eyes are not working and ask the person to check the webcam's USB "
                "cable. Do not try to fix drivers or run sudo.")
    kept = kept_note(keep_picture(shot, mode))
    if mode == "watch":
        speaker.say(f"{CUT_LINE} {thinking_line()}" if think_aloud else CUT_LINE)
        return [" ".join(x for x in (camera.watch_note(), kept) if x), Image(data=shot, format="jpeg")]
    photo = shot
    if think_aloud:
        speaker.say(thinking_line())
    return [kept, Image(data=photo, format="jpeg")] if kept else Image(data=photo, format="jpeg")


_speak_refused = False
QUESTION_STARTS = ("what", "how", "why", "when", "where", "who", "which", "can", "could",
                   "would", "should", "do", "does", "did", "is", "are", "will", "tell", "explain")


def is_real_question(text: str) -> bool:
    """Worth a 'let me think' line: a question of more than four words."""
    words = text.lower().split()
    return len(words) > 4 and (text.strip().endswith("?") or words[0].strip(",.") in QUESTION_STARTS)


def pondering_line() -> str:
    lines = yaml.safe_load(ROBOT_FILE.read_text()).get("pondering_lines") or ["One moment."]
    return random.choice(lines)


# Two bad listens in a row (nothing heard, or Whisper unsure) = maybe the wrong mic
# (Run 2: a Bluetooth speaker's phone mic). The agent is told to offer an ears check.
# UNSURE_SCORE is a first guess for Whisper's mean avg_logprob, not calibrated yet.
UNSURE_SCORE = -1.0
FAILS_BEFORE_HINT = 2
_failed_listens = 0


def listen_failed(text: str, score: float | None) -> bool:
    return not text.strip() or (score is not None and score < UNSURE_SCORE)


def mic_line(st: dict) -> str:
    src = st["source"]
    if not src:
        return "mic: unknown"
    return f"mic: {src['description']}" + (", Bluetooth" if src["bluetooth"] else "")


def ears_warning(st: dict) -> str:
    """A spoken sentence when the mic is likely wrong, else ''."""
    src = st["source"]
    if st["pin_missing"]:
        return f"My ears are unplugged: {st['pin']} isn't there, so I can't hear anything."
    if src and src["bluetooth"]:
        alt = st["alternative"]
        return (f"I'm listening through {src['description']}, a Bluetooth phone mic, and those "
                "hear badly. " + (f"Ask me to tune up and I'll switch to {alt['description']}."
                                  if alt else "A webcam or USB mic works much better."))
    return ""


def listen(max_seconds: float = 30, context: str = "", think_aloud: bool = True) -> str:
    """Listen until the person stops talking; returns what they said.
    context: a few words the person will likely use (the object, names)."""
    if _speak_refused:
        return ("NOT LISTENING: your last speak was refused, so the person heard nothing. "
                "Say it shorter with speak first, then listen.")
    if speaker.is_speaking():
        capslock.set_mode(ACTING)
        speaker.wait_until_quiet()
    capslock.set_mode(YOUR_TURN)
    pcm, reason = mic.record(max_s=max_seconds)
    capslock.set_mode(THINKING)
    if reason == "mic unplugged":
        speaker.say("My ears are unplugged. I can't hear anything.")
        return ("NOT LISTENING: the pinned mic (settings ears.source) is unplugged, and Grace "
                "never falls back to another mic. Nobody can answer by voice until it is back.")
    vocabulary = settings.load()["ears"]["vocabulary"]
    text = mic.transcribe(pcm, ", ".join(w for w in [context, *vocabulary] if w))
    transcript.add("person", text, stopped=reason)
    global _failed_listens
    _failed_listens = _failed_listens + 1 if listen_failed(text, mic.last_score) else 0
    hint = ""
    if _failed_listens >= FAILS_BEFORE_HINT:
        _failed_listens = 0
        hint = (f" EARS TROUBLE: {FAILS_BEFORE_HINT} listens in a row came back empty or "
                f"unclear ({mic_line(mic.status())}). Do not guess what they meant. Ask out "
                "loud whether you may check your ears; on a yes call tune_up with step 'ears'.")
    if think_aloud and is_real_question(text):
        speaker.say(pondering_line())  # fills the gap while the model thinks
    return f"heard: {text!r} (stopped: {reason})" + hint


def max_words() -> int:
    return int(settings.load()["voice"]["max_words"])


def speak(text: str, wait: bool = False, busy: bool = False) -> str:
    """Say the text out loud in Grace's voice.
    busy=true: you are about to do outside work (search, files); the person keeps waiting,
    so the server keeps the LED slow and says progress lines until your next robot tool."""
    global _speak_refused, _last_tool
    n, limit = len(text.split()), max_words()
    if n > limit:
        _speak_refused = True
        return f"NOT SPOKEN: {n} words, the limit is {limit}. Say it shorter."
    _speak_refused = False
    transcript.add("grace", text)
    if busy:
        _last_tool = "speak_busy"
    capslock.set_mode(ACTING)
    seconds = speaker.say(text, wait=wait)
    return f"speaking, {seconds:.1f} s" if not wait else f"spoke, {seconds:.1f} s"


def set_capslock(mode: Literal["off"] = "off") -> str:
    """Switch the Caps Lock LED off. Only off: on, slow and fast are set by the other
    tools while they really listen, think or act. A manual "on" once stayed solid for
    minutes with nobody listening (26 Nov 2026, docs/spec-led-no-false-your-turn.md)."""
    if mode != "off":
        return "REFUSED: only off. The light is set by listen, see and speak themselves."
    capslock.set_mode(IDLE)
    return "capslock off"


def check_devices() -> dict[str, bool]:
    """Quick 'does it answer' check per device, no recording."""
    import glob
    import os
    import shutil
    leds = capslock.led_paths()
    return {
        "camera": os.access(camera.device(), os.R_OK),
        "mic": bool(shutil.which("arecord")) and bool(glob.glob("/dev/snd/pcmC*D*c"))
               and not mic.status()["pin_missing"],
        "speaker": bool(shutil.which("aplay")) and speaker.voice_file_ok(),
        "capslock": bool(leds) and all(os.access(p, os.W_OK) for p in leds)
                    and settings.load()["capslock"]["visible"],  # the person saw it blink
    }


def hello(full: bool = False) -> str:
    """Grace introduces herself and checks her blocks. Call this first."""
    robot = yaml.safe_load(ROBOT_FILE.read_text())
    checks = check_devices()
    ears = mic.status()
    warning = ears_warning(ears)
    if not warning and not checks["camera"] and ears["source"]:
        # Webcam unplugged: its mic is gone too, and the default quietly changed.
        warning = f"I'm listening through {ears['source']['description']}."
    notes = [warning] if warning else []
    notes += [transcript.NOTE] if transcript.enabled() else []
    notes += [KEEP_NOTE] if keeping_pictures() else []
    promises = {**checks, "unplug_off": checks["camera"] and mic.unplug_makes_deaf(ears),
                "pictures_not_kept": not keeping_pictures()}
    text, seen = intro.build(robot, load_devices(), intro.load_seen(), promises, full, notes=notes)
    transcript.add("grace", text)
    intro.save_seen(seen)
    capslock.set_mode(ACTING)
    speaker.say(text)
    broken = [k for k, ok in checks.items() if not ok]
    sink = f"speaker: {ears['sink'] or 'unknown'}" + (", Bluetooth" if ears["sink_bluetooth"] else "")
    kept = []  # where things are saved, so the model can answer "where is it?" truthfully
    if transcript.enabled():
        kept.append(f"transcript in {transcript.directory()}")
    if keeping_pictures():
        kept.append(f"pictures in {pictures_dir()}")
    return (f"saying: {text!r} ({mic_line(ears)}; {sink})"
            + (f" (not answering: {', '.join(broken)})" if broken else "")
            + (f" (saved on this laptop: {'; '.join(kept)})" if kept else ""))


def tune_up(step: Literal["all", "eyes", "ears", "voice", "heartbeat"] = "all") -> str:
    """Grace checks and tunes eyes, ears, voice and heartbeat for this person and room."""
    speaker.wait_until_quiet()
    if step != "all":
        return getattr(tuneup, step)()
    return "\n".join(tuneup.run_all())


TOOLS = {
    "see": heartbeat(see),
    "listen": heartbeat(listen),
    "speak": heartbeat(speak),
    "capslock": heartbeat(set_capslock, think_after=False),
}


def load_devices(directory: Path = DEVICES_DIR) -> list[dict]:
    devices = []
    for f in sorted(directory.glob("*.yaml")):
        d = yaml.safe_load(f.read_text())
        for key in ("name", "tool", "description"):
            if not d.get(key):
                raise ValueError(f"{f.name}: missing '{key}'")
        devices.append(d)
    return devices


def build_instructions(robot_file: Path = ROBOT_FILE) -> str:
    """Grace's character and numbered rules from robot.yaml, so every agent plays the same Grace."""
    return agents_md.instructions(robot_file)


def build_server(devices: list[dict] | None = None) -> MCPServer:
    server = MCPServer("laptop-robot", instructions=build_instructions())
    server.add_tool(heartbeat(hello), name="hello", description=(
        "Grace introduces herself out loud and checks that every block answers. Call "
        "this first, once per session. The first time it is the full intro; after "
        "that only what is new. full=true repeats the full intro when the person asks "
        "who you are. It ends with a question to the person: listen for the answer. The "
        "first time, that question offers a tune-up: if they say yes, call tune_up."))
    server.add_tool(heartbeat(tune_up), name="tune_up", description=(
        "Grace tunes herself to this person and room, about one minute, all spoken: eyes "
        "(adjusts exposure, asks for light if needed), ears (a repeat-after-me sentence), "
        "voice (too fast / too slow / just right), heartbeat (can they see the LED). Call it "
        "when the person agrees after the first hello, or asks you to tune up. step='ears' "
        "(or eyes, voice, heartbeat) runs one check only, e.g. after listen reports EARS "
        "TROUBLE. Do not speak while it runs; afterwards sum up in one sentence what changed."))
    for d in devices if devices is not None else load_devices():
        if d["tool"] not in TOOLS:
            raise ValueError(f"device '{d['name']}' names unknown tool '{d['tool']}'")
        server.add_tool(TOOLS[d["tool"]], name=d["tool"], description=d["description"].strip())
    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
