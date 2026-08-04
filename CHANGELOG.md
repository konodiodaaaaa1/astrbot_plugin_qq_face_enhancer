# Changelog

## 1.2.1 - 2026-08-04

- 附带可选的 NapCat companion plugin，使超级、随机、接龙及扩展 ID 可以绕过标准 OneBot `sysface` 白名单限制。
- 原生发送完整保留 `packId`、`stickerId`、`stickerType`、`randomType`、`resultId` 和 `chainCount`。
- 新增 NapCat 扩展 API 地址、共享 Token 和超时配置，并优化 AstrBot 配置界面的说明、占位提示和条件显示。
- 修正 NapCat WebUI 配置 schema，并确保首次安装时能够创建配置目录和持久化共享 Token。
- 修复私聊原生发送直接将数字 QQ 号作为 QQNT `peerUid` 的问题；现在会先解析内部 UID，避免 `MsgApi.sendMsg` 阻塞超时。

## 1.2.0 - 2026-08-03

- `send_qq_face` 新增可选 `result_id`，显式发送时改走 `face.data.resultId`，支持模型控制随机/超级表情结果字段。
- `send_qq_face` 新增可选 `chain_count`，对接龙表情允许模型直接指定接龙次数并覆盖会话状态。
- 未传显式参数时保持原有 QQ 随机结果和会话接龙自动计算行为。
- 更新 Skill、能力查询和 README，明确参数优先级、默认行为和校验边界。

## 1.1.0 - 2026-08-03

- `search_qq_face` 新增 `kind`、`hidden`、`chain_role` 结构化筛选。
- 检索结果新增隐藏状态、表情/贴纸类型、资源包字段和按类型生成的发送参数说明。
- 新增 `describe_qq_face_capabilities` 工具，可查询当前目录能力摘要或单个 `face_id` 的完整特殊能力。
- Skill 增加隐藏、随机和接龙表情的查询与调用规则，不全量注入易过期的隐藏 ID 表。
- 明确 `resultId`、随机结果和 `chainCount` 的控制边界，模型不能猜测或绕过现有发送校验。

## 1.0.0 - 2026-08-03

- 内置 296 条当前 QQ/NapCat 系统表情规范化目录，附来源版本和第三方许可说明。
- 新增普通、超级、随机超级和接龙超级四类能力字段及完整统计。
- 新增单独发送/混合消息识别，并保留 `resultId`、`chainCount`、`faceType` 与原始扩展字段。
- 新增骰子、包剪锤随机段发送，以及四组显式接龙关系和会话级续接校验。
- 收到的 `mface` 商城表情会以不可发送记录持久化，使其能够参与检索和夜间语境学习。
- 新增 `/qqface lookup`、`/qqface napcat find`、`/qqface sync napcat`，并扩展 `/qqface status`。
- NapCat 本地更新加入 schema 校验、差异摘要、原子缓存和失败回退。
- 检索结果新增表情类别、社交语义、使用风险、单独发送偏好和学习观察。
- 夜间学习支持新增、修改、废弃与删除观察，记录审计日志，并限制样本保留量。
- 修正早期试验目录的错误映射；当前快照中 `22=白眼`、`179=doge（狗头）`、`288=请`。
- 插件数据目录固定使用 `StarTools.get_data_dir("astrbot_plugin_qq_face_enhancer")`。
- 补充生产部署 README、配置说明、Windows NapCat 路径定位方法和故障排查。

## 0.1.1 - 2026-08-03

- 修复插件数据目录 API 和包内相对导入。
- 完成三条试验目录下的接收、检索、发送、外部同步及模拟夜间学习链路。

## 0.1.0 - 2026-08-03

- 初始原型。
