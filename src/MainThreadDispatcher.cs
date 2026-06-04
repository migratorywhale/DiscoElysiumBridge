using System;
using System.Collections.Concurrent;

namespace DiscoElysiumBridge;

public static class MainThreadDispatcher
{
    private static readonly ConcurrentQueue<Action> _queue = new();

    public static void Enqueue(Action action)
    {
        _queue.Enqueue(action);
    }

    public static void ProcessQueue()
    {
        while (_queue.TryDequeue(out var action))
        {
            try { action(); }
            catch (Exception e) { Plugin.Log.LogWarning($"Dispatch error: {e.Message}"); }
        }
    }
}
