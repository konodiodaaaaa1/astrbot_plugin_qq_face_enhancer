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

目录包含四种系统表情能力：

- `normal`：普通表情；
- `super`：动画超级表情；
- `random_super`：结果由 QQ 服务端产生的随机超级表情；
- `chain_super`：具有 `start`、`middle`、`end` 角色的接龙超级表情。

`hidden=true` 只表示该表情在 QQ 客户端入口中隐藏，不表示无法发送。隐藏表情仍必须以动态查询返回的 `sendable` 为准。不要在提示词中维护完整隐藏 ID 表；NapCat 更新后目录可能变化。

理解或选择表情时遵循以下规则：

1. 结合标识前后的完整文字判断社交语气，不能只按官方名称作字面解释。
2. 需要候选或更详细语义时调用 `search_qq_face`，不要凭记忆猜 `face_id`。可使用 `kind`、`hidden` 和 `chain_role` 精确筛选。
3. 发送前确认候选的 `sendable=true`，再调用 `send_qq_face`。
4. 超级表情通常使用 `send_mode=auto`，插件会默认单独发送；只有确实需要同条文字时才显式使用 `mixed`。
5. 骰子和包剪锤默认由 QQ 产生结果；如果语境明确要求指定结果，可将目标结果作为 `result_id` 传给 `send_qq_face`，不要使用 `dice/rps.result` 形式猜测映射。
6. 接龙默认按会话状态续接；如果语境明确要求 Bot 直接控制接龙次数，将正整数作为 `chain_count` 传给 `send_qq_face`，它会覆盖会话状态并允许直接发送中段/收尾。未传 `chain_count` 时仍使用原有状态校验。
7. `result_id` 是可选原始 OneBot 字段，传入后原样透传；`chain_count` 仅对 `chain_super` 生效，必须是正整数。两个参数都不传时保持默认行为。
8. `market_face/mface` 目前只支持理解和学习，不能作为普通 `system_face` 发送。

需要了解特殊分类或参数时调用 `describe_qq_face_capabilities`：

- 不传 `face_id`：查询当前目录的分类、隐藏统计、接龙组和通用发送参数；
- 传精确 `face_id`：查询该表情的 `hidden`、`face_type`、`sticker_type`、资源包、接龙角色及允许的发送参数；
- 查询“隐藏但可发送”的候选：调用 `search_qq_face`，使用 `hidden=hidden`，并检查 `sendable=true`；
- 查询接龙续接：使用 `kind=chain_super` 和 `chain_role=middle|end`，然后使用 `chain_action=continue`。

特殊表情示例（仅用于理解分类，不是完整目录）：

- `423 复兴号`：隐藏超级表情；
- `358 骰子`、`359 包剪锤`：隐藏随机超级表情，默认随机；明确需要控制结果时传 `result_id`；
- `419 火车`：接龙起点；`420 中火车`、`421 大火车`：隐藏接龙中段和收尾；
- `429 蛇年快乐`：接龙起点；`430 蛇身`、`431 蛇尾`：隐藏接龙中段和收尾。

`resultId` 和 `chainCount` 既可以出现在入站事件中，也可以在发送工具中显式指定。默认省略时分别由 QQ 产生或由插件按会话状态计算；只有需要 Bot 主动控制结果/接龙次数时才传入。

检索结果中的 `social_meanings` 是稳定的基础语义，`learned_observations` 是夜间任务从真实上下文中整理的本地用法。发生冲突时，结合证据数、置信度和当前上下文判断。
