"""Turn a day's opt-in transcript into one HTML page.

    .venv/bin/python examples/transcript.py [YYYY-MM-DD] > conversation.html
"""

import html
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server import transcript  # noqa: E402


def render(lines: list[dict], day: str) -> str:
    rows = "\n".join(
        f'<p class="{html.escape(l["who"])}"><time>{html.escape(l["time"])}</time> '
        f'<b>{"You" if l["who"] == "person" else "Grace"}</b> {html.escape(l["text"])}</p>'
        for l in lines)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Grace conversation {html.escape(day)}</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:40em;margin:2em auto;padding:0 16px}}
p{{padding:.4em .7em;border-radius:6px}} .person{{background:#e8eef7}} .grace{{background:#f3ece0}}
time{{color:#777;font-size:.85em;margin-right:.5em}}</style></head><body>
<h1>Grace conversation, {html.escape(day)}</h1>
{rows}
</body></html>"""


def main(day: str) -> None:
    f = transcript.directory() / f"{day}.jsonl"
    lines = [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []
    print(render(lines, day))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else time.strftime("%Y-%m-%d"))
