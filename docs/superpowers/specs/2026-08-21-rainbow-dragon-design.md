# 2024 七彩祥龙端到端调用设计

## 目标

把已经在 QQ 手机端验证成功的 2024 七彩祥龙完整动画做成 QQ 表情目录中的可检索、可发送能力。它与其他隐藏表情使用相同的 AstrBot 工具入口，同时支持私聊和群聊。

验收状态为：接收端使用 `ChainAniStickerMsgItem` 播放 `surprise/100.json` 的竖向动画，主体资源为 `resultId=1`，不出现普通龙或横向压扁状态。

## 协议常量

该效果属于官方表情 `face_id=394`、`pack_id=1`、`sticker_id=40`。NapCat companion 发送以下固定字段：

- `faceId=394`
- `stickerType=4294967299`，Android `int32` 解析结果为 `3`
- `resultId="1"`
- `surpriseId="100"`
- `faceText="/新年大龙"`

特殊编码只由 companion 内部生成。AstrBot 请求不接收原始包、偏移或任意 protobuf 字段。

## NapCat Companion

新增 `POST /send-special`，请求结构：

```json
{
  "effect": "rainbow_dragon_2024",
  "peer": {"type": "private", "id": "2452585759"}
}
```

`peer.type` 支持 `private` 和 `group`。私聊把 QQ 号解析为 UID；群聊直接使用群号。接口动态编码 `MessageSvc.PbSendMsg`，每次生成新的消息序号、随机数和当前同步时间，发送后解析 QQ 回包并返回结果码、服务端序号与时间。

接口沿用 companion 的共享 token 校验。`effect` 采用固定枚举，避免开放通用原始发包能力。

## AstrBot 集成

在 `face_id=394` 的目录记录中加入“七彩祥龙”“完整七彩龙”“2024 龙年隐藏彩蛋”等检索词，并声明特殊变体 `rainbow_dragon_2024`。

现有 `send_qq_face` 增加可选 `variant` 参数。模型从 `search_qq_face` 返回的发送参数中取得该值，并按现有工具流程调用：

```text
send_qq_face(face_id="394", variant="rainbow_dragon_2024")
```

发送器根据当前事件自动选择私聊或群聊目标并调用 `/send-special`。该变体需要 companion；请求失败时返回明确错误，避免静默发送成普通龙或扁龙。其他隐藏表情与普通 `face_id=394` 的行为保持不变。

## 返回与错误

成功结果包含效果名、目标类型、QQ 回包序号和发送完成状态。AstrBot 工具返回简短确认，并设置现有 `qqface.tool_sent` 标记。

无效目标、未知效果、token 错误、QQ 回包错误和超时分别返回可诊断错误。日志不记录共享 token 或完整请求包。

## 测试与发布

测试范围保持紧凑：

- companion 的 protobuf 常量与溢出 `stickerType` 编码；
- 私聊 UID 路由和群聊群号路由；
- AstrBot 检索结果、特殊变体请求和失败时不回退；
- 当前管理员私聊执行一次端到端验收。

不做批量概率抽取或重复视觉试验。发布时更新 AstrBot 插件、内置 companion、README、CHANGELOG 与版本号，部署当前运行实例，完成一次验收后提交并推送仓库。
