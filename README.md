# QQ表情运用增强

面向 AstrBot + OneBot v11（`aiocqhttp`/NapCat）的 QQ 官方表情理解与发送插件。

插件不会把完整表情表塞入系统提示词。收到表情时只向模型提供紧凑标识；模型需要选择表情时再调用检索工具。夜间任务可以从真实对话上下文中整理现代社交用法，但不会向任何会话主动发送消息。

## 功能

- 内置 296 条 QQ/NapCat `sysface` 规范化快照，可离线识别全部当前系统表情。
- 区分 194 条普通表情、87 条超级表情、3 条随机超级表情和 12 条接龙超级表情。
- 区分表情单独发送与表情加文字/其他消息段的混合发送。
- 从原始 OneBot 事件保留 `resultId`、`chainCount`、`faceType` 和 NapCat `raw` 表情元素。
- 识别 `mface` 商城表情并保留包 ID、表情 ID 和摘要；首次收到时以不可发送记录落盘，供检索和夜间学习使用。为防止错发，1.0.0 暂不发送 `mface`。
- 提供 `search_qq_face` 和 `send_qq_face` 模型工具。
- 骰子和包剪锤使用 NapCat 专用随机消息段，不伪造固定结果。
- 接龙中段/收尾必须匹配近期同一会话的同组接龙状态。
- 支持从本机 NapCat `face_config.json` 校验、比较并原子更新运行目录。
- 夜间后台学习可以新增、更新、废弃或删除本地语境观察，并写入审计日志。

## 兼容性

- AstrBot：`>=4.26,<5`
- 平台适配器：`aiocqhttp`
- 推荐协议端：NapCatQQ
- Python：跟随 AstrBot 运行环境，无额外第三方 Python 依赖

其他 OneBot v11 实现可以使用标准 `face` 的基础识别与发送，但 NapCat 扩展字段、随机超级表情和接龙行为不保证一致。

## 安装

在 AstrBot 管理面板上传发布 ZIP。ZIP 根目录应直接包含：

```text
metadata.yaml
main.py
_conf_schema.json
qqface/
skills/
```

安装后先执行：

```text
/qqface status
/qqface lookup 14
```

内置目录已经可以直接工作。只有希望跟随本机 NapCat 版本更新表情元数据时，才需要配置 `napcat_face_config_path`。

## 配置

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `enable_annotation` | `true` | 把入站表情转换为模型短标识，不修改原消息链 |
| `enable_tools` | `true` | 注册模型检索和发送工具 |
| `allow_send` | `false` | 允许模型发送已校验的官方表情 |
| `napcat_face_config_path` | 空 | 本机 NapCat `face_config.json` 绝对路径 |
| `chain_state_ttl_seconds` | `180` | 接龙状态有效秒数 |
| `external_catalog_path` | 空 | 外部语义目录 JSON 本地路径 |
| `external_catalog_url` | 空 | 仅允许 HTTPS 的外部语义目录地址 |
| `learning_enabled` | `true` | 启用夜间语境学习 |
| `learning_time` | `03:30` | 主机本地时区执行时间 |
| `learning_max_samples` | `100` | 单次处理的新样本上限 |
| `learning_retained_samples` | `5000` | 本地保留的上下文样本行数 |
| `learning_provider_id` | 空 | 留空使用 AstrBot 当前默认 Provider |

生产环境首次启用模型发送时，建议先保持 `allow_send=false` 验证入站标识与检索结果，再开启发送。

## 定位 NapCat 配置

AstrBot 与 NapCat 在同一台 Windows 主机时，先执行：

```text
/qqface napcat find
```

插件只检查常见安装目录和明确的候选路径，不会无边界扫描整个磁盘。找到候选后，将完整绝对路径填入 `napcat_face_config_path`，然后执行：

```text
/qqface sync napcat
```

不同 NapCat 安装方式的路径会不同，常见结构包括：

```text
<NapCat目录>\packages\napcat-core\external\face_config.json
<NapCat目录>\resources\app\napcat\napcat\core\external\face_config.json
```

若插件命令没有找到，可在 PowerShell 中只搜索你实际可能安装 NapCat 的几个目录：

```powershell
$roots = @(
  "$env:ProgramFiles\NapCat",
  "${env:ProgramFiles(x86)}\NapCat",
  "$env:LOCALAPPDATA\Programs\NapCat",
  "$env:USERPROFILE\Desktop\NapCat",
  "$env:USERPROFILE\Downloads\NapCat"
) | Where-Object { Test-Path -LiteralPath $_ }

Get-ChildItem -LiteralPath $roots -Filter face_config.json -File -Recurse `
  -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
```

同步会验证 `sysface` 结构和重复 ID，显示新增、移除及名称/类型变化，并把成功结果原子写入插件数据目录。校验或写入失败时继续使用上一次缓存和内置快照。

## 管理命令

以下命令仅 AstrBot 管理员可用：

```text
/qqface status
/qqface lookup <数字ID>
/qqface reload
/qqface napcat find
/qqface sync napcat
/qqface sync external
/qqface unknown export
```

## 模型看到的内容

示例：

```text
[QQ表情:微笑|face_id=14|混合消息]
[QQ超级表情:超级赞|face_id=364|单独发送]
[QQ随机超级表情:骰子|face_id=358|单独发送|结果=4]
[QQ接龙超级表情:火车|face_id=419|单独发送|接龙起点|接龙次数=1]
[QQ商城表情:摘要|emoji_id=abc|单独发送]
```

原始 AstrBot 消息组件链保持不变，只更新模型使用的 `message_str`。未知 ID 保留原始描述并标为未知，插件不会猜名称。

## 发送规则

- 模型必须先用 `search_qq_face` 获取精确 ID。
- 超级表情在 `send_mode=auto` 下默认单独发送。
- `send_mode=mixed` 必须显式提供同条发送的 `text`。
- 骰子 `358` 和包剪锤 `359` 使用随机段，结果由 QQ 客户端/协议端生成。
- 篮球 `114` 作为随机超级表情按官方 `face` 段发送。
- 接龙起点可以开始新接龙；中段与收尾没有匹配状态时会拒绝发送。
- 商城 `mface` 只理解和学习，不发送。

## 夜间学习与数据

白天插件仅在消息包含 QQ 表情时记录有限上下文，真实会话 ID 会先哈希。夜间任务调用配置的 Provider，对观察执行 `upsert`、`deprecate` 或 `delete`；官方 ID、名称和能力字段不能被学习任务修改。

插件数据由 `StarTools.get_data_dir("astrbot_plugin_qq_face_enhancer")` 获取，典型文件包括：

```text
context_samples.jsonl
learning_state.json
observations.json
learning_audit.jsonl
napcat_catalog.json
observed_market_faces.json
unknown_faces.json
```

上下文文本会发送给夜间学习所用的 Provider。对隐私有更严格要求时，应关闭 `learning_enabled`，或使用符合部署要求的本地 Provider。

## 故障排查

- 报错 `get_data_dir`：确认安装的是 1.0.0 ZIP，`main.py` 应使用 `StarTools.get_data_dir(...)`。
- 目录仍不是 296 条：执行 `/qqface status`，确认没有错误的外部目录覆盖；再执行 `/qqface reload`。
- NapCat 同步失败：确认填写的是文件而不是目录，并确认 JSON 中存在 `sysface` 数组。
- 能检索但不能发送：检查 `allow_send=true`，并确认当前事件平台为 `aiocqhttp`。
- 夜间学习没有记录：需要先在真实会话收到包含 `face`/`mface` 的消息，并配置可用 Provider。
- 超级表情样式与 QQ 客户端不同：先用本机 NapCat 更新目录；不同 QQ/NapCat 版本可能具有不同资源。

## 数据来源与许可证

内置目录是从 NapCatQQ 指定版本提取的规范化子集，不包含原始 `face_config.json`。详情见 `THIRD_PARTY_NOTICES.md` 和 `licenses/NAPCAT-LICENSE.txt`。NapCat 的许可包含非商业使用限制，部署前请自行确认适用范围。
