using System;
using System.Text;
using System.Globalization;
using PixelCrushers.DialogueSystem;
using UnityEngine;

namespace DiscoElysiumBridge;

public static class GameState
{
    public static string LastSubtitleText { get; set; } = "";
    public static string LastSpeaker { get; set; } = "";



    public static string GetDialogueStateJson()
    {
        var sb = new StringBuilder();
        sb.Append('{');

        bool active = false;
        try { active = DialogueManager.isConversationActive; } catch { }

        sb.Append($"\"conversationActive\":{(active ? "true" : "false")}");

        if (active)
        {
            try
            {
                var state = DialogueManager.currentConversationState;
                if (state != null)
                {
                    // Current subtitle (NPC/skill text)
                    if (state.subtitle != null)
                    {
                        var text = "";
                        var textZh = "";
                        try
                        {
                            text = state.subtitle.dialogueEntry?.subtitleText
                                ?? state.subtitle.formattedText?.text ?? "";
                            textZh = state.subtitle.dialogueEntry?.currentLocalizedDialogueText
                                ?? state.subtitle.dialogueEntry?.currentDialogueText ?? "";
                        }
                        catch { text = state.subtitle.formattedText?.text ?? ""; }
                        var speaker = state.subtitle.speakerInfo?.Name ?? "";
                        sb.Append($",\"subtitle\":{{\"text\":\"{Plugin.EscapeJson(text)}\",\"textZh\":\"{Plugin.EscapeJson(textZh)}\",\"speaker\":\"{Plugin.EscapeJson(speaker)}\"}}");
                        LastSubtitleText = textZh.Length > 0 ? textZh : text;
                        LastSpeaker = speaker;
                    }

                    // Player choices
                    if (state.pcResponses != null && state.pcResponses.Length > 0)
                    {
                        sb.Append(",\"choices\":[");
                        for (int i = 0; i < state.pcResponses.Length; i++)
                        {
                            var resp = state.pcResponses[i];
                            if (i > 0) sb.Append(',');
                            var choiceText = "";
                            var choiceTextZh = "";
                            try
                            {
                                choiceText = resp?.destinationEntry?.subtitleText
                                    ?? resp?.destinationEntry?.currentMenuText
                                    ?? resp?.formattedText?.text ?? "";
                                choiceTextZh = resp?.destinationEntry?.currentLocalizedMenuText
                                    ?? resp?.destinationEntry?.currentLocalizedDialogueText ?? "";
                            }
                            catch { choiceText = resp?.formattedText?.text ?? ""; }
                            var enabled = resp?.enabled ?? false;
                            sb.Append($"{{\"index\":{i},\"text\":\"{Plugin.EscapeJson(choiceText)}\",\"textZh\":\"{Plugin.EscapeJson(choiceTextZh)}\",\"enabled\":{(enabled ? "true" : "false")}}}");
                        }
                        sb.Append(']');
                    }

                    // Has continue button (NPC response, no player choices)
                    bool hasContinue = state.hasNPCResponse && !state.hasPCResponses;
                    sb.Append($",\"hasContinue\":{(hasContinue ? "true" : "false")}");
                }
            }
            catch (Exception e)
            {
                sb.Append($",\"stateError\":\"{Plugin.EscapeJson(e.Message)}\"");
            }
        }

        // Last known text (even when conversation panel is transitioning)
        sb.Append($",\"lastText\":\"{Plugin.EscapeJson(LastSubtitleText)}\"");
        sb.Append($",\"lastSpeaker\":\"{Plugin.EscapeJson(LastSpeaker)}\"");

        sb.Append('}');
        return sb.ToString();
    }
}
