#!/usr/bin/env bash
# laptop-robot: install Grace's head on a Debian or Ubuntu laptop.
#
#   ./install.sh          asks before every sudo step
#   ./install.sh --yes    answers yes to everything (still needs your sudo password)
#
# Safe to run again: every step checks first and skips what is already done.
# Downloads about 0.5 GB (voice and ears models). Nothing is sent anywhere.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YES=0; [[ "${1:-}" == "--yes" ]] && YES=1
KOKORO_DIR="$HOME/.local/share/kokoro"
KOKORO_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
UDEV_RULE=/etc/udev/rules.d/90-laptop-robot-capslock.rules
START=$(date +%s)
PROBLEMS=()

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   ok: %s\n' "$*"; }
warn() { printf '   \033[33mnote:\033[0m %s\n' "$*"; PROBLEMS+=("$*"); }
die()  { printf '\n\033[31mstop:\033[0m %s\n' "$*"; exit 1; }
ask()  { [[ $YES == 1 ]] && return 0; read -r -p "   $* [y/N] " a; [[ "$a" =~ ^[Yy] ]]; }

cd "$REPO"

say "1/8 System"
command -v apt-get >/dev/null || die "This installer is for Debian or Ubuntu (apt). See docs/ for other systems."
. /etc/os-release; ok "$PRETTY_NAME"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "Python 3.11 or newer needed, found $(python3 --version 2>&1). Debian 12+ or Ubuntu 24.04+ have it."
ok "$(python3 --version)"

say "2/8 System packages"
need=()
command -v ffmpeg    >/dev/null || need+=(ffmpeg)
command -v v4l2-ctl  >/dev/null || need+=(v4l-utils)
command -v arecord   >/dev/null || need+=(alsa-utils)
command -v pactl     >/dev/null || need+=(pulseaudio-utils)
python3 -c 'import venv, ensurepip' 2>/dev/null || need+=(python3-venv)
if (( ${#need[@]} )); then
  echo "   missing: ${need[*]}"
  if ask "Install them with sudo apt-get?"; then
    sudo apt-get update -qq && sudo apt-get install -y "${need[@]}"
  else
    die "Cannot continue without: ${need[*]}"
  fi
fi
ok "ffmpeg, v4l-utils, alsa-utils, pulseaudio-utils, python3-venv"

say "3/8 Python environment (.venv)"
[[ -x .venv/bin/python ]] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
ok "$(.venv/bin/pip list 2>/dev/null | grep -ciE '^(mcp|faster-whisper|kokoro-onnx|piper-tts|pyyaml|soundfile|pytest) ') packages"

say "4/8 Models (about 0.5 GB, once)"
mkdir -p "$KOKORO_DIR"
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  if [[ -s "$KOKORO_DIR/$f" ]]; then ok "voice: $f already here"
  else echo "   downloading $f ..."; curl -fL --progress-bar -o "$KOKORO_DIR/$f.part" "$KOKORO_URL/$f" \
       && mv "$KOKORO_DIR/$f.part" "$KOKORO_DIR/$f"; ok "voice: $f"; fi
done
if .venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('base.en', device='cpu', compute_type='int8')" 2>/dev/null; then
  ok "ears: Whisper base.en"
else
  warn "ears: Whisper model download failed (network?); run ./install.sh again"
fi

say "5/8 Hardware"
if [[ -e /dev/video0 ]]; then
  if [[ -r /dev/video0 ]]; then ok "camera: /dev/video0"
  else warn "camera found but not readable: sudo usermod -aG video \$USER, then log out and in"; fi
else warn "no camera on /dev/video0: plug in a USB webcam (a built-in one may not work on Linux)"; fi
arecord -l 2>/dev/null | grep -q '^card' && ok "microphone: $(pactl get-default-source 2>/dev/null || echo default)" \
  || warn "no microphone found"
aplay -l 2>/dev/null | grep -q '^card' && ok "speaker" || warn "no speaker found"

say "6/8 Heartbeat (Caps Lock LED, optional)"
leds=(/sys/class/leds/*::capslock/brightness)
if [[ ! -e "${leds[0]}" ]]; then
  warn "no Caps Lock LED here; Grace will say out loud when it's your turn"
elif [[ -w "${leds[0]}" ]]; then
  ok "Caps Lock LED writable"
elif ask "Let Grace blink your Caps Lock LED? (one udev rule, needs sudo)"; then
  sudo cp image/90-laptop-robot-capslock.rules "$UDEV_RULE"
  sudo udevadm control --reload && sudo udevadm trigger -s leds
  [[ -w "${leds[0]}" ]] && ok "Caps Lock LED writable" || warn "LED rule installed but not active yet: unplug/replug the keyboard or reboot"
else
  warn "LED skipped; Grace works without it"
fi

say "7/8 Brain (which agent and model think for Grace)"
# Grace's eyes, ears and voice work with any MCP agent. The model belongs to the agent:
# change it later with /model (Claude Code) or /models (OpenCode).
BRAIN=claude
echo "   1) Claude Code + Claude plan (tested, the reference)"
echo "   2) OpenCode + an Ollama model (tested: gemma4:31b-cloud, Ollama Cloud plan)"
if [[ $YES == 1 ]]; then a=1; else read -r -p "   Pick 1 or 2 [1]: " a; fi
if [[ "${a:-1}" == 2 ]]; then
  BRAIN=opencode
  if ! command -v ollama >/dev/null; then
    warn "ollama not installed: https://ollama.com/download, then run ./install.sh again"
  else
    # Grace needs a model that sees images AND calls tools: ollama show lists both.
    models=(gemma4:31b-cloud); skipped=()
    while read -r m; do
      [[ $m == gemma4:31b-cloud ]] && continue
      caps=$(timeout 20 ollama show "$m" 2>/dev/null | sed -n '/Capabilities/,/^$/p')
      if grep -qw vision <<<"$caps" && grep -qw tools <<<"$caps"; then models+=("$m")
      else skipped+=("$m"); fi
    done < <(ollama list 2>/dev/null | awk 'NR>1 {print $1}')
    (( ${#skipped[@]} )) && echo "   Left out (no vision or no tools): ${skipped[*]}"
    echo "   Small local models are slow on a CPU and invent details."
    echo "   Cloud models need: ollama signin"
    for i in "${!models[@]}"; do
      tag=""; [[ ${models[$i]} == gemma4:31b-cloud ]] && tag="  (tested)"
      printf '   %d) %s%s\n' $((i + 1)) "${models[$i]}" "$tag"
    done
    read -r -p "   Model number [1]: " n
    n=${n:-1}
    if [[ "$n" =~ ^[0-9]+$ ]] && (( n >= 1 && n <= ${#models[@]} )); then
      MODEL=${models[$((n - 1))]}
      .venv/bin/python - "$REPO/opencode.json" "$MODEL" <<'EOF'
import json, sys
path, model = sys.argv[1], sys.argv[2]
cfg = json.load(open(path))
cfg["model"] = f"ollama/{model}"
cfg["provider"]["ollama"].setdefault("models", {}).setdefault(model, {
    "name": model, "attachment": True, "tool_call": True,
    "modalities": {"input": ["text", "image"], "output": ["text"]}})
json.dump(cfg, open(path, "w"), indent=2)
open(path, "a").write("\n")
EOF
      ok "opencode.json: model ollama/$MODEL"
      [[ $MODEL == *-cloud ]] && ! ollama list 2>/dev/null | grep -q "^$MODEL " \
        && warn "run: ollama signin && ollama pull $MODEL"
    else
      warn "no model picked; opencode.json unchanged"
    fi
  fi
  command -v opencode >/dev/null && ok "OpenCode $(opencode --version 2>/dev/null)" \
    || warn "OpenCode not installed: curl -fsSL https://opencode.ai/install | bash"
else
  ok "Claude Code"
fi

say "8/8 Check"
if out=$(.venv/bin/python -m pytest -q 2>&1); then ok "tests: $(tail -1 <<<"$out")"
else warn "tests failed: $(tail -1 <<<"$out")"; fi
if .venv/bin/python -c "from mcp_server import server; server.build_server()" 2>/dev/null; then ok "MCP server builds"
else warn "MCP server does not build: .venv/bin/python -m mcp_server.server shows why"; fi
if ask "Let Grace say one sentence through your speaker now?"; then
  .venv/bin/python -c "from drivers import speaker; speaker.say('Hello. My head is installed.', wait=True)" 2>/dev/null \
    && ok "you should have heard Grace" || warn "speaker test failed"
fi

say "Done in $(( $(date +%s) - START )) s"
if (( ${#PROBLEMS[@]} )); then printf '   to look at:\n'; printf '   - %s\n' "${PROBLEMS[@]}"; fi
if [[ $BRAIN == opencode ]]; then
cat <<EOF

Next:
  1. cd $REPO && opencode     (it reads opencode.json and AGENTS.md)
  2. Type:  hi grace          then just talk. Change the model any time with /models.
EOF
exit 0
fi
if command -v claude >/dev/null; then
  cc="1. Claude Code: installed ($(claude --version 2>/dev/null | head -1))"
else
  cc="1. Claude Code: not installed yet. It needs a Claude Pro plan or higher (the free plan
     does not include it). Install it, then open a NEW terminal:
       curl -fsSL https://claude.ai/install.sh | bash
     Details: https://code.claude.com/docs/en/install"
fi
cat <<EOF

Next:
  $cc
  2. cd $REPO && claude    (log in on the first start)
  3. Approve the "laptop-robot" MCP server, then type:  Call hello, then talk with me.
EOF
