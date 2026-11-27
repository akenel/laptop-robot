"""AGENTS.md is generated from robot.yaml; a hand edit or a stale copy fails here."""

from mcp_server import agents_md


def test_agents_md_is_up_to_date():
    assert agents_md.AGENTS_FILE.read_text() == agents_md.agents_md(), (
        "AGENTS.md is out of date: run .venv/bin/python -m mcp_server.agents_md")


def test_rules_are_numbered_in_order():
    import yaml
    keys = list(yaml.safe_load(agents_md.ROBOT_FILE.read_text())["rules"])
    assert keys == [f"R{i}" for i in range(1, len(keys) + 1)]


def test_every_rule_reaches_both_agents():
    text, md = agents_md.instructions(), agents_md.agents_md()
    for line in agents_md._rules(__import__("yaml").safe_load(agents_md.ROBOT_FILE.read_text())):
        assert line in text and line in md
