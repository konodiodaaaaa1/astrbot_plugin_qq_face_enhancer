from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.star.star_tools import StarTools

from .qqface.catalog import (
    FACE_KINDS,
    FaceCatalog,
    FaceRecord,
    find_napcat_face_configs,
)
from .qqface.chain import ChainStateTracker
from .qqface.learning import LearningWorker
from .qqface.parser import annotate_event
from .qqface.sender import send_face

PLUGIN_NAME = "astrbot_plugin_qq_face_enhancer"
PLUGIN_VERSION = "1.2.0"
VALID_KINDS = set(FACE_KINDS.values())
VALID_VISIBILITY = {"any", "hidden", "visible"}
VALID_CHAIN_ROLES = {"", "start", "middle", "end"}


def _send_parameters(record: FaceRecord) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "send_mode": ["auto", "standalone", "mixed"],
        "text": "仅 mixed 模式使用；超级表情通常保持单独发送",
    }
    if record.face_kind == "random_super":
        parameters.update(
            {
                "chain_action": ["auto"],
                "result_id": "可选；传入后原样作为 OneBot face.data.resultId",
            }
        )
    elif record.face_kind == "chain_super":
        action = "start" if record.chain_role == "start" else "continue"
        parameters.update(
            {
                "chain_action": [action],
                "chain_count": "可选正整数；传入后覆盖会话状态并直接指定接龙次数",
                "result_id": "可选；传入后原样作为 OneBot face.data.resultId",
            }
        )
    else:
        parameters["chain_action"] = ["auto"]
        parameters["result_id"] = "可选；传入后原样作为 OneBot face.data.resultId"
        parameters["chain_count"] = "仅 chain_super 支持"
    return parameters


def _record_capabilities(catalog: FaceCatalog, record: FaceRecord) -> dict[str, Any]:
    full = catalog.display(record)
    return {
        "face_id": record.id,
        "name": record.canonical_name,
        "family": record.family,
        "kind": record.face_kind,
        "hidden": record.hidden,
        "face_type": record.face_type,
        "sticker_type": record.sticker_type,
        "pack_id": record.pack_id,
        "pack_name": record.pack_name,
        "sticker_id": record.sticker_id,
        "em_code": record.em_code,
        "social_meanings": record.social_meanings,
        "tone": record.tone,
        "usage_contexts": record.usage_contexts,
        "avoid_contexts": record.avoid_contexts,
        "standalone_preferred": record.standalone_preferred,
        "chain_group": record.chain_group,
        "chain_role": record.chain_role,
        "sendable": record.sendable,
        "send_parameters": _send_parameters(record),
        "learned_observations": full["learned_observations"],
    }


def _capability_summary(
    catalog: FaceCatalog, include_hidden: bool = True
) -> dict[str, Any]:
    records = catalog.system_records()
    categories: dict[str, dict[str, Any]] = {}
    for kind in FACE_KINDS.values():
        members = [record for record in records if record.face_kind == kind]
        category: dict[str, Any] = {
            "total": len(members),
            "sendable": sum(record.sendable for record in members),
        }
        if include_hidden:
            hidden_members = [record for record in members if record.hidden]
            category.update(
                {
                    "hidden": len(hidden_members),
                    "hidden_examples": [
                        {"face_id": record.id, "name": record.canonical_name}
                        for record in hidden_members[:8]
                    ],
                }
            )
        categories[kind] = category

    chain_groups: dict[str, dict[str, str]] = defaultdict(dict)
    for record in records:
        if record.chain_group and record.chain_role:
            chain_groups[record.chain_group][record.chain_role] = record.id

    return {
        "catalog_version": catalog.catalog_meta.get("catalog_version", "unknown"),
        "total": len(records),
        "categories": categories,
        "hidden_semantics": (
            "hidden=true 表示 QQ 客户端入口隐藏，不等于不可发送；以 sendable 为准"
        ),
        "random_result": (
            "默认由 QQ 服务端产生；模型可通过 result_id 显式指定并原样透传"
        ),
        "chain_groups": dict(chain_groups),
        "chain_semantics": (
            "默认按会话状态计算 chainCount；传入 chain_count 正整数时覆盖状态，"
            "可直接指定接龙次数"
        ),
        "send_qq_face_parameters": {
            "send_mode": ["auto", "standalone", "mixed"],
            "chain_action": ["auto", "start", "continue"],
            "text": "mixed 模式下的同条文字",
            "result_id": "可选字符串，原样透传到 face.data.resultId",
            "chain_count": "可选正整数；仅 chain_super 生效，覆盖自动状态",
        },
    }


class QQFaceEnhancer(Star):
    """OneBot QQ face understanding, retrieval, sending and nightly learning."""

    def __init__(self, context: Context, config: dict[str, Any] | None = None) -> None:
        super().__init__(context)
        self.config = dict(config or {})
        self.data_dir = StarTools.get_data_dir(PLUGIN_NAME)
        self.catalog = FaceCatalog(self.data_dir, self.config)
        self.learning = LearningWorker(context, self.catalog, self.config)
        self.learning_task: asyncio.Task[Any] | None = None
        try:
            chain_ttl = int(self.config.get("chain_state_ttl_seconds", 180) or 180)
        except (TypeError, ValueError):
            chain_ttl = 180
        try:
            context_window_size = int(self.config.get("context_window_size", 8) or 8)
        except (TypeError, ValueError):
            context_window_size = 8
        self.chain_tracker = ChainStateTracker(chain_ttl)
        self.recent_context: defaultdict[str, deque[str]] = defaultdict(
            lambda: deque(maxlen=max(2, min(context_window_size, 20)))
        )

    @filter.platform_adapter_type("aiocqhttp", priority=100)
    async def enrich_qq_faces(self, event: AstrMessageEvent) -> None:
        """Annotate OneBot QQ faces before AstrBot's Agent stage."""
        annotations = annotate_event(
            event,
            self.catalog,
            enabled=bool(self.config.get("enable_annotation", True)),
            chain_tracker=self.chain_tracker,
        )
        session_id = str(
            getattr(event, "unified_msg_origin", "") or event.get_session_id()
        )
        self.recent_context[session_id].append(event.message_str)
        if not annotations:
            return
        sample = event.get_extra("qqface.context_sample")
        if isinstance(sample, dict):
            sample["context_window"] = list(self.recent_context[session_id])
            sample["session_hash"] = hashlib.sha256(session_id.encode()).hexdigest()[
                :16
            ]
        if bool(self.config.get("learning_enabled", True)):
            self.learning.record_event(event)

    @filter.llm_tool(name="search_qq_face")
    async def search_qq_face(
        self,
        event: AstrMessageEvent,
        query: str,
        tone: str = "",
        family: str = "system_face",
        kind: str = "",
        hidden: str = "any",
        chain_role: str = "",
        limit: int = 5,
    ) -> str:
        """Search known QQ faces by name, social meaning, tone and context.

        Args:
            query(string): 要表达的意图、表情名称或社交语境。
            tone(string): 可选语气，例如友好、调侃、吐槽、安慰。
            family(string): 表情类别，发送时使用 system_face。
            kind(string): 可选能力类型：normal、super、random_super、chain_super。
            hidden(string): 可见性筛选：any、hidden、visible。
            chain_role(string): 可选接龙角色：start、middle、end。
            limit(number): 返回候选数量，最大 5 条。
        """
        _ = event
        if not bool(self.config.get("enable_tools", True)):
            return "QQ 表情工具当前已关闭。"
        try:
            safe_limit = max(1, min(int(limit or 5), 5))
        except (TypeError, ValueError):
            safe_limit = 5
        safe_kind = str(kind or "").strip().lower()
        safe_hidden = str(hidden or "any").strip().lower()
        safe_chain_role = str(chain_role or "").strip().lower()
        if safe_kind and safe_kind not in VALID_KINDS:
            return "kind 无效；可用值：normal、super、random_super、chain_super。"
        if safe_hidden not in VALID_VISIBILITY:
            return "hidden 无效；可用值：any、hidden、visible。"
        if safe_chain_role not in VALID_CHAIN_ROLES:
            return "chain_role 无效；可用值：start、middle、end。"
        records = self.catalog.search(
            query,
            tone=tone,
            family=family,
            kind=safe_kind,
            hidden=safe_hidden,
            chain_role=safe_chain_role,
            limit=safe_limit,
        )
        if not records:
            return "没有找到匹配的 QQ 表情；不要猜测 face_id。"
        results = []
        for record in records:
            results.append(_record_capabilities(self.catalog, record))
        return json.dumps(results, ensure_ascii=False)

    @filter.llm_tool(name="describe_qq_face_capabilities")
    async def describe_qq_face_capabilities(
        self,
        event: AstrMessageEvent,
        face_id: str = "",
        include_hidden: bool = True,
    ) -> str:
        """Describe current QQ face categories, special fields and send controls.

        Args:
            face_id(string): 可选精确数字 ID；为空时返回当前目录能力摘要。
            include_hidden(boolean): 摘要中是否包含隐藏统计和少量示例。
        """
        _ = event
        if not bool(self.config.get("enable_tools", True)):
            return "QQ 表情工具当前已关闭。"
        safe_face_id = str(face_id or "").strip()
        if not safe_face_id:
            return json.dumps(
                _capability_summary(self.catalog, bool(include_hidden)),
                ensure_ascii=False,
            )
        if not safe_face_id.isdigit():
            return "face_id 必须是数字；不要猜测特殊表情 ID。"
        record = self.catalog.get(safe_face_id)
        if not record:
            return f"目录中没有 face_id={safe_face_id}；不要猜测该 ID。"
        return json.dumps(
            _record_capabilities(self.catalog, record), ensure_ascii=False
        )

    @filter.llm_tool(name="send_qq_face")
    async def send_qq_face(
        self,
        event: AstrMessageEvent,
        face_id: str,
        family: str = "system_face",
        text: str = "",
        send_mode: str = "auto",
        chain_action: str = "auto",
        result_id: str = "",
        chain_count: int | str | None = None,
        reason: str = "",
    ) -> str:
        """Send one validated QQ face to the current OneBot conversation.

        Args:
            face_id(string): 必须来自 search_qq_face 的精确数字 ID。
            family(string): 普通和超级表情均使用 system_face。
            text(string): mixed 模式下与表情同条发送的文字；通常留空。
            send_mode(string): auto、standalone 或 mixed；超级表情默认 standalone。
            chain_action(string): auto、start 或 continue；续接必须匹配近期会话状态。
            result_id(string): 可选，显式指定 OneBot face.data.resultId；不传则由 QQ 产生或省略。
            chain_count(number): 可选正整数；chain_super 传入后覆盖会话状态，直接指定接龙次数。
            reason(string): 可选，说明选择该表情的语境，不会发送给用户。
        """
        _ = reason
        if not bool(self.config.get("enable_tools", True)):
            return "QQ 表情工具当前已关闭。"
        if not bool(self.config.get("allow_send", False)):
            return "发送功能当前未启用。"
        return await send_face(
            event,
            self.catalog,
            face_id,
            family,
            text=text,
            send_mode=send_mode,
            chain_action=chain_action,
            result_id=result_id,
            chain_count=chain_count,
            chain_tracker=self.chain_tracker,
        )

    @filter.command("qqface")
    async def qqface_command(self, event: AstrMessageEvent):
        """Inspect and maintain the QQ face catalog."""
        if not event.is_admin():
            yield event.plain_result("只有管理员可以使用 QQ 表情运用增强管理命令。")
            return
        parts = (event.message_str or "").strip().split()
        if parts and parts[0].lstrip("/").lower() == "qqface":
            parts = parts[1:]
        command = parts[0].lower() if parts else "status"

        if command == "status":
            stats = self.catalog.stats()
            state = self.learning.store.get_state()
            configured = (
                str(self.config.get("napcat_face_config_path", "")).strip() or "未配置"
            )
            source_revision = str(
                self.catalog.catalog_meta.get("source_revision", "未知")
            )[:12]
            last_run = str(state.get("last_run_at", "尚未执行"))
            yield event.plain_result(
                f"QQ表情运用增强 v{PLUGIN_VERSION}\n"
                f"目录：{stats['total']} 条（普通 {stats['normal']}，超级 {stats['super']}，"
                f"随机 {stats['random_super']}，接龙 {stats['chain_super']}）\n"
                f"已观察商城表情：{stats['market_face']} 条（仅理解/学习，不发送）\n"
                f"内置来源版本：{source_revision}\n"
                f"NapCat 路径：{configured}\n"
                f"NapCat 同步缓存：{'存在' if self.catalog.napcat_cache_path.is_file() else '尚未生成'}\n"
                f"目录加载告警：{self.catalog.last_load_error or '无'}\n"
                f"语境观察：{stats['observed_faces']} 个表情；夜间学习："
                f"{'启用' if self.config.get('learning_enabled', True) else '关闭'}；上次执行：{last_run}"
            )
            return

        if command == "lookup":
            if len(parts) < 2 or not parts[1].isdigit():
                yield event.plain_result("用法：/qqface lookup <数字ID>")
                return
            record = self.catalog.get(parts[1])
            if not record:
                yield event.plain_result(
                    f"目录中没有 face_id={parts[1]}，不要猜测该 ID。"
                )
                return
            yield event.plain_result(
                json.dumps(self.catalog.display(record), ensure_ascii=False, indent=2)
            )
            return

        if command == "reload":
            self.catalog.load()
            yield event.plain_result("QQ 表情目录已重新加载。")
            return

        if command == "sync":
            target = parts[1].lower() if len(parts) > 1 else "napcat"
            try:
                if target == "napcat":
                    result = await asyncio.to_thread(self.catalog.sync_napcat)
                    yield event.plain_result(
                        f"NapCat 目录同步完成：共 {result['total']} 条，新增 {result['added']}，"
                        f"移除 {result['removed']}，名称/类型变化 {result['changed']}。\n"
                        f"来源：{result['path']}"
                    )
                elif target == "external":
                    message = await asyncio.to_thread(self.catalog.sync_external)
                    self.catalog.load()
                    yield event.plain_result(message)
                else:
                    yield event.plain_result("用法：/qqface sync napcat | external")
            except Exception as exc:
                yield event.plain_result(f"目录同步失败：{exc}")
            return

        if command == "napcat" and len(parts) > 1 and parts[1].lower() == "find":
            configured = str(self.config.get("napcat_face_config_path", "")).strip()
            extra = [Path(configured).parent] if configured else []
            candidates = await asyncio.to_thread(find_napcat_face_configs, 12, extra)
            if not candidates:
                yield event.plain_result(
                    "未在常见 Windows 安装目录找到 face_config.json。请按 README 的 PowerShell 方法定位，"
                    "再填写 napcat_face_config_path。"
                )
            else:
                yield event.plain_result(
                    "找到以下候选路径，请将正确路径填入 napcat_face_config_path：\n"
                    + "\n".join(str(path) for path in candidates)
                )
            return

        if command == "unknown" and len(parts) > 1 and parts[1].lower() == "export":
            unknown: dict[str, dict[str, Any]] = {}
            for sample in self.learning.store.read_since("", 5000):
                for annotation in sample.get("annotations", []):
                    if isinstance(annotation, dict) and not annotation.get("known"):
                        unknown[str(annotation.get("face_key", ""))] = annotation
            path = self.data_dir / "unknown_faces.json"
            temp = path.with_suffix(".tmp")
            temp.write_text(
                json.dumps(list(unknown.values()), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp.replace(path)
            yield event.plain_result(
                f"未知表情已导出：{path.name}（{len(unknown)} 条）"
            )
            return

        yield event.plain_result(
            "用法：/qqface status | lookup <ID> | reload | sync napcat | sync external | "
            "napcat find | unknown export"
        )

    @filter.on_astrbot_loaded()
    async def start_learning_worker(self) -> None:
        if (
            bool(self.config.get("learning_enabled", True))
            and self.learning_task is None
        ):
            self.learning_task = asyncio.create_task(
                self.learning.run(), name="qq-face-nightly-learning"
            )

    async def terminate(self) -> None:
        self.learning.stop()
        if self.learning_task:
            self.learning_task.cancel()
            try:
                await self.learning_task
            except asyncio.CancelledError:
                pass
            self.learning_task = None
