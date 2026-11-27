# laptop-robot: notes for agents working on this repo

A robot built from the head down. The laptop is the head: webcam = eyes, microphone = ears,
speakers = voice, Caps Lock LED = heartbeat. Any MCP agent (Claude Code, OpenCode, ...) drives
it through the `laptop-robot` MCP server. Neck, arms and wheels come later, one block at a
time, each added only when the one above works.

If you are an agent asked to *be* the robot: your character and rules come from the MCP
server's instructions (Claude Code) or `AGENTS.md` (others). This file is for working ON the
code.

## Layout

```
devices/      one plain-language description file per device (the server builds tools from them)
drivers/      camera, mic, speaker, Caps Lock: read/write only, no MCP knowledge
mcp_server/   server.py (tools: hello, see, listen, speak, capslock, tune_up),
              intro.py, tuneup.py, transcript.py, agents_md.py
robot.yaml    THE source of the character: name, greetings, rules R1..R17, lines
AGENTS.md     GENERATED from robot.yaml: .venv/bin/python -m mcp_server.agents_md
tests/        hardware-free tests: .venv/bin/pytest
docs/         grace-lessons.md (why each rule exists), grace-check.md (manual check sheet)
examples/     the filmed head demo, a free conversation, smoke test, transcript renderer
image/        udev rule for the Caps Lock LED (later: live USB build)
```

## Rules for changing things

- **Prompts don't enforce limits; the server does.** Every rule that matters is enforced in
  `mcp_server/server.py`, not only written in `robot.yaml`: max words per speak, one robot tool
  at a time in arrival order, a speak batched behind another speak is refused, the LED only
  says "your turn" while really listening. Add the enforcement and a test, not just a rule.
- **Rules are numbered and append-only.** Add R18 at the end; never renumber. Every new rule
  gets an entry in `docs/grace-lessons.md` saying which real failure caused it.
- **After editing `robot.yaml`, regenerate `AGENTS.md`.** `tests/test_agents_md.py` fails when
  it is stale.
- **Every promise in the intro must be true for the code.** A device's `wont` line that depends
  on hardware or a setting carries `needs:` and is dropped when that is false.
- **Privacy:** nothing leaves the laptop except what goes to the model the person chose.
  Pictures and transcripts are kept only when a setting says so, and the intro says it.
- Test on real hardware before writing about it; measure, don't assume.
- All docs in English, short sentences.

## Platform

Debian 12+/Ubuntu 24.04+, Python 3.11+, CPU only, 16 GB. Linux only today: macOS would be head
only (untested), Windows and WSL are not supported yet.

## Settings and state

`~/.config/laptop-robot/`: `settings.json` (tuned by `tune_up`), `state.json` (which blocks
Grace has introduced), `transcripts/` and `pictures/` (only when enabled). Tests never touch
these (`tests/conftest.py` points them at a temp dir).
