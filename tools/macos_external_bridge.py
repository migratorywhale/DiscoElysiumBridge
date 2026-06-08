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
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except Exception:  # pragma: no cover - depends on local venv.
    Image = None  # type: ignore


VERSION = "0.3.9"
APP_BUNDLE_ID = os.environ.get("DISCO_APP_BUNDLE_ID", "com.zaumstudio.discoelysium")
DEFAULT_GAME_SCALE = 0.4
LAST_GAME_CAPTURE_TTL_SECONDS = 60.0
LAST_GAME_CAPTURE: dict[str, Any] | None = None

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
    global LAST_GAME_CAPTURE

    scale = clamp_float(one(params, "scale", str(DEFAULT_GAME_SCALE)), 0.05, 1.0)
    quality = clamp_int(one(params, "quality", "35"), 10, 95)
    max_bytes = clamp_int(one(params, "max_bytes", "750000"), 20_000, 5_000_000)
    target = one(params, "target", "game").lower()
    reusable_capture = recent_game_capture() if one(params, "reuse_last_capture", "0").lower() in {"1", "true", "yes"} else None
    if reusable_capture and target not in {"screen", "fullscreen", "desktop"}:
        game_window = reusable_capture.get("gameWindow")
        preset_crop_box = reusable_capture.get("cropPixelBox")
    else:
        activate_game()
        game_window = find_game_window() if target not in {"screen", "fullscreen", "desktop"} else None
        preset_crop_box = None

    if Image is None:
        return capture_png_with_screencapture()

    image, capture_source, capture_warning = capture_display_image()
    source_width, source_height = image.size
    bbox = preset_crop_box or (game_window["pixelBox"] if game_window else None)
    cropped = False
    crop_box = None
    if bbox:
        left, top, right, bottom = clip_box(bbox, source_width, source_height)
        if right > left and bottom > top:
            crop_box = (left, top, right, bottom)
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
    if cropped and game_window and crop_box:
        LAST_GAME_CAPTURE = {
            "capturedAt": time.monotonic(),
            "scale": scale,
            "cropPixelBox": crop_box,
            "displayScale": float(game_window["displayScale"]),
            "sourceWidth": source_width,
            "sourceHeight": source_height,
            "width": width,
            "height": height,
            "gameWindow": game_window,
        }
    elif target not in {"screen", "fullscreen", "desktop"}:
        LAST_GAME_CAPTURE = None
    payload = {
        "screenshot": True,
        "format": "jpeg",
        "width": width,
        "height": height,
        "size": len(data),
        "scale": scale,
        "quality": used_quality,
        "target": "game" if cropped else "screen",
        "cropped": cropped,
        "cropPixelBox": crop_box,
        "gameWindow": game_window if cropped else None,
        "sourceWidth": source_width,
        "sourceHeight": source_height,
        "data": base64.b64encode(data).decode("ascii"),
        "source": capture_source,
    }
    if capture_warning:
        payload["warning"] = capture_warning
    return payload


def capture_display_image() -> tuple[Any, str, str | None]:
    if Quartz is not None:
        try:
            return capture_display_image_with_quartz(), "macos-quartz-display", None
        except Exception as exc:
            image = capture_display_image_with_screencapture()
            return image, "macos-screencapture", f"Quartz capture failed; fell back to screencapture: {exc}"
    return capture_display_image_with_screencapture(), "macos-screencapture", None


def capture_display_image_with_quartz() -> Any:
    q = require_quartz()
    cg_image = q.CGDisplayCreateImage(q.CGMainDisplayID())
    if cg_image is None:
        raise RuntimeError("CGDisplayCreateImage returned None")
    width = q.CGImageGetWidth(cg_image)
    height = q.CGImageGetHeight(cg_image)
    bytes_per_row = q.CGImageGetBytesPerRow(cg_image)
    provider = q.CGImageGetDataProvider(cg_image)
    data = q.CGDataProviderCopyData(provider)
    image = Image.frombuffer("RGBA", (width, height), bytes(data), "raw", "BGRA", bytes_per_row, 1)
    return image.convert("RGB")


def capture_display_image_with_screencapture() -> Any:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        path = Path(tmp.name)
    try:
        subprocess.run(["screencapture", "-x", "-t", "png", str(path)], check=True, timeout=10)
        return Image.open(path).convert("RGB")
    finally:
        path.unlink(missing_ok=True)


def capture_png_with_screencapture() -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        path = Path(tmp.name)
    try:
        subprocess.run(["screencapture", "-x", "-t", "png", str(path)], check=True, timeout=10)
        data = path.read_bytes()
        return {
            "screenshot": True,
            "format": "png",
            "size": len(data),
            "data": base64.b64encode(data).decode("ascii"),
            "source": "macos-screencapture",
            "warning": "Pillow is not available; scale/quality/crop were skipped.",
        }
    finally:
        path.unlink(missing_ok=True)


def detect_markers(params: dict[str, list[str]]) -> dict[str, Any]:
    if Image is None:
        return {"error": "Pillow is not available; cannot detect markers."}

    data = capture_screenshot(params)
    image_b64 = data.get("data")
    if not image_b64:
        return {"error": "screenshot capture failed", "capture": data}

    image = Image.open(BytesIO(base64.b64decode(image_b64))).convert("RGB")
    markers = detect_green_markers(image)
    scale = float(data.get("scale") or DEFAULT_GAME_SCALE)
    crop_box = data.get("cropPixelBox")
    game_window = data.get("gameWindow")
    display_scale = float(game_window.get("displayScale", mac_screen_scale())) if isinstance(game_window, dict) else mac_screen_scale()
    crop_left = float(crop_box[0]) if isinstance(crop_box, (list, tuple)) and len(crop_box) >= 2 else 0.0
    crop_top = float(crop_box[1]) if isinstance(crop_box, (list, tuple)) and len(crop_box) >= 2 else 0.0

    for marker in markers:
        marker["click"] = {"x": marker["x"], "y": marker["y"], "target": "game", "scale": scale}
        marker["screenPoint"] = {
            "x": int(round((crop_left + (marker["x"] / scale)) / display_scale)),
            "y": int(round((crop_top + (marker["y"] / scale)) / display_scale)),
        }

    meta = {key: value for key, value in data.items() if key != "data"}
    return {"markers": markers, "count": len(markers), "screenshot": meta}


def click_watch(params: dict[str, list[str]]) -> dict[str, Any]:
    click_result = perform_click(params)
    remember_click_mapping_as_capture(click_result)
    frame_count = clamp_int(one(params, "frames", "3"), 1, 5)
    interval_ms = clamp_int(one(params, "interval_ms", "150"), 0, 1000)
    frame_params = {
        "target": [one(params, "target", "game")],
        "scale": [one(params, "watch_scale", one(params, "scale", str(DEFAULT_GAME_SCALE)))],
        "quality": [one(params, "quality", "35")],
        "max_bytes": [one(params, "max_bytes", "350000")],
        "reuse_last_capture": ["1"],
    }
    frames: list[dict[str, Any]] = []
    started = time.monotonic()
    for index in range(frame_count):
        if index > 0 and interval_ms > 0:
            time.sleep(interval_ms / 1000)
        frame = capture_screenshot(frame_params)
        frame["frame"] = index
        frame["afterClickMs"] = int(round((time.monotonic() - started) * 1000))
        frames.append(frame)
    return {"click": click_result, "frames": frames}


def remember_click_mapping_as_capture(click_result: dict[str, Any]) -> None:
    global LAST_GAME_CAPTURE

    mapping = click_result.get("mapping")
    if not isinstance(mapping, dict):
        return
    crop_box = mapping.get("cropPixelBox")
    game_window = mapping.get("gameWindow")
    if not crop_box or not isinstance(game_window, dict):
        return
    LAST_GAME_CAPTURE = {
        "capturedAt": time.monotonic(),
        "scale": float(mapping.get("inputScale") or DEFAULT_GAME_SCALE),
        "cropPixelBox": crop_box,
        "displayScale": float(game_window.get("displayScale", mac_screen_scale())),
        "gameWindow": game_window,
    }


def detect_green_markers(image: Any) -> list[dict[str, Any]]:
    width, height = image.size
    points: list[tuple[int, int]] = []
    for y in range(height):
        for x in range(width):
            r, g, b = image.getpixel((x, y))
            if g > 140 and b > 100 and r < 135 and g > r + 35:
                points.append((x, y))

    raw_components = connected_components(points)
    merged = merge_nearby_components(raw_components)
    markers: list[dict[str, Any]] = []
    for index, comp in enumerate(sorted(merged, key=lambda item: (item["y"], item["x"])), 1):
        markers.append(
            {
                "id": index,
                "x": comp["x"],
                "y": comp["y"],
                "box": comp["box"],
                "pixels": comp["pixels"],
            }
        )
    return markers


def connected_components(points: list[tuple[int, int]]) -> list[dict[str, Any]]:
    point_set = set(points)
    seen: set[tuple[int, int]] = set()
    components: list[dict[str, Any]] = []
    for point in points:
        if point in seen:
            continue
        stack = [point]
        seen.add(point)
        xs: list[int] = []
        ys: list[int] = []
        while stack:
            cx, cy = stack.pop()
            xs.append(cx)
            ys.append(cy)
            for nx in range(cx - 2, cx + 3):
                for ny in range(cy - 2, cy + 3):
                    neighbor = (nx, ny)
                    if neighbor in point_set and neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
        if len(xs) >= 10:
            components.append(component_from_points(xs, ys))
    return components


def merge_nearby_components(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending = components[:]
    merged: list[dict[str, Any]] = []
    while pending:
        current = pending.pop(0)
        changed = True
        while changed:
            changed = False
            rest: list[dict[str, Any]] = []
            for candidate in pending:
                dx = current["x"] - candidate["x"]
                dy = current["y"] - candidate["y"]
                if (dx * dx + dy * dy) ** 0.5 <= 18:
                    current = merge_components(current, candidate)
                    changed = True
                else:
                    rest.append(candidate)
            pending = rest
        merged.append(current)
    return merged


def merge_components(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    left = min(a["box"][0], b["box"][0])
    top = min(a["box"][1], b["box"][1])
    right = max(a["box"][2], b["box"][2])
    bottom = max(a["box"][3], b["box"][3])
    pixels = int(a["pixels"]) + int(b["pixels"])
    return {
        "x": int(round(((a["x"] * int(a["pixels"])) + (b["x"] * int(b["pixels"]))) / pixels)),
        "y": int(round(((a["y"] * int(a["pixels"])) + (b["y"] * int(b["pixels"]))) / pixels)),
        "box": [left, top, right, bottom],
        "pixels": pixels,
    }


def component_from_points(xs: list[int], ys: list[int]) -> dict[str, Any]:
    return {
        "x": int(round(sum(xs) / len(xs))),
        "y": int(round(sum(ys) / len(ys))),
        "box": [min(xs), min(ys), max(xs), max(ys)],
        "pixels": len(xs),
    }


def find_game_window(retries: int = 3, delay: float = 0.12, *, allow_frontmost_screen: bool = True) -> dict[str, Any] | None:
    if Quartz is None:
        return None

    for attempt in range(max(1, retries)):
        window = find_game_window_once()
        if window:
            return window
        if attempt < retries - 1:
            time.sleep(delay)

    if allow_frontmost_screen and is_game_frontmost():
        return main_screen_game_window()

    return None


def find_game_window_once() -> dict[str, Any] | None:
    display_scale = mac_screen_scale()
    screen_pixel_box = main_screen_pixel_box()
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
        visible_box = intersect_box(
            (pixel_x, pixel_y, pixel_x + pixel_width, pixel_y + pixel_height),
            screen_pixel_box,
        )
        visible_width = max(0, visible_box[2] - visible_box[0])
        visible_height = max(0, visible_box[3] - visible_box[1])
        # During fullscreen/Space transitions, CGWindow can briefly report a
        # real game window with a negative/off-screen X. Cropping that produces
        # a useless vertical strip, and click mapping misses the visible game.
        # Treat mostly-offscreen candidates as absent and let the frontmost
        # screen fallback handle fullscreen play.
        if visible_width < pixel_width * 0.9 or visible_height < pixel_height * 0.9:
            continue
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
            "visiblePixelBox": visible_box,
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


def is_game_frontmost() -> bool:
    script = (
        'tell application "System Events" to get bundle identifier of first application process '
        "whose frontmost is true"
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return False
    return result.stdout.strip() == APP_BUNDLE_ID


def main_screen_game_window() -> dict[str, Any] | None:
    try:
        from AppKit import NSScreen

        screen = NSScreen.mainScreen()
        if not screen:
            return None
        frame = screen.frame()
        scale = float(screen.backingScaleFactor())
        point_x = float(frame.origin.x)
        point_y = float(frame.origin.y)
        point_width = float(frame.size.width)
        point_height = float(frame.size.height)
    except Exception:
        scale = mac_screen_scale()
        point_x = 0.0
        point_y = 0.0
        point_width = float(Quartz.CGDisplayPixelsWide(Quartz.CGMainDisplayID()) / scale)
        point_height = float(Quartz.CGDisplayPixelsHigh(Quartz.CGMainDisplayID()) / scale)

    pixel_x = int(point_x * scale)
    pixel_y = int(point_y * scale)
    pixel_width = int(point_width * scale)
    pixel_height = int(point_height * scale)
    return {
        "owner": "Disco Elysium",
        "title": "frontmost screen fallback",
        "windowNumber": 0,
        "displayScale": scale,
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
        "fallback": "frontmost-main-screen",
    }


def main_screen_pixel_box() -> tuple[int, int, int, int]:
    try:
        from AppKit import NSScreen

        screen = NSScreen.mainScreen()
        if not screen:
            raise RuntimeError("NSScreen.mainScreen() returned None")
        frame = screen.frame()
        scale = float(screen.backingScaleFactor())
        width = int(float(frame.size.width) * scale)
        height = int(float(frame.size.height) * scale)
    except Exception:
        try:
            width = int(Quartz.CGDisplayPixelsWide(Quartz.CGMainDisplayID()))
            height = int(Quartz.CGDisplayPixelsHigh(Quartz.CGMainDisplayID()))
        except Exception:
            scale = mac_screen_scale()
            width = int(1440 * scale)
            height = int(900 * scale)
    return (0, 0, width, height)


def intersect_box(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    return (
        max(a[0], b[0]),
        max(a[1], b[1]),
        min(a[2], b[2]),
        min(a[3], b[3]),
    )


def map_click_coordinates(x: int, y: int, params: dict[str, list[str]]) -> tuple[int, int, dict[str, Any]]:
    target = one(params, "target", "screen").lower()
    scale = clamp_float(one(params, "scale", str(DEFAULT_GAME_SCALE)), 0.05, 1.0)
    if target in {"game", "window"}:
        activate_game()
        last_capture = recent_game_capture()
        game_window = last_capture.get("gameWindow") if last_capture else find_game_window(retries=5, delay=0.18)
        if not game_window and not last_capture:
            raise RuntimeError("Disco Elysium window not found; launch the game or use target=screen absolute coordinates.")
        display_scale = float(last_capture["displayScale"] if last_capture else game_window["displayScale"])
        crop_box = last_capture["cropPixelBox"] if last_capture else game_window.get("visiblePixelBox") or game_window["pixelBox"]
        crop_left, crop_top = float(crop_box[0]), float(crop_box[1])
        mapped_x = int(round((crop_left + (x / scale)) / display_scale))
        mapped_y = int(round((crop_top + (y / scale)) / display_scale))
        return mapped_x, mapped_y, {
            "coordinateSpace": "game",
            "inputX": x,
            "inputY": y,
            "inputScale": scale,
            "cropPixelBox": crop_box,
            "mappingSource": "last-game-screenshot" if last_capture else "current-window",
            "lastCaptureAge": round(time.monotonic() - last_capture["capturedAt"], 3) if last_capture else None,
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


def recent_game_capture() -> dict[str, Any] | None:
    if not LAST_GAME_CAPTURE:
        return None
    if time.monotonic() - float(LAST_GAME_CAPTURE["capturedAt"]) > LAST_GAME_CAPTURE_TTL_SECONDS:
        return None
    return LAST_GAME_CAPTURE


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


def perform_click(params: dict[str, list[str]]) -> dict[str, Any]:
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
            return perform_click(params)
        if path == "/click-watch":
            return click_watch(params)
        if path == "/key":
            name = one(params, "name")
            hold = int(one(params, "hold", "0"))
            return post_key(name, hold)
        if path == "/screenshot":
            return capture_screenshot(params)
        if path == "/markers":
            return detect_markers(params)
        return {
            "error": "unknown endpoint",
            "endpoints": ["/health", "/state", "/choose", "/continue", "/click", "/click-watch", "/key", "/screenshot", "/markers"],
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
