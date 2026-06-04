using System;
using System.IO;
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

    public override void Load()
    {
        Log = base.Log;
        Log.LogInfo("DiscoElysiumBridge loading...");

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

    private const uint KEYEVENTF_KEYDOWN = 0x0000;
    private const uint KEYEVENTF_KEYUP = 0x0002;
    private const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    private const uint MOUSEEVENTF_LEFTUP = 0x0004;
    private const uint MOUSEEVENTF_LEFTDBLCLK = 0x0002 | 0x0004; // not real flag, we simulate

    private static void SimulateKey(byte vk)
    {
        keybd_event(vk, 0, KEYEVENTF_KEYDOWN, UIntPtr.Zero);
        Thread.Sleep(50);
        keybd_event(vk, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
    }

    private string HandleChoose(HttpListenerContext ctx)
    {
        var indexStr = ctx.Request.QueryString["index"];
        if (indexStr == null) return "{\"error\":\"need index param (0-based). Example: /choose?index=0\"}";
        if (!int.TryParse(indexStr, out int index)) return "{\"error\":\"index must be integer\"}";

        // Keys 1-9 map to options 0-8, 0 maps to option 9
        if (index < 0 || index > 9)
            return $"{{\"error\":\"keyboard only supports index 0-9. Use /state to check available choices.\"}}";

        byte vk = index < 9 ? (byte)(0x31 + index) : (byte)0x30; // VK_1..VK_9, VK_0
        SimulateKey(vk);
        return $"{{\"chosen\":{index},\"key\":\"{(index < 9 ? (index + 1).ToString() : "0")}\"}}";
    }

    private string HandleContinue()
    {
        SimulateKey(0x0D); // VK_RETURN
        return "{\"continued\":true}";
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

        return $"{{\"clicked\":true,\"x\":{x},\"y\":{y},\"double\":{(doubleClick ? "true" : "false")}}}";
    }

    private static readonly System.Collections.Generic.Dictionary<string, byte> KeyMap = new()
    {
        {"tab", 0x09}, {"enter", 0x0D}, {"escape", 0x1B}, {"space", 0x20},
        {"f1", 0x70}, {"f2", 0x71}, {"f3", 0x72}, {"f4", 0x73},
        {"f5", 0x74}, {"f6", 0x75}, {"f7", 0x76}, {"f8", 0x77},
        {"f9", 0x78}, {"f10", 0x79}, {"f11", 0x7A}, {"f12", 0x7B},
        {"shift", 0x10}, {"ctrl", 0x11}, {"alt", 0x12},
        {"up", 0x26}, {"down", 0x28}, {"left", 0x25}, {"right", 0x27},
        {"i", 0x49}, {"j", 0x4A}, {"m", 0x4D}, {"t", 0x54},
    };

    private string HandleKey(HttpListenerContext ctx)
    {
        var keyName = ctx.Request.QueryString["name"]?.ToLower();
        var holdStr = ctx.Request.QueryString["hold"];

        if (keyName == null)
            return $"{{\"error\":\"need name param. Example: /key?name=tab  Available: {string.Join(",", KeyMap.Keys)}\"}}";

        if (!KeyMap.TryGetValue(keyName, out byte vk))
            return $"{{\"error\":\"unknown key '{keyName}'. Available: {string.Join(",", KeyMap.Keys)}\"}}";

        if (holdStr != null && int.TryParse(holdStr, out int holdMs) && holdMs > 0)
        {
            keybd_event(vk, 0, KEYEVENTF_KEYDOWN, UIntPtr.Zero);
            Thread.Sleep(Math.Min(holdMs, 5000));
            keybd_event(vk, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
            return $"{{\"key\":\"{keyName}\",\"held\":{holdMs}}}";
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

    private string HandleScreenshot(HttpListenerContext ctx)
    {
        var scaleStr = ctx.Request.QueryString["scale"];
        var format = ctx.Request.QueryString["format"]?.ToLower() ?? "bmp";
        float scale = 1.0f;
        if (scaleStr != null && float.TryParse(scaleStr, System.Globalization.NumberStyles.Float,
            System.Globalization.CultureInfo.InvariantCulture, out float s))
            scale = Math.Clamp(s, 0.1f, 1.0f);

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
