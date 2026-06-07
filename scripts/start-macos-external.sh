#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GAZE_TOOL_DIR="${GAZE_TOOL_DIR:-$HOME/Projects/gaze-xiaoke-tool}"
PYTHON="${DISCO_EXTERNAL_PYTHON:-$GAZE_TOOL_DIR/.venv/bin/python}"
HOST="${DISCO_EXTERNAL_HOST:-127.0.0.1}"
PORT="${DISCO_EXTERNAL_PORT:-7860}"

if [[ ! -x "$PYTHON" ]]; then
  echo "Python not found or not executable: $PYTHON" >&2
  echo "Set DISCO_EXTERNAL_PYTHON, or create the gaze-xiaoke-tool venv first." >&2
  exit 1
fi

exec "$PYTHON" "$REPO_ROOT/tools/macos_external_bridge.py" --host "$HOST" --port "$PORT"
