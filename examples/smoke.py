"""Live hardware check, one device at a time.

    .venv/bin/python examples/smoke.py photo|watch|speak|listen|leds|mcp [outdir]

photo/watch write JPEGs to outdir (default: current directory) so a person can look.
mcp starts the real server over stdio, lists its tools and takes one photo through it.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drivers import camera, capslock, mic, speaker  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def timed(label, fn, *a, **kw):
    t = time.time()
    r = fn(*a, **kw)
    print(f"{label}: {time.time() - t:.2f} s")
    return r


def main(what: str, out: Path) -> None:
    if what == "photo":
        p = out / "smoke-photo.jpg"
        p.write_bytes(timed("photo", camera.photo))
        print(p)
    elif what == "watch":
        p = out / "smoke-watch.jpg"
        speaker.say("Hold something up and turn it slowly. Watching now.", wait=True)
        p.write_bytes(timed("watch", camera.watch))
        print(p)
    elif what == "speak":
        s = timed("say (returns at start)", speaker.say,
                  "Hello. I am Grace. Found one block: camera.")
        print(f"audio {s:.1f} s, speaking now: {speaker.is_speaking()}")
        speaker.wait_until_quiet()
    elif what == "listen":
        speaker.say("Ask me something, then stop talking.", wait=True)
        text, reason = timed("listen + transcribe", mic.listen)
        print(f"heard: {text!r}  (stopped: {reason})")
    elif what == "leds":
        print("LEDs:", capslock.led_paths())
        for mode in ("fast", "slow", "on", "off"):
            print(mode)
            capslock.set_mode(mode)
            time.sleep(2)
    elif what == "mcp":
        asyncio.run(mcp_check(out))
    else:
        sys.exit(__doc__)


async def mcp_check(out: Path) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=str(ROOT / ".venv/bin/python"),
                                   args=["-m", "mcp_server.server"], cwd=str(ROOT))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        tools = (await s.list_tools()).tools
        for t in tools:
            print(f"tool {t.name}: {t.description[:70]}...")
        t0 = time.time()
        res = await s.call_tool("see", {"mode": "photo"})
        kinds = [c.type for c in res.content]
        print(f"see(photo) via MCP: {time.time() - t0:.2f} s, content {kinds}")
        import base64
        img = next(c for c in res.content if c.type == "image")
        p = out / "smoke-mcp.jpg"
        p.write_bytes(base64.b64decode(img.data))
        print(p)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd())
