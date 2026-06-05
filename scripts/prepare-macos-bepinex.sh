#!/usr/bin/env bash
set -euo pipefail

GAME_ROOT="${1:-${DISCO_ELYSIUM_GAME_ROOT:-$HOME/Library/Application Support/Steam/steamapps/common/Disco Elysium}}"
APP_NAME="${DISCO_ELYSIUM_APP_NAME:-disco.app}"
APP_ROOT="$GAME_ROOT/$APP_NAME"
MACOS_DIR="$APP_ROOT/Contents/MacOS"
RESOURCES_DATA="../Resources/Data"
FRAMEWORKS_GAME_ASSEMBLY="../Frameworks/GameAssembly.dylib"
BEPINEX_CFG="$GAME_ROOT/BepInEx/config/BepInEx.cfg"

echo "Game root: $GAME_ROOT"
echo "App:       $APP_ROOT"

if [[ ! -d "$GAME_ROOT" ]]; then
  echo "Game root not found. Pass it explicitly:" >&2
  echo "  scripts/prepare-macos-bepinex.sh '/path/to/Steam/steamapps/common/Disco Elysium'" >&2
  exit 1
fi

if [[ ! -d "$MACOS_DIR" ]]; then
  echo "Could not find $MACOS_DIR." >&2
  echo "Set DISCO_ELYSIUM_APP_NAME if the app bundle has a different name." >&2
  exit 1
fi

ensure_symlink() {
  local link_path="$1"
  local target="$2"

  if [[ -L "$link_path" ]]; then
    local current
    current="$(readlink "$link_path")"
    if [[ "$current" == "$target" ]]; then
      echo "OK symlink: $link_path -> $target"
      return
    fi
    echo "Refusing to replace existing symlink: $link_path -> $current" >&2
    exit 1
  fi

  if [[ -e "$link_path" ]]; then
    echo "Refusing to replace existing file/directory: $link_path" >&2
    exit 1
  fi

  ln -s "$target" "$link_path"
  echo "Created symlink: $link_path -> $target"
}

ensure_symlink "$MACOS_DIR/Disco Elysium_Data" "$RESOURCES_DATA"
ensure_symlink "$MACOS_DIR/GameAssembly.so" "$FRAMEWORKS_GAME_ASSEMBLY"
ensure_symlink "$MACOS_DIR/libil2cpp.so" "$FRAMEWORKS_GAME_ASSEMBLY"

if [[ -f "$BEPINEX_CFG" ]]; then
  if grep -q '^ScanMethodRefs = true$' "$BEPINEX_CFG"; then
    perl -0pi -e 's/^ScanMethodRefs = true$/ScanMethodRefs = false/m' "$BEPINEX_CFG"
    echo "Updated: ScanMethodRefs = false"
  else
    echo "OK config: ScanMethodRefs is not true"
  fi
else
  echo "BepInEx config not found yet. Run BepInEx once, then rerun this script if interop generation fails."
fi

echo
echo "Next:"
echo "  cd '$GAME_ROOT'"
echo "  ./run_bepinex.sh"
