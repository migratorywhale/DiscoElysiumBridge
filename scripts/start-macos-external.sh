#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ -z "${GAZE_TOOL_DIR:-}" ]]; then
  if [[ -f "$HOME/Projects/gaze/gaze_local.py" ]]; then
    GAZE_TOOL_DIR="$HOME/Projects/gaze"
  else
    GAZE_TOOL_DIR="$HOME/Projects/gaze-xiaoke-tool"
  fi
fi
PYTHON="${DISCO_EXTERNAL_PYTHON:-$GAZE_TOOL_DIR/.venv/bin/python}"
HOST="${DISCO_EXTERNAL_HOST:-127.0.0.1}"
PORT="${DISCO_EXTERNAL_PORT:-7860}"

if [[ ! -x "$PYTHON" ]]; then
  echo "Python not found or not executable: $PYTHON" >&2
  echo "Set DISCO_EXTERNAL_PYTHON, or create the local gaze venv first." >&2
  exit 1
fi

exec "$PYTHON" "$REPO_ROOT/tools/macos_external_bridge.py" --host "$HOST" --port "$PORT"
