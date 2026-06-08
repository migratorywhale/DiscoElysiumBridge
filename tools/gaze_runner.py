"""Run the local gaze tool once and return compact caption entries."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_GAZE_DIRS = (
    Path.home() / "Projects" / "gaze",
    Path.home() / "Projects" / "gaze-xiaoke-tool",
)


def default_gaze_dir() -> Path:
    for path in DEFAULT_GAZE_DIRS:
        if (path / "gaze_local.py").exists():
            return path
    return DEFAULT_GAZE_DIRS[0]


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
    caption_provider: str = "none",
    ocr: bool = True,
    mask_preset: str = "mac-safe",
    max_ocr_chars: int = 1200,
    timeout: int = 45,
    strict_window: bool = True,
) -> dict[str, Any]:
    gaze_dir = Path(os.environ.get("GAZE_TOOL_DIR", default_gaze_dir())).expanduser()
    gaze_local = gaze_dir / "gaze_local.py"

    if not gaze_local.exists():
        return {
            "ok": False,
            "error": f"gaze_local.py not found under {gaze_dir}",
            "hint": "Set GAZE_TOOL_DIR to the local gaze repo.",
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

    if window:
        activate_macos_app(os.environ.get("DISCO_APP_BUNDLE_ID", "com.zaumstudio.discoelysium"))

    cmd = build_gaze_command(
        gaze_dir=gaze_dir,
        gaze_local=gaze_local,
        window=window,
        caption_provider=caption_provider,
        ocr=ocr,
        mask_preset=mask_preset,
        max_ocr_chars=max_ocr_chars,
        strict_window=strict_window,
    )

    try:
        result = run_command(cmd, gaze_dir, timeout)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "window": window}
    retried_fullscreen = False
    combined_output = f"{result.stderr if result else ''}\n{result.stdout if result else ''}".lower()
    if strict_window and result is not None and result.returncode != 0 and "could not create image from window" in combined_output:
        # Unity/Metal fullscreen windows can be visible but unavailable to
        # `screencapture -l`. If we got this exact failure after activating the
        # game, fullscreen fallback is narrower than it sounds: it should be the
        # game itself.
        cmd = build_gaze_command(
            gaze_dir=gaze_dir,
            gaze_local=gaze_local,
            window="",
            caption_provider=caption_provider,
            ocr=ocr,
            mask_preset=mask_preset,
            max_ocr_chars=max_ocr_chars,
            strict_window=False,
        )
        try:
            result = run_command(cmd, gaze_dir, timeout)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "window": window}
        retried_fullscreen = True

    if result is None:
        return {"ok": False, "error": f"gaze timed out after {timeout}s", "window": window}

    entries = parse_gaze_entries(result.stdout)
    window_missing = "window not found" in result.stderr.lower()
    if window_missing and strict_window and not retried_fullscreen:
        entries = []

    response: dict[str, Any] = {
        "ok": result.returncode == 0 and not (window_missing and strict_window and not retried_fullscreen),
        "window": window,
        "caption_provider": caption_provider,
        "entries": entries,
    }

    if retried_fullscreen:
        response["fallback"] = "fullscreen-after-window-capture-failure"
    if not entries:
        response["message"] = "No gaze caption entries were produced."
    if window_missing and strict_window and not retried_fullscreen:
        response["error"] = f"window not found: {window!r}"
        response["hint"] = "Launch Disco Elysium first. Fullscreen fallback was suppressed."
    elif result.returncode != 0:
        response["error"] = tail_text(result.stderr or result.stdout)
    elif result.stderr.strip():
        response["warnings"] = tail_text(result.stderr)

    return response


def build_gaze_command(
    *,
    gaze_dir: Path,
    gaze_local: Path,
    window: str,
    caption_provider: str,
    ocr: bool,
    mask_preset: str,
    max_ocr_chars: int,
    strict_window: bool,
) -> list[str]:
    cmd = [
        gaze_python(gaze_dir),
        str(gaze_local),
        "--once",
        "--dry-run",
        "--caption-provider",
        caption_provider,
        "--batch-interval",
        "0",
        "--max-batch",
        "1",
        "--max-ocr-chars",
        str(max(1, int(max_ocr_chars))),
        "--mask-preset",
        mask_preset,
        "--auto-mask",
    ]
    if window:
        cmd.extend(["--window", window])
    if not ocr:
        cmd.append("--no-ocr")
    if strict_window:
        cmd.append("--strict-window")
    else:
        cmd.append("--allow-fullscreen-fallback")
    return cmd


def run_command(cmd: list[str], gaze_dir: Path, timeout: int) -> subprocess.CompletedProcess[str] | None:
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
        return None
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    return result


def activate_macos_app(bundle_id: str) -> None:
    frontmost_script = (
        'tell application "System Events" to set frontmost of first application process '
        f'whose bundle identifier is "{bundle_id}" to true'
    )
    result = subprocess.run(
        ["osascript", "-e", frontmost_script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        subprocess.run(
            ["osascript", "-e", f'tell application id "{bundle_id}" to activate'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    time.sleep(0.15)


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
