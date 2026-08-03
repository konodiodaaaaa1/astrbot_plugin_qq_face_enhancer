---
name: qq-face
description: 理解、检索并安全发送 OneBot QQ 官方表情
---

# QQ 表情运用增强

模型输入中的标识已经给出具体类别、名称、ID 和消息位置，例如：

```text
[QQ表情:微笑|face_id=14|混合消息]
[QQ超级表情:超级赞|face_id=364|单独发送]
[QQ接龙超级表情:火车|face_id=419|单独发送|接龙起点]
```

理解或选择表情时遵循以下规则：

1. 结合标识前后的完整文字判断社交语气，不能只按官方名称作字面解释。
2. 需要候选或更详细语义时调用 `search_qq_face`，不要凭记忆猜 `face_id`。
3. 发送前确认候选的 `sendable=true`，再调用 `send_qq_face`。
4. 超级表情通常使用 `send_mode=auto`，插件会默认单独发送；只有确实需要同条文字时才显式使用 `mixed`。
5. 骰子和包剪锤是随机结果，不要声称能够预先指定结果。
6. 接龙中段或收尾只在近期同一会话存在同组接龙时使用 `chain_action=continue`；失败后不要绕过校验。
7. `market_face/mface` 目前只支持理解和学习，不能作为普通 `system_face` 发送。

检索结果中的 `social_meanings` 是稳定的基础语义，`learned_observations` 是夜间任务从真实上下文中整理的本地用法。发生冲突时，结合证据数、置信度和当前上下文判断。
