# laptop-robot

**A robot built from the head down.** No robot hardware to buy: your laptop is the head (a ~CHF 20 USB webcam helps).

A free "hello world" for robots. An AI agent sees, hears and speaks through the laptop you
already have: the laptop is the head. The rest of the robot (neck, arms, wheels) is built
one block at a time, each block added only when the one above it works.

Her name is Grace. You talk to her; she answers out loud, looks through the webcam when you
show her something, and says when she is not sure.

## Tested with

| Brain | Status |
| --- | --- |
| Claude Code + Claude subscription (~USD 20/month) | The reference. Tested for days. |
| OpenCode 1.19.6 + Ollama Cloud `gemma4:31b-cloud` (~USD 20/month) | One full spoken conversation (~2 h, 6 pictures), every description true. |
| Local Ollama on a CPU | Works in principle: 13-241 s per picture, and small models invent details. A lesson, not a daily driver. |

Any MCP agent that passes images to a model that sees and calls tools should work. Only the
two above are tested.

## What you need

- **Linux only, today:** Debian 12+ or Ubuntu 24.04+ (Python 3.11+), a 16 GB laptop, no GPU
  needed. Windows and macOS are not supported yet (the Windows plan is a later block).
- A USB webcam (~CHF 20). Built-in laptop cameras often don't work on Linux. The webcam's
  microphone is usually clearer than the laptop's.
- About 0.5 GB of disk for the voice and ears models. Nothing is sent anywhere by the
  robot itself; the model you choose is the only thing that leaves the laptop.

## Quickstart

```sh
./install.sh          # asks before every sudo step; safe to run again
```

The installer asks which brain: Claude Code, or OpenCode with one of your Ollama models
(it lists them and writes your pick into `opencode.json`). Then:

- **Claude Code:** `claude` in this folder (it reads `.mcp.json`), type `hi grace`.
- **OpenCode:** `ollama signin` once, then `opencode` in this folder (it reads
  `opencode.json` and `AGENTS.md`), type `hi grace`.

From then on, just talk. Change the model later with `/model` (Claude Code) or `/models`
(OpenCode).

## The Caps Lock light

Grace uses your Caps Lock LED as a heartbeat (optional, needs one udev rule the installer
offers):

- **Solid:** your turn, talk or show something.
- **Slow blink:** she is thinking.
- **Fast blink:** she is acting (watching, speaking).
- **Off:** idle after 90 seconds, or the conversation is over. If the agent stops mid-conversation,
  Grace says so ("Type hi grace to wake me up") and the light goes off.

## Honest limits

- A good conversation needs a paid cloud model. Local CPU models are slow and make things up.
- With OpenCode, edits, shell commands and web fetches are set to ask first
  (`opencode.json`). Choosing "allow always" stops the asking for that tool for the rest of
  the session; pick "allow once" when unsure.
- Grace's own tools only look, listen, speak and blink. Anything else the agent can do
  (files, shell, web) is the agent's configuration, not this repo's.
- Not yet tested: Bluetooth microphones, macOS (head only, no heartbeat), other laptops.
- Similar tools exist for voice coding (Claude Code's `/voice`, VoiceMode) and for robot heads
  you buy (Reachy Mini). This one is the step before: no hardware, and the lessons on why each
  rule exists are in `docs/grace-lessons.md`.

## Layout

```
devices/      one plain-language description file per device
drivers/      camera, mic, speaker, Caps Lock (read/write only)
mcp_server/   exposes the drivers as tools: hello, see, listen, speak, capslock, tune_up
robot.yaml    Grace's character and numbered rules R1..R17 (the one source)
AGENTS.md     generated from robot.yaml, for agents that don't read MCP instructions
docs/         grace-lessons.md (why each rule exists), grace-check.md (a 3-minute check)
tests/        hardware-free tests: .venv/bin/pytest
```

## Licence

MIT. See `LICENSE`.
