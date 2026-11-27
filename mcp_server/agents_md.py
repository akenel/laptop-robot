"""Grace's character and numbered rules, rendered from robot.yaml (the one source).

    .venv/bin/python -m mcp_server.agents_md     # rewrites AGENTS.md

The MCP server sends instructions() to agents that read MCP instructions (Claude Code).
AGENTS.md is for agents that don't (OpenCode). tests/test_agents_md.py fails when the
two drift apart."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ROBOT_FILE = ROOT / "robot.yaml"
AGENTS_FILE = ROOT / "AGENTS.md"
TOOLS = ("Tools: hello (introduce yourself), see (eyes), listen (ears), speak (voice; "
         "everything you say goes through it), capslock (heartbeat).")


def _rules(robot: dict) -> list[str]:
    return [f"{k}. {' '.join(str(v).split())}" for k, v in robot["rules"].items()]


def instructions(robot_file: Path = ROBOT_FILE) -> str:
    """One plain-text block for the MCP server's instructions."""
    robot = yaml.safe_load(robot_file.read_text())
    jokes = " ".join(f'"{j}"' for j in robot.get("humor_examples", []))
    parts = [" ".join(robot["character"].split()), "Rules:", *_rules(robot), TOOLS]
    if jokes:
        parts.append(f"The kind of humor that fits: {jokes}")
    return "\n".join(parts)


def agents_md(robot_file: Path = ROBOT_FILE) -> str:
    robot = yaml.safe_load(robot_file.read_text())
    jokes = "\n".join(f'- "{j}"' for j in robot.get("humor_examples", []))
    return (
        "# You are Grace\n\n"
        "<!-- GENERATED from robot.yaml by `.venv/bin/python -m mcp_server.agents_md`. "
        "Do not edit here. -->\n\n"
        "For agents that do not read MCP server instructions (OpenCode, ...). Claude Code "
        "gets the same text from the laptop-robot server. Why each rule exists: "
        "`docs/grace-lessons.md`.\n\n"
        f"{' '.join(robot['character'].split())}\n\n"
        "## Rules\n\n" + "\n".join(_rules(robot)) + "\n\n"
        "Loop: hello -> listen -> (see) -> speak -> listen -> speak -> listen ... -> "
        "capslock off.\n\n"
        f"{TOOLS}\n\n"
        "## Humor that fits\n\n" + jokes + "\n")


if __name__ == "__main__":
    AGENTS_FILE.write_text(agents_md())
    print(f"wrote {AGENTS_FILE}")
