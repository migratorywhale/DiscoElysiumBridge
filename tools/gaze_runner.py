"""Run the local gaze tool once and return compact caption entries."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_GAZE_DIR = Path.home() / "Projects" / "gaze-xiaoke-tool"


def gaze_python(gaze_dir: Path) -> str:
    configured = os.environ.get("GAZE_PYTHON")
    if configured:
        return configured
    venv_python = gaze_dir / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def run_gaze_once(
    *,
    window: str = "Disco Elysium",
    caption_provider: str = "glm",
    ocr: bool = True,
    mask_preset: str = "mac-safe",
    timeout: int = 45,
    strict_window: bool = True,
) -> dict[str, Any]:
    gaze_dir = Path(os.environ.get("GAZE_TOOL_DIR", DEFAULT_GAZE_DIR)).expanduser()
    gaze_local = gaze_dir / "gaze_local.py"

    if not gaze_local.exists():
        return {
            "ok": False,
            "error": f"gaze_local.py not found under {gaze_dir}",
            "hint": "Set GAZE_TOOL_DIR to the gaze-xiaoke-tool repo.",
        }

    if window and strict_window:
        visible = macos_window_visible(window)
        if visible is False:
            return {
                "ok": False,
                "window": window,
                "error": f"window not found: {window!r}",
                "hint": "Launch Disco Elysium or pass allow-fullscreen-fallback for manual debugging.",
                "entries": [],
            }

    cmd = [
        gaze_python(gaze_dir),
        str(gaze_local),
        "--once",
        "--dry-run",
        "--window",
        window,
        "--caption-provider",
        caption_provider,
        "--batch-interval",
        "0",
        "--max-batch",
        "1",
        "--mask-preset",
        mask_preset,
        "--auto-mask",
    ]
    if not ocr:
        cmd.append("--no-ocr")
    if strict_window:
        cmd.append("--strict-window")

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(gaze_dir),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"gaze timed out after {timeout}s", "window": window}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "window": window}

    entries = parse_gaze_entries(result.stdout)
    window_missing = "window not found" in result.stderr.lower()
    if window_missing and strict_window:
        entries = []

    response: dict[str, Any] = {
        "ok": result.returncode == 0 and not (window_missing and strict_window),
        "window": window,
        "caption_provider": caption_provider,
        "entries": entries,
    }

    if not entries:
        response["message"] = "No gaze caption entries were produced."
    if window_missing and strict_window:
        response["error"] = f"window not found: {window!r}"
        response["hint"] = "Launch Disco Elysium first. Fullscreen fallback was suppressed."
    elif result.returncode != 0:
        response["error"] = tail_text(result.stderr or result.stdout)
    elif result.stderr.strip():
        response["warnings"] = tail_text(result.stderr)

    return response


def macos_window_visible(needle: str) -> bool | None:
    try:
        import Quartz  # type: ignore
    except Exception:
        return None

    needle_lower = needle.lower()
    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
    for win in windows:
        owner = str(win.get("kCGWindowOwnerName", "") or "")
        title = str(win.get("kCGWindowName", "") or "")
        haystack = f"{owner} {title}".lower()
        if needle_lower not in haystack:
            continue
        bounds = win.get("kCGWindowBounds") or {}
        if int(bounds.get("Width", 0)) > 0 and int(bounds.get("Height", 0)) > 0:
            return True
    return False


def parse_gaze_entries(stdout: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        text = line.strip()
        if not text or text[0] not in "[{":
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
        elif isinstance(payload, list):
            entries.extend(item for item in payload if isinstance(item, dict))
    return entries


def tail_text(text: str, max_chars: int = 1200) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return "..." + text[-max_chars:]
