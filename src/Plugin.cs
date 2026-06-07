using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Globalization;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using BepInEx;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;
using PixelCrushers.DialogueSystem;
using UnityEngine;

namespace DiscoElysiumBridge;

[BepInPlugin("chen.DiscoElysiumBridge", "Disco Elysium Bridge", "0.1.0")]
public class Plugin : BasePlugin
{
    internal static new ManualLogSource Log;
    private HttpListener _listener;
    private Thread _serverThread;
    private static bool IsMac => RuntimeInformation.IsOSPlatform(OSPlatform.OSX);

    public override void Load()
    {
        Log = base.Log;
        Log.LogInfo("DiscoElysiumBridge loading...");

        if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
        {
            Log.LogInfo("Skipping Harmony dialogue patches on macOS; state endpoint will read DialogueManager directly");
        }
        else
        {
            try
            {
                var harmony = new Harmony("chen.DiscoElysiumBridge");
                harmony.PatchAll(typeof(DialogueHooks));
                Log.LogInfo("Harmony patches applied");
            }
            catch (Exception e)
            {
                Log.LogError($"Failed to apply Harmony patches: {e}");
            }
        }

        StartHttpServer();
        Log.LogInfo("DiscoElysiumBridge loaded!");
    }

    private void StartHttpServer()
    {
        try
        {
            _listener = new HttpListener();
            _listener.Prefixes.Add("http://localhost:7860/");
            _listener.Start();

            _serverThread = new Thread(ServerLoop) { IsBackground = true };
            _serverThread.Start();
            Log.LogInfo("HTTP server started on http://localhost:7860/");
        }
        catch (Exception e)
        {
            Log.LogError($"Failed to start HTTP server: {e}");
        }
    }

    private void ServerLoop()
    {
        while (_listener?.IsListening == true)
        {
            try
            {
                var ctx = _listener.GetContext();
                HandleRequest(ctx);
            }
            catch (Exception e)
            {
                if (_listener?.IsListening == true)
                    Log.LogWarning($"HTTP error: {e.Message}");
            }
        }
    }

    private void HandleRequest(HttpListenerContext ctx)
    {
        var path = ctx.Request.Url?.AbsolutePath ?? "/";
        string json;

        try
        {
            json = path switch
            {
                "/state" => GameState.GetDialogueStateJson(),
                "/choose" => HandleChoose(ctx),
                "/continue" => HandleContinue(),
                "/click" => HandleClick(ctx),
                "/key" => HandleKey(ctx),
                "/screenshot" => HandleScreenshot(ctx),
                "/health" => "{\"status\":\"ok\",\"mod\":\"DiscoElysiumBridge\",\"version\":\"0.5.0\"}",
                _ => "{\"error\":\"unknown endpoint\",\"endpoints\":[\"/state\",\"/choose\",\"/continue\",\"/click\",\"/key\",\"/screenshot\",\"/health\"]}"
            };
        }
        catch (Exception e)
        {
            json = $"{{\"error\":\"{EscapeJson(e.Message)}\"}}";
        }

        var buf = Encoding.UTF8.GetBytes(json);
        ctx.Response.ContentType = "application/json";
        ctx.Response.ContentLength64 = buf.Length;
        ctx.Response.AddHeader("Access-Control-Allow-Origin", "*");
        ctx.Response.OutputStream.Write(buf, 0, buf.Length);
        ctx.Response.Close();
    }

    [DllImport("user32.dll")]
    private static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);

    [DllImport("user32.dll")]
    private static extern bool SetCursorPos(int X, int Y);

    [DllImport("user32.dll")]
    private static extern void mouse_event(uint dwFlags, int dx, int dy, uint dwData, UIntPtr dwExtraInfo);

    private const string ApplicationServices =
        "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices";
    private const string CoreFoundation =
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation";

    [StructLayout(LayoutKind.Sequential)]
    private struct CGPoint
    {
        public double X;
        public double Y;

        public CGPoint(double x, double y)
        {
            X = x;
            Y = y;
        }
    }

    [DllImport(ApplicationServices)]
    private static extern IntPtr CGEventCreateKeyboardEvent(IntPtr source, ushort virtualKey, bool keyDown);

    [DllImport(ApplicationServices)]
    private static extern IntPtr CGEventCreateMouseEvent(IntPtr source, uint mouseType, CGPoint mouseCursorPosition, int mouseButton);

    [DllImport(ApplicationServices)]
    private static extern void CGEventSetIntegerValueField(IntPtr eventRef, int field, long value);

    [DllImport(ApplicationServices)]
    private static extern void CGEventPost(uint tap, IntPtr eventRef);

    [DllImport(CoreFoundation)]
    private static extern void CFRelease(IntPtr cf);

    private const uint KEYEVENTF_KEYDOWN = 0x0000;
    private const uint KEYEVENTF_KEYUP = 0x0002;
    private const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    private const uint MOUSEEVENTF_LEFTUP = 0x0004;
    private const uint MOUSEEVENTF_LEFTDBLCLK = 0x0002 | 0x0004; // not real flag, we simulate
    private const uint KCGHIDEventTap = 0;
    private const uint KCGEventLeftMouseDown = 1;
    private const uint KCGEventLeftMouseUp = 2;
    private const int KCGMouseButtonLeft = 0;
    private const int KCGMouseEventClickState = 1;

    private static void SimulateKey(byte vk)
    {
        keybd_event(vk, 0, KEYEVENTF_KEYDOWN, UIntPtr.Zero);
        Thread.Sleep(50);
        keybd_event(vk, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
    }

    private static void ActivateMacGame()
    {
        try
        {
            string frontmostScript = "tell application \"System Events\" to set frontmost of first application process whose bundle identifier is \"com.zaumstudio.discoelysium\" to true";
            if (!RunProcess("/usr/bin/osascript", new[] { "-e", frontmostScript }, 1500, out _, out var frontmostError))
            {
                string activateScript = "tell application id \"com.zaumstudio.discoelysium\" to activate";
                if (!RunProcess("/usr/bin/osascript", new[] { "-e", activateScript }, 1500, out _, out var activateError))
                    Log?.LogWarning($"Could not activate Disco Elysium before macOS input: {frontmostError}; fallback: {activateError}");
            }
            Thread.Sleep(120);
        }
        catch (Exception e)
        {
            Log?.LogWarning($"Could not activate Disco Elysium before macOS input: {e.Message}");
        }
    }

    private static void ReleaseIfNeeded(IntPtr handle)
    {
        if (handle != IntPtr.Zero)
            CFRelease(handle);
    }

    private static void PostMacKey(ushort keyCode, int holdMs = 0)
    {
        ActivateMacGame();
        IntPtr down = IntPtr.Zero;
        IntPtr up = IntPtr.Zero;
        try
        {
            down = CGEventCreateKeyboardEvent(IntPtr.Zero, keyCode, true);
            up = CGEventCreateKeyboardEvent(IntPtr.Zero, keyCode, false);
            if (down == IntPtr.Zero || up == IntPtr.Zero)
                throw new InvalidOperationException("CGEventCreateKeyboardEvent returned null");

            CGEventPost(KCGHIDEventTap, down);
            Thread.Sleep(holdMs > 0 ? Math.Min(holdMs, 5000) : 50);
            CGEventPost(KCGHIDEventTap, up);
        }
        finally
        {
            ReleaseIfNeeded(down);
            ReleaseIfNeeded(up);
        }
    }

    private static void PostMacClick(int x, int y, bool doubleClick)
    {
        ActivateMacGame();
        var point = new CGPoint(x, y);
        int clicks = doubleClick ? 2 : 1;

        for (int i = 0; i < clicks; i++)
        {
            IntPtr down = IntPtr.Zero;
            IntPtr up = IntPtr.Zero;
            try
            {
                down = CGEventCreateMouseEvent(IntPtr.Zero, KCGEventLeftMouseDown, point, KCGMouseButtonLeft);
                up = CGEventCreateMouseEvent(IntPtr.Zero, KCGEventLeftMouseUp, point, KCGMouseButtonLeft);
                if (down == IntPtr.Zero || up == IntPtr.Zero)
                    throw new InvalidOperationException("CGEventCreateMouseEvent returned null");

                CGEventSetIntegerValueField(down, KCGMouseEventClickState, i + 1);
                CGEventSetIntegerValueField(up, KCGMouseEventClickState, i + 1);
                CGEventPost(KCGHIDEventTap, down);
                Thread.Sleep(30);
                CGEventPost(KCGHIDEventTap, up);
                Thread.Sleep(80);
            }
            finally
            {
                ReleaseIfNeeded(down);
                ReleaseIfNeeded(up);
            }
        }
    }

    private string HandleChoose(HttpListenerContext ctx)
    {
        var indexStr = ctx.Request.QueryString["index"];
        if (indexStr == null) return "{\"error\":\"need index param (0-based). Example: /choose?index=0\"}";
        if (!int.TryParse(indexStr, out int index)) return "{\"error\":\"index must be integer\"}";

        // Keys 1-9 map to options 0-8, 0 maps to option 9
        if (index < 0 || index > 9)
            return $"{{\"error\":\"keyboard only supports index 0-9. Use /state to check available choices.\"}}";

        string key = index < 9 ? (index + 1).ToString() : "0";
        if (IsMac)
        {
            PostMacKey(MacKeyMap[key]);
        }
        else
        {
            byte vk = index < 9 ? (byte)(0x31 + index) : (byte)0x30; // VK_1..VK_9, VK_0
            SimulateKey(vk);
        }
        return $"{{\"chosen\":{index},\"key\":\"{key}\",\"platform\":\"{(IsMac ? "macos" : "windows")}\"}}";
    }

    private string HandleContinue()
    {
        if (IsMac)
            PostMacKey(MacKeyMap["enter"]);
        else
            SimulateKey(0x0D); // VK_RETURN
        return $"{{\"continued\":true,\"platform\":\"{(IsMac ? "macos" : "windows")}\"}}";
    }

    private string HandleClick(HttpListenerContext ctx)
    {
        var xStr = ctx.Request.QueryString["x"];
        var yStr = ctx.Request.QueryString["y"];
        var dblStr = ctx.Request.QueryString["double"];

        if (xStr == null || yStr == null)
            return "{\"error\":\"need x and y params. Example: /click?x=500&y=300 or /click?x=500&y=300&double=1\"}";
        if (!int.TryParse(xStr, out int x) || !int.TryParse(yStr, out int y))
            return "{\"error\":\"x and y must be integers\"}";

        bool doubleClick = dblStr == "1" || dblStr == "true";

        if (IsMac)
        {
            PostMacClick(x, y, doubleClick);
        }
        else
        {
            SetCursorPos(x, y);
            Thread.Sleep(30);
            mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
            Thread.Sleep(30);
            mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);

            if (doubleClick)
            {
                Thread.Sleep(80);
                mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
                Thread.Sleep(30);
                mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
            }
        }

        return $"{{\"clicked\":true,\"x\":{x},\"y\":{y},\"double\":{(doubleClick ? "true" : "false")},\"platform\":\"{(IsMac ? "macos" : "windows")}\"}}";
    }

    private static readonly Dictionary<string, byte> KeyMap = new()
    {
        {"tab", 0x09}, {"enter", 0x0D}, {"escape", 0x1B}, {"space", 0x20},
        {"f1", 0x70}, {"f2", 0x71}, {"f3", 0x72}, {"f4", 0x73},
        {"f5", 0x74}, {"f6", 0x75}, {"f7", 0x76}, {"f8", 0x77},
        {"f9", 0x78}, {"f10", 0x79}, {"f11", 0x7A}, {"f12", 0x7B},
        {"shift", 0x10}, {"ctrl", 0x11}, {"alt", 0x12},
        {"up", 0x26}, {"down", 0x28}, {"left", 0x25}, {"right", 0x27},
        {"i", 0x49}, {"j", 0x4A}, {"m", 0x4D}, {"t", 0x54},
    };

    private static readonly Dictionary<string, ushort> MacKeyMap = new()
    {
        {"a", 0}, {"s", 1}, {"d", 2}, {"f", 3}, {"h", 4}, {"g", 5},
        {"z", 6}, {"x", 7}, {"c", 8}, {"v", 9}, {"b", 11},
        {"q", 12}, {"w", 13}, {"e", 14}, {"r", 15}, {"y", 16}, {"t", 17},
        {"1", 18}, {"2", 19}, {"3", 20}, {"4", 21}, {"6", 22}, {"5", 23},
        {"=", 24}, {"9", 25}, {"7", 26}, {"-", 27}, {"8", 28}, {"0", 29},
        {"o", 31}, {"u", 32}, {"i", 34}, {"p", 35},
        {"enter", 36}, {"return", 36}, {"l", 37}, {"j", 38}, {"k", 40},
        {"n", 45}, {"m", 46}, {"tab", 48}, {"space", 49},
        {"escape", 53}, {"esc", 53},
        {"command", 55}, {"cmd", 55}, {"shift", 56}, {"alt", 58}, {"option", 58}, {"ctrl", 59},
        {"left", 123}, {"right", 124}, {"down", 125}, {"up", 126},
        {"f1", 122}, {"f2", 120}, {"f3", 99}, {"f4", 118},
        {"f5", 96}, {"f6", 97}, {"f7", 98}, {"f8", 100},
        {"f9", 101}, {"f10", 109}, {"f11", 103}, {"f12", 111},
    };

    private string HandleKey(HttpListenerContext ctx)
    {
        var keyName = ctx.Request.QueryString["name"]?.ToLower();
        var holdStr = ctx.Request.QueryString["hold"];

        if (keyName == null)
            return $"{{\"error\":\"need name param. Example: /key?name=tab  Available: {string.Join(",", KeyMap.Keys)}\"}}";

        if (IsMac)
        {
            if (!MacKeyMap.TryGetValue(keyName, out ushort macCode))
                return $"{{\"error\":\"unknown key '{keyName}'. Available: {string.Join(",", MacKeyMap.Keys)}\"}}";

            int holdMs = 0;
            if (holdStr != null && int.TryParse(holdStr, out int parsedHold) && parsedHold > 0)
                holdMs = Math.Min(parsedHold, 5000);

            PostMacKey(macCode, holdMs);
            return holdMs > 0
                ? $"{{\"key\":\"{keyName}\",\"held\":{holdMs},\"platform\":\"macos\"}}"
                : $"{{\"key\":\"{keyName}\",\"pressed\":true,\"platform\":\"macos\"}}";
        }

        if (!KeyMap.TryGetValue(keyName, out byte vk))
            return $"{{\"error\":\"unknown key '{keyName}'. Available: {string.Join(",", KeyMap.Keys)}\"}}";

        if (holdStr != null && int.TryParse(holdStr, out int windowsHoldMs) && windowsHoldMs > 0)
        {
            keybd_event(vk, 0, KEYEVENTF_KEYDOWN, UIntPtr.Zero);
            Thread.Sleep(Math.Min(windowsHoldMs, 5000));
            keybd_event(vk, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
            return $"{{\"key\":\"{keyName}\",\"held\":{windowsHoldMs}}}";
        }

        SimulateKey(vk);
        return $"{{\"key\":\"{keyName}\",\"pressed\":true}}";
    }

    [DllImport("user32.dll")]
    private static extern IntPtr GetDesktopWindow();
    [DllImport("user32.dll")]
    private static extern IntPtr GetWindowDC(IntPtr hWnd);
    [DllImport("user32.dll")]
    private static extern int ReleaseDC(IntPtr hWnd, IntPtr hDC);
    [DllImport("user32.dll")]
    private static extern int GetSystemMetrics(int nIndex);
    [DllImport("gdi32.dll")]
    private static extern IntPtr CreateCompatibleDC(IntPtr hdc);
    [DllImport("gdi32.dll")]
    private static extern IntPtr CreateCompatibleBitmap(IntPtr hdc, int width, int height);
    [DllImport("gdi32.dll")]
    private static extern IntPtr SelectObject(IntPtr hdc, IntPtr hgdiobj);
    [DllImport("gdi32.dll")]
    private static extern bool BitBlt(IntPtr hdcDest, int xDest, int yDest, int width, int height, IntPtr hdcSrc, int xSrc, int ySrc, uint rop);
    [DllImport("gdi32.dll")]
    private static extern int StretchDIBits(IntPtr hdc, int xDest, int yDest, int wDest, int hDest, int xSrc, int ySrc, int wSrc, int hSrc, byte[] bits, ref BITMAPINFO bmi, uint usage, uint rop);
    [DllImport("gdi32.dll")]
    private static extern bool DeleteObject(IntPtr hObject);
    [DllImport("gdi32.dll")]
    private static extern bool DeleteDC(IntPtr hdc);
    [DllImport("gdi32.dll")]
    private static extern int GetDIBits(IntPtr hdc, IntPtr hbmp, uint start, uint lines, byte[] bits, ref BITMAPINFO bmi, uint usage);

    // GDI+ for JPEG encoding
    [DllImport("gdiplus.dll")]
    private static extern int GdiplusStartup(out IntPtr token, ref GdiplusStartupInput input, IntPtr output);
    [DllImport("gdiplus.dll")]
    private static extern int GdiplusShutdown(IntPtr token);
    [DllImport("gdiplus.dll")]
    private static extern int GdipCreateBitmapFromScan0(int width, int height, int stride, int format, IntPtr scan0, out IntPtr bitmap);
    [DllImport("gdiplus.dll")]
    private static extern int GdipBitmapSetPixel(IntPtr bitmap, int x, int y, uint color);
    [DllImport("gdiplus.dll")]
    private static extern int GdipSaveImageToStream(IntPtr image, IntPtr stream, ref Guid clsid, IntPtr encoderParams);
    [DllImport("gdiplus.dll")]
    private static extern int GdipDisposeImage(IntPtr image);
    [DllImport("gdiplus.dll")]
    private static extern int GdipCreateBitmapFromHBITMAP(IntPtr hbm, IntPtr hpal, out IntPtr bitmap);
    [DllImport("ole32.dll")]
    private static extern int CreateStreamOnHGlobal(IntPtr hGlobal, bool fDeleteOnRelease, out IntPtr ppstm);
    [DllImport("ole32.dll")]
    private static extern IntPtr GlobalAlloc(uint uFlags, UIntPtr dwBytes);

    [StructLayout(LayoutKind.Sequential)]
    private struct GdiplusStartupInput
    {
        public int GdiplusVersion;
        public IntPtr DebugEventCallback;
        public bool SuppressBackgroundThread;
        public bool SuppressExternalCodecs;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct BITMAPINFOHEADER
    {
        public uint biSize; public int biWidth; public int biHeight;
        public ushort biPlanes; public ushort biBitCount; public uint biCompression;
        public uint biSizeImage; public int biXPelsPerMeter; public int biYPelsPerMeter;
        public uint biClrUsed; public uint biClrImportant;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct BITMAPINFO { public BITMAPINFOHEADER bmiHeader; }

    private static bool RunProcess(string executable, IEnumerable<string> args, int timeoutMs, out string stdout, out string stderr)
    {
        var psi = new ProcessStartInfo(executable)
        {
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var arg in args)
            psi.ArgumentList.Add(arg);

        using var process = Process.Start(psi);
        if (process == null)
        {
            stdout = "";
            stderr = "Process.Start returned null";
            return false;
        }

        if (!process.WaitForExit(timeoutMs))
        {
            try { process.Kill(entireProcessTree: true); } catch { }
            stdout = "";
            stderr = $"Timed out after {timeoutMs}ms";
            return false;
        }

        stdout = process.StandardOutput.ReadToEnd();
        stderr = process.StandardError.ReadToEnd();
        return process.ExitCode == 0;
    }

    private static (int Width, int Height) ReadMacImageDimensions(string path)
    {
        if (!RunProcess("/usr/bin/sips", new[] { "-g", "pixelWidth", "-g", "pixelHeight", path }, 3000, out var stdout, out _))
            return (0, 0);

        int width = 0;
        int height = 0;
        foreach (var rawLine in stdout.Split('\n'))
        {
            var line = rawLine.Trim();
            if (line.StartsWith("pixelWidth:", StringComparison.Ordinal)
                && int.TryParse(line["pixelWidth:".Length..].Trim(), out var parsedWidth))
                width = parsedWidth;
            else if (line.StartsWith("pixelHeight:", StringComparison.Ordinal)
                && int.TryParse(line["pixelHeight:".Length..].Trim(), out var parsedHeight))
                height = parsedHeight;
        }
        return (width, height);
    }

    private static string HandleMacScreenshot(float scale)
    {
        string rawPath = Path.Combine(Path.GetTempPath(), $"disco-bridge-{Guid.NewGuid():N}.jpg");
        string scaledPath = Path.Combine(Path.GetTempPath(), $"disco-bridge-{Guid.NewGuid():N}-scaled.jpg");
        string readPath = rawPath;

        try
        {
            ActivateMacGame();
            if (!RunProcess("/usr/sbin/screencapture", new[] { "-x", "-t", "jpg", rawPath }, 8000, out _, out var captureError))
                return $"{{\"error\":\"screencapture failed: {EscapeJson(captureError)}\"}}";

            var (width, height) = ReadMacImageDimensions(rawPath);
            bool scaled = false;

            if (scale < 0.99f && width > 0 && height > 0)
            {
                int maxDimension = Math.Max(1, (int)(Math.Max(width, height) * scale));
                if (RunProcess("/usr/bin/sips", new[] { "-Z", maxDimension.ToString(CultureInfo.InvariantCulture), rawPath, "--out", scaledPath }, 8000, out _, out _)
                    && File.Exists(scaledPath))
                {
                    readPath = scaledPath;
                    scaled = true;
                    (width, height) = ReadMacImageDimensions(scaledPath);
                }
            }

            var imageBytes = File.ReadAllBytes(readPath);
            string base64 = Convert.ToBase64String(imageBytes);
            return $"{{\"screenshot\":true,\"format\":\"jpeg\",\"width\":{width},\"height\":{height},\"size\":{imageBytes.Length},\"scale\":{scale.ToString(CultureInfo.InvariantCulture)},\"scaled\":{(scaled ? "true" : "false")},\"source\":\"macos-screencapture\",\"data\":\"{base64}\"}}";
        }
        finally
        {
            try { File.Delete(rawPath); } catch { }
            try { File.Delete(scaledPath); } catch { }
        }
    }

    private string HandleScreenshot(HttpListenerContext ctx)
    {
        var scaleStr = ctx.Request.QueryString["scale"];
        var format = ctx.Request.QueryString["format"]?.ToLower() ?? "bmp";
        float scale = 1.0f;
        if (scaleStr != null && float.TryParse(scaleStr, System.Globalization.NumberStyles.Float,
            System.Globalization.CultureInfo.InvariantCulture, out float s))
            scale = Math.Clamp(s, 0.1f, 1.0f);

        if (IsMac)
            return HandleMacScreenshot(scale);

        try
        {
            int srcW = GetSystemMetrics(0);
            int srcH = GetSystemMetrics(1);
            int outW = (int)(srcW * scale);
            int outH = (int)(srcH * scale);

            IntPtr desktop = GetDesktopWindow();
            IntPtr srcDC = GetWindowDC(desktop);
            IntPtr memDC = CreateCompatibleDC(srcDC);
            IntPtr hBmp = CreateCompatibleBitmap(srcDC, outW, outH);
            IntPtr old = SelectObject(memDC, hBmp);

            if (scale < 1.0f)
            {
                // StretchBlt for scaling
                SetStretchBltMode(memDC, 3); // COLORONCOLOR
                StretchBlt(memDC, 0, 0, outW, outH, srcDC, 0, 0, srcW, srcH, 0x00CC0020);
            }
            else
            {
                BitBlt(memDC, 0, 0, outW, outH, srcDC, 0, 0, 0x00CC0020);
            }

            var bmi = new BITMAPINFO();
            bmi.bmiHeader.biSize = (uint)Marshal.SizeOf(typeof(BITMAPINFOHEADER));
            bmi.bmiHeader.biWidth = outW;
            bmi.bmiHeader.biHeight = -outH;
            bmi.bmiHeader.biPlanes = 1;
            bmi.bmiHeader.biBitCount = 32;
            byte[] pixels = new byte[outW * outH * 4];
            GetDIBits(memDC, hBmp, 0, (uint)outH, pixels, ref bmi, 0);

            byte[] imageBytes;
            string actualFormat;

            if (format == "jpeg" || format == "jpg")
            {
                imageBytes = EncodeJpeg(hBmp);
                actualFormat = "jpeg";
            }
            else
            {
                imageBytes = EncodeBmp(pixels, outW, outH);
                actualFormat = "bmp";
            }

            SelectObject(memDC, old);
            DeleteObject(hBmp);
            DeleteDC(memDC);
            ReleaseDC(desktop, srcDC);

            string base64 = Convert.ToBase64String(imageBytes);
            return $"{{\"screenshot\":true,\"format\":\"{actualFormat}\",\"width\":{outW},\"height\":{outH},\"size\":{imageBytes.Length},\"data\":\"{base64}\"}}";
        }
        catch (Exception e)
        {
            return $"{{\"error\":\"{EscapeJson(e.Message)}\"}}";
        }
    }

    [DllImport("gdi32.dll")]
    private static extern bool StretchBlt(IntPtr hdcDest, int xDest, int yDest, int wDest, int hDest, IntPtr hdcSrc, int xSrc, int ySrc, int wSrc, int hSrc, uint rop);
    [DllImport("gdi32.dll")]
    private static extern int SetStretchBltMode(IntPtr hdc, int mode);

    private static byte[] EncodeBmp(byte[] pixels, int w, int h)
    {
        using var ms = new MemoryStream();
        using (var bw = new BinaryWriter(ms, Encoding.Default, true))
        {
            int rowSize = w * 3;
            int padding = (4 - rowSize % 4) % 4;
            int dataSize = (rowSize + padding) * h;
            bw.Write((ushort)0x4D42);
            bw.Write(54 + dataSize);
            bw.Write(0);
            bw.Write(54);
            bw.Write(40);
            bw.Write(w); bw.Write(h);
            bw.Write((ushort)1); bw.Write((ushort)24);
            bw.Write(0); bw.Write(dataSize);
            bw.Write(0); bw.Write(0); bw.Write(0); bw.Write(0);
            byte[] pad = new byte[padding];
            for (int y = h - 1; y >= 0; y--)
            {
                for (int x = 0; x < w; x++)
                {
                    int i = (y * w + x) * 4;
                    bw.Write(pixels[i]);
                    bw.Write(pixels[i + 1]);
                    bw.Write(pixels[i + 2]);
                }
                if (padding > 0) bw.Write(pad);
            }
        }
        return ms.ToArray();
    }

    private static byte[] EncodeJpeg(IntPtr hBitmap)
    {
        var input = new GdiplusStartupInput { GdiplusVersion = 1 };
        GdiplusStartup(out IntPtr gdipToken, ref input, IntPtr.Zero);
        try
        {
            GdipCreateBitmapFromHBITMAP(hBitmap, IntPtr.Zero, out IntPtr gpBitmap);
            CreateStreamOnHGlobal(IntPtr.Zero, true, out IntPtr stream);
            var jpegClsid = new Guid("557cf401-1a04-11d3-9a73-0000f81ef32e");
            GdipSaveImageToStream(gpBitmap, stream, ref jpegClsid, IntPtr.Zero);
            GdipDisposeImage(gpBitmap);

            // Read IStream into byte[]
            var statStg = new System.Runtime.InteropServices.ComTypes.STATSTG();
            var iStream = (System.Runtime.InteropServices.ComTypes.IStream)Marshal.GetObjectForIUnknown(stream);
            iStream.Stat(out statStg, 0);
            int size = (int)statStg.cbSize;
            byte[] buf = new byte[size];
            iStream.Seek(0, 0, IntPtr.Zero);
            iStream.Read(buf, size, IntPtr.Zero);
            Marshal.Release(stream);
            return buf;
        }
        finally
        {
            GdiplusShutdown(gdipToken);
        }
    }

    internal static string EscapeJson(string s) =>
        s?.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "") ?? "";
}
