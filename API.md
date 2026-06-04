# DiscoElysiumBridge API

BepInEx IL2CPP mod，在游戏内运行HTTP服务器，暴露对话状态数据。

## 基本信息

- 地址：`http://localhost:7860`
- 版本：v0.2.0
- 游戏启动后自动运行
- 注意：curl需要 `--noproxy localhost` 或用环境变量 `NO_PROXY=localhost`

## 端点

### GET /health

健康检查。

```json
{"status":"ok","mod":"DiscoElysiumBridge","version":"0.1.1"}
```

### GET /state

获取当前对话状态。核心端点。

**无对话时：**
```json
{
  "conversationActive": false,
  "lastText": "",
  "lastSpeaker": ""
}
```

**对话进行中（有选项）：**
```json
{
  "conversationActive": true,
  "subtitle": {
    "text": "Yes?",
    "textZh": "什么事？",
    "speaker": "Kim Kitsuragi"
  },
  "choices": [
    {"index": 0, "text": "Tell me about the case again.", "textZh": "再跟我说说这个案子。", "enabled": true},
    {"index": 1, "text": "I think I should tell you...", "textZh": "我觉得我应该告诉你...", "enabled": true}
  ],
  "hasContinue": false,
  "lastText": "什么事？",
  "lastSpeaker": "Kim Kitsuragi"
}
```

**对话进行中（只有继续按钮）：**
```json
{
  "conversationActive": true,
  "subtitle": {
    "text": "He nods slowly.",
    "textZh": "他缓缓点头。",
    "speaker": "Kim Kitsuragi"
  },
  "hasContinue": true,
  "lastText": "他缓缓点头。",
  "lastSpeaker": "Kim Kitsuragi"
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| conversationActive | bool | 是否在对话中 |
| subtitle.text | string | 当前文本（英文原文） |
| subtitle.textZh | string | 当前文本（中文翻译，可能为空） |
| subtitle.speaker | string | 说话人名字 |
| choices | array | 玩家可选的对话选项 |
| choices[].index | int | 选项编号（对应键盘数字键 index+1） |
| choices[].text | string | 选项文本（英文） |
| choices[].textZh | string | 选项文本（中文，可能为空） |
| choices[].enabled | bool | 是否可选 |
| hasContinue | bool | 是否显示"继续"按钮（无选项时） |
| lastText | string | 上一次对话文本（对话切换时保持） |
| lastSpeaker | string | 上一次说话人 |

## 操作方式

### GET /choose?index=N

选择对话选项。通过Windows API模拟按键。

- index=0 → 按键1，index=1 → 按键2，...，index=8 → 按键9，index=9 → 按键0
- 支持index 0-9（键盘限制）
- 也可以直接用CoDriver按数字键

```
curl --noproxy localhost "http://localhost:7860/choose?index=2"
→ {"chosen":2,"key":"3"}
```

### GET /continue

继续对话（模拟Enter键）。用于hasContinue=true时。

```
curl --noproxy localhost "http://localhost:7860/continue"
→ {"continued":true}
```

### 旧方式（仍可用）
- 键盘数字键选选项：选项 index=0 对应按键 `1`
- Enter键继续对话

### 移动角色
使用 CoDriver 点击地面（DPI已修复，点击精确）。双击可跑步。

## 游戏启动配置

### DPI修复
游戏注册表设置了 DPIUNAWARE 覆盖，解决125% DPI下点击坐标偏移：
```
HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers
"D:\steam\steamapps\common\Disco Elysium\disco.exe" = "~ DPIUNAWARE"
```

### 文件位置
- mod DLL：`D:\steam\steamapps\common\Disco Elysium\BepInEx\plugins\DiscoElysiumBridge.dll`
- 源码：`F:\2-other-out-of-class\1-AI-CLAUDE\projects\DiscoElysiumBridge\src\`
- 编译：`dotnet-sdk\dotnet.exe build -c Release`（SDK在 `F:\2-other-out-of-class\1-AI-CLAUDE\tools\dotnet-sdk\`）

## 已知问题

- textZh 中文文本有时为空，需要进一步研究 I2 Localization 的翻译时机
- 移动API（SetDestination）需要主线程调用，hook protected方法导致崩溃，暂时搁置
- Speaker名字是英文（CharacterInfo.Name），中文名需要额外查询
