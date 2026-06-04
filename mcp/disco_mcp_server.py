#!/usr/bin/env python3
"""MCP wrapper for DiscoElysiumBridge's localhost HTTP API."""

from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP, Image


BRIDGE_URL = os.environ.get("DISCO_BRIDGE_URL", "http://127.0.0.1:7860")

mcp = FastMCP("disco-elysium-bridge")


def request_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"{BRIDGE_URL.rstrip('/')}{path}{query}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=10) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def compact(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
def disco_health() -> str:
    """Check whether the Disco Elysium bridge mod is running."""
    return compact(request_json("/health"))


@mcp.tool()
def disco_state() -> str:
    """Read current dialogue state and available choices."""
    return compact(request_json("/state"))


@mcp.tool()
def disco_choose(index: int) -> str:
    """Choose a dialogue option by 0-based index."""
    return compact(request_json("/choose", {"index": index}))


@mcp.tool()
def disco_continue() -> str:
    """Advance dialogue by pressing Enter."""
    return compact(request_json("/continue"))


@mcp.tool()
def disco_click(x: int, y: int, double: bool = False) -> str:
    """Click a screen coordinate. Set double=true to run."""
    return compact(request_json("/click", {"x": x, "y": y, "double": 1 if double else 0}))


@mcp.tool()
def disco_key(name: str, hold: int = 0) -> str:
    """Press or hold a supported key such as tab, escape, i, m, up, down."""
    params: dict[str, Any] = {"name": name}
    if hold:
        params["hold"] = hold
    return compact(request_json("/key", params))


@mcp.tool()
def disco_screenshot(scale: float = 0.5) -> list:
    """Capture a scaled JPEG screenshot from the game/desktop."""
    scale = max(0.1, min(float(scale), 1.0))
    data = request_json("/screenshot", {"scale": scale, "format": "jpeg"})
    image_b64 = data.get("data")
    if not image_b64:
        return [compact(data)]

    image_bytes = base64.b64decode(image_b64)
    meta = {k: v for k, v in data.items() if k != "data"}
    return [
        Image(data=image_bytes, format="jpeg"),
        compact(meta),
    ]


if __name__ == "__main__":
    mcp.run(transport="stdio")
