#!/usr/bin/env bash
set -euo pipefail

GAME_ROOT="${1:-${DISCO_ELYSIUM_GAME_ROOT:-$HOME/Library/Application Support/Steam/steamapps/common/Disco Elysium}}"
BEPINEX_CORE="$GAME_ROOT/BepInEx/core"
BEPINEX_DLL="$BEPINEX_CORE/BepInEx.Unity.IL2CPP.dll"
CECIL_DLL="$BEPINEX_CORE/Mono.Cecil.dll"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PATCHER_SRC="$REPO_ROOT/tools/PatchBepInExImmediateExecute.cs"
WORK_DIR="${TMPDIR:-/tmp}/disco-bepinex-runtime-patcher"

if [[ ! -f "$BEPINEX_DLL" ]]; then
  echo "BepInEx.Unity.IL2CPP.dll not found: $BEPINEX_DLL" >&2
  exit 1
fi

if [[ ! -f "$CECIL_DLL" ]]; then
  echo "Mono.Cecil.dll not found: $CECIL_DLL" >&2
  exit 1
fi

rm -rf "$WORK_DIR"
dotnet new console --force --output "$WORK_DIR" >/dev/null
cp "$PATCHER_SRC" "$WORK_DIR/Program.cs"

python3 - "$WORK_DIR/disco-bepinex-runtime-patcher.csproj" "$CECIL_DLL" <<'PY'
from pathlib import Path
import sys

csproj = Path(sys.argv[1])
cecil = sys.argv[2]
text = csproj.read_text()
insert = f'''
  <ItemGroup>
    <Reference Include="Mono.Cecil">
      <HintPath>{cecil}</HintPath>
    </Reference>
  </ItemGroup>
'''
text = text.replace("</Project>", insert + "\n</Project>")
csproj.write_text(text)
PY

dotnet build "$WORK_DIR/disco-bepinex-runtime-patcher.csproj" >/dev/null
dotnet "$WORK_DIR/bin/Debug/net8.0/disco-bepinex-runtime-patcher.dll" "$BEPINEX_DLL"

echo
echo "Done. Start Disco Elysium with BepInEx:"
echo "  cd '$GAME_ROOT'"
echo "  ./run_bepinex.sh"
