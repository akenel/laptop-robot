"""tune_up: Grace checks and tunes her blocks for this person, this room, this laptop.

Measured, not guessed: eyes by pixel arithmetic, ears by level and word overlap, voice
and heartbeat by the person's short answer. An unclear answer leaves a setting as it was.
Settings land in ~/.config/laptop-robot/settings.json (drivers/settings.py).
"""

import re
import subprocess

from drivers import camera, capslock, mic, settings, speaker

EAR_TARGET = "I'll show you something else."

VOICE_ANSWERS = {   # checked in this order
    "fast": ["too fast", "fast", "quick", "slow down", "slower"],
    "slow": ["too slow", "slow", "faster", "speed up"],
    "loud": ["too loud", "loud", "quieter"],
    "quiet": ["too quiet", "quiet", "can't hear", "cannot hear", "louder", "soft"],
    "right": ["just right", "right", "fine", "good", "perfect", "okay", "ok", "great"],
}
YES_WORDS = ["yes", "yeah", "yep", "i do", "i can", "sure", "it is"]
NO_WORDS = ["no", "nope", "not", "can't", "cannot", "nothing", "don't see"]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def parse_answer(text: str, options: dict[str, list[str]]) -> str | None:
    """First option whose keyword appears as whole words; None if nothing matches.
    'slow' must not match inside 'slower': phrases are matched on word boundaries."""
    padded = " " + " ".join(_words(text)) + " "
    for key, phrases in options.items():
        if any(f" {p} " in padded for p in phrases):
            return key
    return None


def parse_yes_no(text: str) -> str | None:
    """'yes', 'no', or None when the answer is empty or says both."""
    yes = parse_answer(text, {"yes": YES_WORDS})
    no = parse_answer(text, {"no": NO_WORDS})
    if yes and no:
        return None
    return yes or no


def word_match(said: str, target: str) -> float:
    """Share of the target's words that were heard."""
    t = _words(target)
    heard = set(_words(said))
    return sum(w in heard for w in t) / len(t) if t else 0.0


def _say(text: str) -> None:
    capslock.set_mode("fast")
    speaker.say(text, wait=True)


def _hear(context: str) -> tuple[str, str]:
    capslock.set_mode("on")
    pcm, reason = mic.record(max_s=8)
    capslock.set_mode("slow")
    return mic.transcribe(pcm, context), reason


# --- steps -----------------------------------------------------------------

def eyes() -> str:
    _say("First my eyes. Hold still for a moment.")
    c = settings.load()["camera"]
    verdict, changed = "ok", False
    for _ in range(3):
        settings.update("camera", **c)
        stats = camera.brightness_stats(camera.photo())
        c, verdict = camera.next_controls(stats, c)
        if verdict in ("ok", "too dark", "too bright"):
            break
        changed = True
    settings.update("camera", **c)
    line = {
        "ok": "I adjusted my eyes to your light." if changed else "The light looks good.",
        "too dark": "It's too dark for me, even at full sensitivity. Please turn on a light.",
        "too bright": "It's too bright, even with my eyes squinted. Turn the lamp away from me a little.",
    }.get(verdict, "I adjusted my eyes as far as they go.")
    _say(line)
    return f"eyes: {verdict}, camera {c} (mean {stats['mean']:.0f}, clipped {stats['clipped']:.1%})"


def ears() -> str:
    """Repeat-after-me, with one retry: the first miss is usually the instruction, not the mic."""
    switched = ""
    st = mic.status()
    if st["pin_missing"]:
        _say("My ears are unplugged, so I can't check them. Plug the microphone back in.")
        return f"ears: unplugged ({st['pin']} not found)"
    src, alt = st["source"], st["alternative"]
    if src and src["bluetooth"]:
        if alt:
            settings.update("ears", source=alt["name"])
            switched = f", switched from {src['description']} (Bluetooth) to {alt['description']}"
            _say(f"I was listening through {src['description']}, a Bluetooth phone mic. "
                 f"I'll use {alt['description']} instead.")
        else:
            _say(f"I'm listening through {src['description']}, a Bluetooth phone mic. "
                 "Those hear badly, so let's see.")
    mic_name = (alt if switched else src or {}).get("description", "unknown mic")
    _say("Now my ears. I'll say a sentence. When my light goes solid, say it back to me.")
    _say(f"The sentence is: {EAR_TARGET} Your turn.")
    tries = []
    for attempt in (1, 2):
        text, reason = _hear("show you something else")
        score = word_match(text, EAR_TARGET)
        tries.append(f"{text!r} {score:.0%}")
        if score >= 0.8:
            _say("I heard you clearly." if attempt == 1 else "That time I heard you clearly.")
            return f"ears: ok on try {attempt}, {mic_name}{switched} ({'; '.join(tries)})"
        if attempt == 1:
            _say(f"I heard: {text}. Let's try once more. Just the sentence: {EAR_TARGET}"
                 if text else f"I didn't hear anything. Once more: {EAR_TARGET}")
    if reason == "no speech" or not text:
        _say("I still didn't hear anything. Is the right microphone switched on?")
    else:
        _say("I'm still missing words. Sitting a bit closer and facing the camera usually helps.")
    return f"ears: weak, {mic_name}{switched} ({'; '.join(tries)})"


def _volume_percent() -> int | None:
    try:
        out = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                             capture_output=True, text=True, timeout=5).stdout
        return int(re.search(r"(\d+)%", out).group(1))
    except (OSError, AttributeError, ValueError, subprocess.SubprocessError):
        return None


def voice() -> str:
    _say("Next, my voice. Was that too fast, too slow, or just right?")
    text, _ = _hear("too fast, too slow, just right, loud, quiet")
    answer = parse_answer(text, VOICE_ANSWERS)
    speed = settings.load()["voice"]["speed"]
    if answer == "fast":
        speed = max(0.8, round(speed - 0.1, 1))
        settings.update("voice", speed=speed)
        line = "Okay, I'll speak a little slower. Like this."
    elif answer == "slow":
        speed = min(1.2, round(speed + 0.1, 1))
        settings.update("voice", speed=speed)
        line = "Okay, a little faster. Like this."
    elif answer == "loud":
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"], capture_output=True)
        line = "Sorry. Is this better?"
    elif answer == "quiet":
        vol = _volume_percent()
        if vol is not None and vol < 100:
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"], capture_output=True)
            line = "Okay, a bit louder."
        else:
            line = "My volume is already at the maximum. Headphones or the volume keys might help."
    elif answer == "right":
        line = "Good, I'll keep it that way."
    else:
        line = "I didn't quite get that, so I'll leave my voice as it is."
    _say(line)
    return f"voice: heard {text!r} -> {answer or 'unclear'}, speed {speed}"


def heartbeat() -> str:
    if not capslock.led_paths():
        return "heartbeat: no Caps Lock LED on this laptop"
    capslock.set_mode("fast")
    speaker.say("Last one. Do you see my Caps Lock light blinking?", wait=True)
    capslock.set_mode("fast")  # keep blinking while they look
    pcm, _ = mic.record(max_s=8)
    text = mic.transcribe(pcm, "yes, no, blinking, light")
    answer = parse_yes_no(text)
    capslock.set_mode("off")
    if answer == "yes":
        settings.update("capslock", visible=True)
        line = "Great. Solid means your turn, slow means I'm thinking, fast means I'm doing something."
    elif answer == "no":
        settings.update("capslock", visible=False)
        line = "Okay, then I won't rely on my light. I'll tell you out loud when it's your turn."
    else:
        line = "I didn't catch that, so I'll keep using my light."
    _say(line)
    return f"heartbeat: heard {text!r} -> {answer or 'unclear'}"


def run_all() -> list[str]:
    report = [eyes(), ears(), voice(), heartbeat()]
    _say("All done. I'm tuned to your room.")
    return report
