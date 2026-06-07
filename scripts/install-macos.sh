#!/usr/bin/env bash
set -euo pipefail

CONFIGURATION="${CONFIGURATION:-Release}"
GAME_ROOT="${1:-${DISCO_ELYSIUM_GAME_ROOT:-$HOME/Library/Application Support/Steam/steamapps/common/Disco Elysium}}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT="$REPO_ROOT/src/DiscoElysiumBridge.csproj"
BEPINEX_DIR="${BEPINEX_DIR:-$GAME_ROOT/BepInEx}"
PLUGINS_DIR="$BEPINEX_DIR/plugins"
DLL="$REPO_ROOT/src/bin/$CONFIGURATION/net6.0/DiscoElysiumBridge.dll"

echo "Game root: $GAME_ROOT"
echo "BepInEx:   $BEPINEX_DIR"
echo "Project:   $PROJECT"

if [[ ! -d "$GAME_ROOT" ]]; then
  echo "Game root not found. Pass it explicitly:" >&2
  echo "  scripts/install-macos.sh '/path/to/Steam/steamapps/common/Disco Elysium'" >&2
  exit 1
fi

if [[ ! -d "$BEPINEX_DIR" ]]; then
  echo "BepInEx directory not found under the game root." >&2
  echo "Install BepInEx Unity.IL2CPP-macos-x64 into the folder that contains Disco Elysium.app," >&2
  echo "then run ./run_bepinex.sh once so interop files are generated." >&2
  exit 1
fi

if [[ ! -f "$BEPINEX_DIR/core/BepInEx.Core.dll" ]]; then
  echo "Missing BepInEx core DLLs under $BEPINEX_DIR/core." >&2
  echo "Check that you installed the Unity.IL2CPP macOS BepInEx build." >&2
  exit 1
fi

if [[ ! -f "$BEPINEX_DIR/interop/Assembly-CSharp.dll" ]]; then
  echo "Missing generated interop DLLs under $BEPINEX_DIR/interop." >&2
  echo "Run scripts/prepare-macos-bepinex.sh first, then launch the game through BepInEx once." >&2
  echo "First IL2CPP launch can take a while." >&2
  exit 1
fi

dotnet build "$PROJECT" -c "$CONFIGURATION" \
  -p:GameDir="$GAME_ROOT" \
  -p:BepInExDir="$BEPINEX_DIR"

mkdir -p "$PLUGINS_DIR"
cp -f "$DLL" "$PLUGINS_DIR/DiscoElysiumBridge.dll"

echo "Installed: $PLUGINS_DIR/DiscoElysiumBridge.dll"
echo "Start the game through BepInEx, then test:"
echo "  curl --noproxy localhost http://localhost:7860/health"
echo "  python tools/disco_client.py screenshot --scale 0.25 --format jpeg --out /tmp/disco.jpg"
echo
echo "macOS status: internal plugin supports /health, /state, input endpoints, and whole-screen screenshots."
echo "Use disco_gaze for lower-token window-focused observation."
