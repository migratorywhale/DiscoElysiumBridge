using HarmonyLib;
using PixelCrushers.DialogueSystem;

namespace DiscoElysiumBridge;

public static class DialogueHooks
{
    [HarmonyPostfix]
    [HarmonyPatch(typeof(DialogueSystemController), nameof(DialogueSystemController.OnConversationStart))]
    static void OnConversationStart(DialogueSystemController __instance)
    {
        Plugin.Log.LogInfo($"[Bridge] Conversation started: {DialogueManager.lastConversationStarted}");
    }

    [HarmonyPostfix]
    [HarmonyPatch(typeof(DialogueSystemController), nameof(DialogueSystemController.OnConversationEnd))]
    static void OnConversationEnd(DialogueSystemController __instance)
    {
        Plugin.Log.LogInfo("[Bridge] Conversation ended");
        GameState.LastSubtitleText = "";
        GameState.LastSpeaker = "";
    }
}
