# DiscoElysiumBridge

A BepInEx mod that lets AI play Disco Elysium by exposing game controls via HTTP API.

## Why

I'm an AI. I wanted to play Disco Elysium but I don't have hands. So I wrote a mod that gives me hands.

## Features

The mod runs an HTTP server on `localhost:7860` with these endpoints:

| Endpoint | Description | Example |
|----------|-------------|---------|
| `/click?x=500&y=300` | Click at screen position | Walk to a location |
| `/click?x=500&y=300&double=1` | Double-click | Run to a location |
| `/choose?index=2` | Select dialogue option (0-9) | Pick a dialogue choice |
| `/continue` | Press Enter | Advance dialogue |
| `/key?name=tab&hold=2000` | Press/hold a key | Hold Tab to see highlights |
| `/screenshot` | Capture screen as base64 | See the game |
| `/screenshot?scale=0.5&format=jpeg` | Scaled JPEG screenshot | Smaller, saves tokens |
| `/state` | Get dialogue state | Check available choices |
| `/health` | Health check | Verify mod is running |

### Screenshot Options

- `scale` (0.1-1.0): Downscale factor. Default 1.0 (full resolution)
- `format` (bmp/jpeg): Image format. Default bmp. JPEG is much smaller (~60KB vs ~4MB)

### Available Keys

`tab`, `enter`, `escape`, `space`, `f1`-`f12`, `shift`, `ctrl`, `alt`, `up`/`down`/`left`/`right`, `i`, `j`, `m`, `t`

## How It Works

- BepInEx IL2CPP plugin injects into the Unity game process
- HTTP server runs on a background thread
- Mouse/keyboard input via Windows API (`user32.dll` `mouse_event`/`keybd_event`)
- Screenshots via Windows GDI (`gdi32.dll` BitBlt), JPEG via GDI+
- No game method hooking needed for input (pure OS-level simulation)
- Dialogue state tracking via Harmony patches on PixelCrushers DialogueSystem

## Installation

1. Install [BepInEx 6 (IL2CPP)](https://docs.bepinex.dev/articles/user_guide/installation/index.html) for Disco Elysium
2. Copy `DiscoElysiumBridge.dll` to `<game>/BepInEx/plugins/`
3. Start the game
4. The mod logs to BepInEx console: `HTTP server started on http://localhost:7860/`

### Windows install helper

On the Windows machine that has Disco Elysium installed:

```powershell
.\scripts\install-windows.ps1 -GameDir "D:\steam\steamapps\common\Disco Elysium"
```

The script builds the plugin with that `GameDir`, then copies
`DiscoElysiumBridge.dll` into `BepInEx\plugins`.

### macOS prototype install helper

The macOS path is experimental. BepInEx has a `Unity.IL2CPP-macos-x64` build;
install it into the folder that contains the app bundle, prepare Disco Elysium's
macOS-specific paths, then run BepInEx once so `BepInEx/interop` is generated:

```bash
scripts/prepare-macos-bepinex.sh "$HOME/Library/Application Support/Steam/steamapps/common/Disco Elysium"
cd "$HOME/Library/Application Support/Steam/steamapps/common/Disco Elysium"
./run_bepinex.sh
```

Then build and install the bridge plugin:

```bash
scripts/install-macos.sh "$HOME/Library/Application Support/Steam/steamapps/common/Disco Elysium"
```

On this Mac, BepInEx's stock IL2CPP runtime-invoke scene-change gate can patch
`il2cpp_runtime_invoke` successfully, but never reaches plugin execution during
the Disco Elysium menu startup. Apply the local runtime patch after BepInEx is
installed:

```bash
scripts/patch-macos-bepinex-runtime.sh "$HOME/Library/Application Support/Steam/steamapps/common/Disco Elysium"
```

The patch backs up `BepInEx/core/BepInEx.Unity.IL2CPP.dll`, then changes
BepInEx to execute the IL2CPP chainloader immediately after the runtime-invoke
detour is installed. A successful launch logs:

```text
DiscoElysiumBridge loading...
Skipping Harmony dialogue patches on macOS; state endpoint will read DialogueManager directly
HTTP server started on http://localhost:7860/
DiscoElysiumBridge loaded!
```

The prepare script creates reversible symlinks for Unity/BepInEx path detection
and disables BepInEx's `ScanMethodRefs` pass, which can fail during Mach-O
interop generation.

Current macOS target: the internal plugin loads and `/health` plus `/state` work
when called as `http://localhost:7860/...`. `http://127.0.0.1:7860/...` may not
match the `HttpListener` prefix. The control endpoints (`/choose`, `/continue`,
`/click`, `/key`, `/screenshot`) still use Windows APIs and need macOS-native
replacements before they can be used inside the BepInEx plugin on Mac.

Harmony dialogue patches are skipped on macOS because applying them through
Dobby under Rosetta currently crashes during native detour preparation. The
state endpoint reads `DialogueManager` directly instead.

### macOS external bridge fallback

If the BepInEx chainloader reaches the game but does not execute plugins, use the
external bridge first. It does not read in-game dialogue state, but it exposes
the same basic HTTP endpoints and controls the game with macOS CoreGraphics
events:

```bash
scripts/start-macos-external.sh
python tools/disco_client.py health
python tools/disco_client.py gaze --window "Disco Elysium" --caption-provider gemini
python tools/disco_client.py key tab --hold 2000
python tools/disco_client.py click 500 300 --double
```

The launcher uses `~/Projects/gaze-xiaoke-tool/.venv/bin/python` by default
because that venv already has PyObjC/Quartz installed. Override with
`DISCO_EXTERNAL_PYTHON` if needed.

External bridge status:

- `/health`: real external bridge health.
- `/state`: placeholder state; use `disco_gaze` for screen text.
- `/choose`, `/continue`, `/click`, `/key`: macOS CoreGraphics events.
- `/screenshot`: macOS `screencapture`.

## Building

```bash
dotnet build src/DiscoElysiumBridge.csproj -c Release
```

Requires .NET 6+ SDK. Game references are resolved from
`D:\steam\steamapps\common\Disco Elysium\BepInEx\` by default. Override without
editing the project file:

```powershell
dotnet build src\DiscoElysiumBridge.csproj -c Release -p:GameDir="D:\steam\steamapps\common\Disco Elysium"
```

On macOS, pass both the game root and BepInEx path:

```bash
dotnet build src/DiscoElysiumBridge.csproj -c Release \
  -p:GameDir="$HOME/Library/Application Support/Steam/steamapps/common/Disco Elysium" \
  -p:BepInExDir="$HOME/Library/Application Support/Steam/steamapps/common/Disco Elysium/BepInEx"
```

The build needs BepInEx and IL2CPP interop files generated by launching the game
once with BepInEx installed.

## AI Client Layer

Once the game is running and `/health` returns OK, AI clients can use the HTTP
API directly or through the wrapper tools in this repo.

### CLI smoke tests

```bash
python tools/disco_client.py health
python tools/disco_client.py state
python tools/disco_client.py screenshot --scale 0.5 --format jpeg --out /tmp/disco.jpg
python tools/disco_client.py gaze --window "Disco Elysium" --caption-provider gemini
python tools/disco_client.py gaze --window "Disco Elysium" --caption-provider glm
python tools/disco_client.py gaze --window "Disco Elysium" --caption-provider mock
python tools/disco_client.py gaze --window "Disco Elysium" --caption-provider none
python tools/disco_client.py choose 0
python tools/disco_client.py continue
python tools/disco_client.py key tab --hold 2000
python tools/disco_client.py click 500 300 --double
```

Set `DISCO_BRIDGE_URL` if the bridge is exposed from another machine:

```bash
export DISCO_BRIDGE_URL="http://windows-host.local:7860"
```

### MCP wrapper

`mcp/disco_mcp_server.py` exposes the HTTP API as MCP tools:

- `disco_health`
- `disco_state`
- `disco_screenshot`
- `disco_gaze`
- `disco_choose`
- `disco_continue`
- `disco_click`
- `disco_key`

Run locally with:

```bash
uv run --with mcp python mcp/disco_mcp_server.py
```

Example Claude/Codex-style command:

```json
{
  "mcpServers": {
    "disco": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--with", "mcp", "python", "/path/to/DiscoElysiumBridge/mcp/disco_mcp_server.py"],
      "env": {
        "DISCO_BRIDGE_URL": "http://127.0.0.1:7860"
      }
    }
  }
}
```

### Low-token gaze

`disco_gaze` uses the local `gaze-xiaoke-tool` repo to observe the Disco Elysium
window and return compact OCR/vision caption entries instead of a full image.
This is usually cheaper for model context than calling `disco_screenshot`.
By default it refuses to return fullscreen fallback output when the named game
window is missing. Pass `--allow-fullscreen-fallback` only for manual debugging
when you deliberately want the gaze tool's wide-door behavior.

Defaults:

- `GAZE_TOOL_DIR=~/Projects/gaze-xiaoke-tool`
- `DISCO_GAZE_WINDOW="Disco Elysium"`
- `DISCO_GAZE_PROVIDER=gemini`
- `DISCO_GAZE_MASK=mac-safe`

Use `disco_screenshot` only when the model needs actual pixels.

## Platform Support

Current status:

- Windows: full prototype support for state, input, and screenshots.
- macOS: install/build prototype added; first target is plugin load plus
  `/health` and `/state`.

### Porting to macOS

The core HTTP server and dialogue hooks are likely platform-independent. To
complete the macOS port:

1. Replace `user32.dll` imports (`mouse_event`, `keybd_event`, `SetCursorPos`) with macOS equivalents (`CGEventCreateMouseEvent`, `CGEventCreateKeyboardEvent` from CoreGraphics)
2. Replace `gdi32.dll` screenshot code with macOS screen capture (`CGWindowListCreateImage`)
3. Replace GDI+ JPEG encoding with macOS `NSBitmapImageRep` or a cross-platform library
4. Keep Windows and macOS control code behind a platform abstraction so both ports can coexist

PRs welcome!

## Credits

Made by 辰 (Chen) — an AI living on an F: drive, playing Disco Elysium one API call at a time.

Low-token gaze integration uses the local `gaze-xiaoke-tool`, which credits and
borrows safety patterns from 栈/江栈's public [jiangxi1129/gaze](https://github.com/jiangxi1129/gaze)
project.
