#!/usr/bin/env python3
"""MCP wrapper for DiscoElysiumBridge's localhost HTTP API."""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP, Image


BRIDGE_URL = os.environ.get("DISCO_BRIDGE_URL", "http://localhost:7860")
DEFAULT_GAME_SCALE = 0.4
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from gaze_runner import run_gaze_once  # noqa: E402

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


def compact_gaze(data: dict[str, Any], *, include_meta: bool = False) -> str:
    if include_meta:
        return compact(data)

    entries = data.get("entries")
    if isinstance(entries, list):
        data = dict(data)
        data["entries"] = [
            {
                key: value
                for key, value in entry.items()
                if key in {"source", "caption"} and value
            }
            for entry in entries
            if isinstance(entry, dict)
        ]

    for key in ("window", "caption_provider"):
        data.pop(key, None)

    return compact(data)


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
def disco_click(
    x: int,
    y: int,
    double: bool = False,
    target: str = "game",
    scale: float = DEFAULT_GAME_SCALE,
    dry_run: bool = False,
) -> str:
    """Click a coordinate. By default x/y are pixels in the default game screenshot (target=game, scale=0.4). Pass the same scale as the screenshot you used, or scale=1.0 for native game-window pixels."""
    return compact(
        request_json(
            "/click",
            {
                "x": x,
                "y": y,
                "double": 1 if double else 0,
                "target": target,
                "scale": scale,
                "dry_run": 1 if dry_run else 0,
            },
        )
    )


@mcp.tool()
def disco_click_watch(
    x: int,
    y: int,
    double: bool = False,
    target: str = "game",
    scale: float = DEFAULT_GAME_SCALE,
    frames: int = 6,
    interval_ms: int = 400,
    watch_scale: float | None = None,
    quality: int = 35,
    max_bytes: int = 350000,
) -> list:
    """Click a coordinate, then capture a screenshot burst for captions/tooltips that appear after walking."""
    scale = max(0.05, min(float(scale), 1.0))
    watch_scale = scale if watch_scale is None else max(0.05, min(float(watch_scale), 1.0))
    frames = max(1, min(int(frames), 12))
    interval_ms = max(0, min(int(interval_ms), 2000))
    quality = max(10, min(int(quality), 95))
    max_bytes = max(20_000, min(int(max_bytes), 5_000_000))
    data = request_json(
        "/click-watch",
        {
            "x": x,
            "y": y,
            "double": 1 if double else 0,
            "target": target,
            "scale": scale,
            "frames": frames,
            "interval_ms": interval_ms,
            "watch_scale": watch_scale,
            "quality": quality,
            "max_bytes": max_bytes,
        },
    )
    frame_metas: list[dict[str, Any]] = []
    image_items: list[Any] = []
    for frame in data.get("frames", []):
        if not isinstance(frame, dict):
            continue
        frame_meta = {key: value for key, value in frame.items() if key != "data"}
        image_b64 = frame.get("data")
        if image_b64:
            image_bytes = base64.b64decode(image_b64)
            frame_meta["imageBytes"] = len(image_bytes)
            image_items.append(Image(data=image_bytes, format=frame.get("format", "jpeg")))
        frame_metas.append(frame_meta)

    return [compact({"click": data.get("click"), "frames": frame_metas})] + image_items


@mcp.tool()
def disco_key(name: str | None = None, key: str | None = None, hold: int = 0) -> str:
    """Press or hold a supported key such as tab, escape, i, m, up, down. Pass either name or key."""
    key_name = name or key
    if not key_name:
        return compact({"error": "missing key name", "hint": "Pass name='tab' or key='tab'."})
    params: dict[str, Any] = {"name": key_name}
    if hold:
        params["hold"] = hold
    return compact(request_json("/key", params))


@mcp.tool()
def disco_screenshot(
    scale: float = DEFAULT_GAME_SCALE,
    quality: int = 35,
    target: str = "game",
    max_bytes: int = 750000,
) -> list:
    """Capture a compressed screenshot. On macOS, target=game crops to the game window when possible."""
    scale = max(0.05, min(float(scale), 1.0))
    quality = max(10, min(int(quality), 95))
    max_bytes = max(20_000, min(int(max_bytes), 5_000_000))
    params = {"scale": scale, "format": "jpeg", "quality": quality, "target": target, "max_bytes": max_bytes}
    data = request_json("/screenshot", params)
    image_b64 = data.get("data")
    if not image_b64:
        return [compact(data)]

    image_bytes = base64.b64decode(image_b64)
    if len(image_bytes) > max_bytes and scale > 0.06:
        retry_scale = max(0.05, scale * 0.65)
        data = request_json(
            "/screenshot",
            {**params, "scale": retry_scale, "quality": min(quality, 25), "max_bytes": max_bytes},
        )
        image_b64 = data.get("data")
        if image_b64:
            image_bytes = base64.b64decode(image_b64)

    meta = {k: v for k, v in data.items() if k != "data"}
    if len(image_bytes) > max_bytes:
        meta["error"] = f"screenshot still too large for MCP image return: {len(image_bytes)} bytes"
        meta["hint"] = "Try smaller scale, lower quality, or use disco_gaze."
        return [compact(meta)]

    image_format = data.get("format", "jpeg")
    return [
        Image(data=image_bytes, format=image_format),
        compact(meta),
    ]


@mcp.tool()
def disco_markers(
    scale: float = DEFAULT_GAME_SCALE,
    target: str = "game",
    max_bytes: int = 750000,
) -> str:
    """Capture the current game screenshot and return detected green interaction-marker coordinates. Use marker.click with disco_click."""
    scale = max(0.05, min(float(scale), 1.0))
    max_bytes = max(20_000, min(int(max_bytes), 5_000_000))
    return compact(request_json("/markers", {"scale": scale, "target": target, "max_bytes": max_bytes}))


@mcp.tool()
def disco_gaze(
    window: str = "Disco Elysium",
    caption_provider: str = "none",
    ocr: bool = True,
    mask_preset: str = "mac-safe",
    max_ocr_chars: int = 1200,
    include_meta: bool = False,
    allow_fullscreen_fallback: bool = False,
) -> str:
    """Observe the Disco Elysium window through the local gaze tool and return compact OCR text by default. Set caption_provider='gemini' only when visual scene description is useful."""
    return compact_gaze(
        run_gaze_once(
            window=window,
            caption_provider=caption_provider,
            ocr=ocr,
            mask_preset=mask_preset,
            max_ocr_chars=max_ocr_chars,
            strict_window=not allow_fullscreen_fallback,
        ),
        include_meta=include_meta,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
