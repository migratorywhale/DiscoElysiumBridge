#!/usr/bin/env python3
"""External macOS HTTP bridge for Disco Elysium.

This fallback does not depend on the BepInEx plugin being loaded. It controls the
frontmost game window with CoreGraphics events and exposes the same basic HTTP
shape as DiscoElysiumBridge so the MCP wrapper can keep using one URL.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import tempfile
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except Exception:  # pragma: no cover - depends on local venv.
    Image = None  # type: ignore


VERSION = "0.3.0"
APP_BUNDLE_ID = os.environ.get("DISCO_APP_BUNDLE_ID", "com.zaumstudio.discoelysium")

try:
    import Quartz  # type: ignore
except Exception as exc:  # pragma: no cover - depends on local pyobjc install.
    Quartz = None  # type: ignore
    QUARTZ_ERROR = str(exc)
else:
    QUARTZ_ERROR = ""


KEY_CODES: dict[str, int] = {
    "a": 0,
    "s": 1,
    "d": 2,
    "f": 3,
    "h": 4,
    "g": 5,
    "z": 6,
    "x": 7,
    "c": 8,
    "v": 9,
    "b": 11,
    "q": 12,
    "w": 13,
    "e": 14,
    "r": 15,
    "y": 16,
    "t": 17,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "6": 22,
    "5": 23,
    "=": 24,
    "9": 25,
    "7": 26,
    "-": 27,
    "8": 28,
    "0": 29,
    "o": 31,
    "u": 32,
    "i": 34,
    "p": 35,
    "enter": 36,
    "return": 36,
    "l": 37,
    "j": 38,
    "k": 40,
    "n": 45,
    "m": 46,
    "tab": 48,
    "space": 49,
    "escape": 53,
    "esc": 53,
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f8": 100,
    "f9": 101,
    "f10": 109,
    "f11": 103,
    "f12": 111,
}


def activate_game() -> None:
    frontmost_script = (
        'tell application "System Events" to set frontmost of first application process '
        f'whose bundle identifier is "{APP_BUNDLE_ID}" to true'
    )
    result = subprocess.run(
        ["osascript", "-e", frontmost_script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=2,
        check=False,
    )
    if result.returncode != 0:
        subprocess.run(
            ["osascript", "-e", f'tell application id "{APP_BUNDLE_ID}" to activate'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    time.sleep(0.12)


def require_quartz() -> Any:
    if Quartz is None:
        raise RuntimeError(
            "Quartz is not available. Run with the gaze venv Python or install pyobjc-framework-Quartz. "
            f"Import error: {QUARTZ_ERROR}"
        )
    return Quartz


def post_key(name: str, hold_ms: int = 0) -> dict[str, Any]:
    q = require_quartz()
    key = name.lower()
    if key not in KEY_CODES:
        return {"error": f"unknown key {name!r}", "available": sorted(KEY_CODES)}

    activate_game()
    code = KEY_CODES[key]
    down = q.CGEventCreateKeyboardEvent(None, code, True)
    up = q.CGEventCreateKeyboardEvent(None, code, False)
    q.CGEventPost(q.kCGHIDEventTap, down)
    if hold_ms > 0:
        time.sleep(min(hold_ms, 5000) / 1000)
    else:
        time.sleep(0.05)
    q.CGEventPost(q.kCGHIDEventTap, up)
    return {"key": key, "held": hold_ms} if hold_ms > 0 else {"key": key, "pressed": True}


def post_click(x: int, y: int, double: bool = False) -> dict[str, Any]:
    q = require_quartz()
    activate_game()
    point = (x, y)
    for i in range(2 if double else 1):
        down = q.CGEventCreateMouseEvent(None, q.kCGEventLeftMouseDown, point, q.kCGMouseButtonLeft)
        up = q.CGEventCreateMouseEvent(None, q.kCGEventLeftMouseUp, point, q.kCGMouseButtonLeft)
        q.CGEventSetIntegerValueField(down, q.kCGMouseEventClickState, i + 1)
        q.CGEventSetIntegerValueField(up, q.kCGMouseEventClickState, i + 1)
        q.CGEventPost(q.kCGHIDEventTap, down)
        time.sleep(0.03)
        q.CGEventPost(q.kCGHIDEventTap, up)
        time.sleep(0.08)
    return {"clicked": True, "x": x, "y": y, "double": double}


def capture_screenshot(params: dict[str, list[str]]) -> dict[str, Any]:
    scale = clamp_float(one(params, "scale", "0.25"), 0.05, 1.0)
    quality = clamp_int(one(params, "quality", "35"), 10, 95)
    max_bytes = clamp_int(one(params, "max_bytes", "750000"), 20_000, 5_000_000)
    target = one(params, "target", "game").lower()
    activate_game()
    game_window = find_game_window() if target not in {"screen", "fullscreen", "desktop"} else None

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        path = Path(tmp.name)
    try:
        subprocess.run(["screencapture", "-x", "-t", "png", str(path)], check=True, timeout=10)
        if Image is None:
            data = path.read_bytes()
            return {
                "screenshot": True,
                "format": "png",
                "size": len(data),
                "data": base64.b64encode(data).decode("ascii"),
                "source": "macos-screencapture",
                "warning": "Pillow is not available; scale/quality/crop were skipped.",
            }

        image = Image.open(path).convert("RGB")
        source_width, source_height = image.size
        bbox = game_window["pixelBox"] if game_window else None
        cropped = False
        if bbox:
            left, top, right, bottom = clip_box(bbox, source_width, source_height)
            if right > left and bottom > top:
                image = image.crop((left, top, right, bottom))
                cropped = True

        if scale < 0.999:
            width, height = image.size
            image = image.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.Resampling.LANCZOS,
            )

        data, used_quality = encode_jpeg_under_limit(image, quality, max_bytes)
        width, height = image.size
        return {
            "screenshot": True,
            "format": "jpeg",
            "width": width,
            "height": height,
            "size": len(data),
            "scale": scale,
            "quality": used_quality,
            "target": "game" if cropped else "screen",
            "cropped": cropped,
            "gameWindow": game_window if cropped else None,
            "sourceWidth": source_width,
            "sourceHeight": source_height,
            "data": base64.b64encode(data).decode("ascii"),
            "source": "macos-screencapture",
        }
    finally:
        path.unlink(missing_ok=True)


def find_game_window() -> dict[str, Any] | None:
    if Quartz is None:
        return None

    display_scale = mac_screen_scale()
    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
    candidates: list[tuple[int, dict[str, Any]]] = []
    for win in windows or []:
        owner = str(win.get("kCGWindowOwnerName", "") or "")
        title = str(win.get("kCGWindowName", "") or "")
        layer = int(win.get("kCGWindowLayer", 0) or 0)
        alpha = float(win.get("kCGWindowAlpha", 1.0) or 0.0)
        haystack = f"{owner} {title}".lower()
        if "disco elysium" not in haystack:
            continue
        if layer != 0 or alpha <= 0:
            continue
        bounds = win.get("kCGWindowBounds") or {}
        point_x = float(bounds.get("X", 0) or 0)
        point_y = float(bounds.get("Y", 0) or 0)
        point_width = float(bounds.get("Width", 0) or 0)
        point_height = float(bounds.get("Height", 0) or 0)
        if point_width < 300 or point_height < 300:
            continue
        point_area = point_width * point_height
        if point_area < 250_000:
            continue

        pixel_x = int(point_x * display_scale)
        pixel_y = int(point_y * display_scale)
        pixel_width = int(point_width * display_scale)
        pixel_height = int(point_height * display_scale)
        info = {
            "owner": owner,
            "title": title,
            "windowNumber": int(win.get("kCGWindowNumber", 0) or 0),
            "displayScale": display_scale,
            "pointBox": {
                "x": point_x,
                "y": point_y,
                "width": point_width,
                "height": point_height,
            },
            "pixelBox": (pixel_x, pixel_y, pixel_x + pixel_width, pixel_y + pixel_height),
            "pixelBoxObject": {
                "x": pixel_x,
                "y": pixel_y,
                "width": pixel_width,
                "height": pixel_height,
            },
        }
        candidates.append((pixel_width * pixel_height, info))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def map_click_coordinates(x: int, y: int, params: dict[str, list[str]]) -> tuple[int, int, dict[str, Any]]:
    target = one(params, "target", "screen").lower()
    scale = clamp_float(one(params, "scale", "1.0"), 0.05, 1.0)
    if target in {"game", "window"}:
        game_window = find_game_window()
        if not game_window:
            raise RuntimeError("Disco Elysium window not found; launch the game or use target=screen absolute coordinates.")
        point_box = game_window["pointBox"]
        display_scale = float(game_window["displayScale"])
        mapped_x = int(round(float(point_box["x"]) + (x / (display_scale * scale))))
        mapped_y = int(round(float(point_box["y"]) + (y / (display_scale * scale))))
        return mapped_x, mapped_y, {
            "coordinateSpace": "game",
            "inputX": x,
            "inputY": y,
            "inputScale": scale,
            "gameWindow": game_window,
        }

    if target in {"screen-image", "fullscreen-image", "desktop-image"}:
        display_scale = mac_screen_scale()
        mapped_x = int(round(x / (display_scale * scale)))
        mapped_y = int(round(y / (display_scale * scale)))
        return mapped_x, mapped_y, {
            "coordinateSpace": target,
            "inputX": x,
            "inputY": y,
            "inputScale": scale,
            "displayScale": display_scale,
        }

    return x, y, {"coordinateSpace": "screen", "inputX": x, "inputY": y}


def mac_screen_scale() -> float:
    try:
        from AppKit import NSScreen

        screen = NSScreen.mainScreen()
        if screen:
            return float(screen.backingScaleFactor())
    except Exception:
        pass
    return 1.0


def clip_box(box: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    return (
        max(0, min(width, left)),
        max(0, min(height, top)),
        max(0, min(width, right)),
        max(0, min(height, bottom)),
    )


def encode_jpeg_under_limit(image: Any, quality: int, max_bytes: int) -> tuple[bytes, int]:
    from io import BytesIO

    current = image
    current_quality = quality
    for _ in range(8):
        buf = BytesIO()
        current.save(buf, format="JPEG", quality=current_quality, optimize=True)
        data = buf.getvalue()
        if len(data) <= max_bytes:
            return data, current_quality

        if current_quality > 25:
            current_quality = max(25, current_quality - 12)
            continue

        width, height = current.size
        if width <= 320 or height <= 240:
            return data, current_quality
        current = current.resize((max(1, int(width * 0.8)), max(1, int(height * 0.8))), Image.Resampling.LANCZOS)

    buf = BytesIO()
    current.save(buf, format="JPEG", quality=current_quality, optimize=True)
    return buf.getvalue(), current_quality


def choose_index(index: int) -> dict[str, Any]:
    if index < 0 or index > 9:
        return {"error": "keyboard only supports index 0-9"}
    key = str(index + 1) if index < 9 else "0"
    result = post_key(key)
    result.update({"chosen": index, "key": key})
    return result


def external_state() -> dict[str, Any]:
    return {
        "conversationActive": False,
        "source": "macos-external",
        "note": "External bridge cannot read in-game dialogue state; use disco_gaze for screen text.",
        "lastText": "",
        "lastSpeaker": "",
    }


def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "mod": "DiscoElysiumBridge",
        "mode": "macos-external",
        "version": VERSION,
        "quartz": Quartz is not None,
        "quartzError": QUARTZ_ERROR,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name.
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        try:
            payload = self.route(parsed.path, params)
        except Exception as exc:
            payload = {"error": str(exc)}
        self.respond(payload)

    def route(self, path: str, params: dict[str, list[str]]) -> dict[str, Any]:
        if path == "/health":
            return health()
        if path == "/state":
            return external_state()
        if path == "/continue":
            result = post_key("enter")
            result["continued"] = True
            return result
        if path == "/choose":
            return choose_index(int(one(params, "index", "0")))
        if path == "/click":
            x = int(one(params, "x"))
            y = int(one(params, "y"))
            double = one(params, "double", "0").lower() in {"1", "true", "yes"}
            mapped_x, mapped_y, mapping = map_click_coordinates(x, y, params)
            if one(params, "dry_run", "0").lower() in {"1", "true", "yes"}:
                return {
                    "clicked": False,
                    "dryRun": True,
                    "x": mapped_x,
                    "y": mapped_y,
                    "double": double,
                    "mapping": mapping,
                }
            result = post_click(mapped_x, mapped_y, double)
            result["mapping"] = mapping
            return result
        if path == "/key":
            name = one(params, "name")
            hold = int(one(params, "hold", "0"))
            return post_key(name, hold)
        if path == "/screenshot":
            return capture_screenshot(params)
        return {
            "error": "unknown endpoint",
            "endpoints": ["/health", "/state", "/choose", "/continue", "/click", "/key", "/screenshot"],
        }

    def respond(self, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[macos-external] {self.address_string()} {fmt % args}")


def one(params: dict[str, list[str]], key: str, default: str | None = None) -> str:
    values = params.get(key)
    if values:
        return values[0]
    if default is not None:
        return default
    raise ValueError(f"need {key} param")


def clamp_float(value: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except ValueError:
        parsed = minimum
    return max(minimum, min(parsed, maximum))


def clamp_int(value: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except ValueError:
        parsed = minimum
    return max(minimum, min(parsed, maximum))


def main() -> int:
    parser = argparse.ArgumentParser(description="External macOS bridge for Disco Elysium.")
    parser.add_argument("--host", default=os.environ.get("DISCO_EXTERNAL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DISCO_EXTERNAL_PORT", "7860")))
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"macOS external Disco bridge listening on http://{args.host}:{args.port}")
    print(json.dumps(health(), ensure_ascii=False))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
