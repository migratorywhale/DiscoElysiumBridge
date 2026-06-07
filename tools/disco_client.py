#!/usr/bin/env python3
"""Small CLI client for the DiscoElysiumBridge HTTP API."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from gaze_runner import run_gaze_once


DEFAULT_URL = os.environ.get("DISCO_BRIDGE_URL", "http://localhost:7860")


def request_json(base_url: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"{base_url.rstrip('/')}{path}{query}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=10) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call a running DiscoElysiumBridge HTTP API.")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Bridge URL, default: {DEFAULT_URL}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health")
    sub.add_parser("state")
    sub.add_parser("continue")

    choose = sub.add_parser("choose")
    choose.add_argument("index", type=int, help="0-based dialogue choice index")

    click = sub.add_parser("click")
    click.add_argument("x", type=int)
    click.add_argument("y", type=int)
    click.add_argument("--double", action="store_true", help="Double-click/run")

    key = sub.add_parser("key")
    key.add_argument("name", help="Key name: tab, enter, escape, f1, up, i, m, ...")
    key.add_argument("--hold", type=int, default=0, help="Hold duration in ms")

    screenshot = sub.add_parser("screenshot")
    screenshot.add_argument("--scale", type=float, default=0.25)
    screenshot.add_argument("--format", choices=["jpeg", "bmp"], default="jpeg")
    screenshot.add_argument("--quality", type=int, default=35)
    screenshot.add_argument("--target", choices=["game", "screen", "fullscreen", "desktop"], default="game")
    screenshot.add_argument("--max-bytes", type=int, default=750_000)
    screenshot.add_argument("--out", type=Path, help="Write decoded image to this file")

    gaze = sub.add_parser("gaze")
    gaze.add_argument("--window", default=os.environ.get("DISCO_GAZE_WINDOW", "Disco Elysium"))
    gaze.add_argument("--caption-provider", choices=["glm", "gemini", "mock", "none"], default=os.environ.get("DISCO_GAZE_PROVIDER", "gemini"))
    gaze.add_argument("--no-ocr", action="store_true")
    gaze.add_argument("--mask-preset", default=os.environ.get("DISCO_GAZE_MASK", "mac-safe"))
    gaze.add_argument("--timeout", type=int, default=45)
    gaze.add_argument(
        "--allow-fullscreen-fallback",
        action="store_true",
        help="Allow gaze_local.py to capture fullscreen if the named window is missing.",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        if args.command == "health":
            print_json(request_json(args.url, "/health"))
        elif args.command == "state":
            print_json(request_json(args.url, "/state"))
        elif args.command == "continue":
            print_json(request_json(args.url, "/continue"))
        elif args.command == "choose":
            print_json(request_json(args.url, "/choose", {"index": args.index}))
        elif args.command == "click":
            print_json(
                request_json(
                    args.url,
                    "/click",
                    {"x": args.x, "y": args.y, "double": 1 if args.double else 0},
                )
            )
        elif args.command == "key":
            params: dict[str, Any] = {"name": args.name}
            if args.hold:
                params["hold"] = args.hold
            print_json(request_json(args.url, "/key", params))
        elif args.command == "screenshot":
            data = request_json(
                args.url,
                "/screenshot",
                {
                    "scale": args.scale,
                    "format": args.format,
                    "quality": args.quality,
                    "target": args.target,
                    "max_bytes": args.max_bytes,
                },
            )
            image_b64 = data.get("data")
            if args.out and image_b64:
                args.out.write_bytes(base64.b64decode(image_b64))
                data = {k: v for k, v in data.items() if k != "data"}
                data["written"] = str(args.out)
            print_json(data if args.out else {k: v for k, v in data.items() if k != "data"})
        elif args.command == "gaze":
            print_json(
                run_gaze_once(
                    window=args.window,
                    caption_provider=args.caption_provider,
                    ocr=not args.no_ocr,
                    mask_preset=args.mask_preset,
                    timeout=args.timeout,
                    strict_window=not args.allow_fullscreen_fallback,
                )
            )
    except Exception as exc:
        print(f"disco_client error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
