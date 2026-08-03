from __future__ import annotations

from typing import Any

from astrbot.api.event import MessageChain
from astrbot.api.message_components import Face, Plain

from .catalog import FaceCatalog, FaceRecord
from .chain import ChainStateTracker


def _session_id(event: Any) -> str:
    value = getattr(event, "unified_msg_origin", "")
    if value:
        return str(value)
    getter = getattr(event, "get_session_id", None)
    return str(getter() or "") if callable(getter) else ""


async def _send_onebot_segments(event: Any, segments: list[dict[str, Any]]) -> None:
    bot = getattr(event, "bot", None)
    if bot is None:
        raise RuntimeError("当前 aiocqhttp 事件未暴露 bot，无法发送高级表情段。")
    group_id = str(event.get_group_id() or "")
    sender_id = str(event.get_sender_id() or "")
    self_id = str(event.get_self_id() or "") if hasattr(event, "get_self_id") else ""
    routing = {"self_id": int(self_id)} if self_id.isdigit() else {}
    if group_id.isdigit():
        await bot.send_group_msg(group_id=int(group_id), message=segments, **routing)
    elif sender_id.isdigit():
        await bot.send_private_msg(user_id=int(sender_id), message=segments, **routing)
    else:
        raw_event = getattr(getattr(event, "message_obj", None), "raw_message", None)
        if raw_event is None:
            raise RuntimeError(
                "当前事件缺少群号、用户号和原始 OneBot 事件，无法安全路由。"
            )
        await bot.send(event=raw_event, message=segments)


def _advanced_segment(
    record: FaceRecord, chain_count: int | None = None
) -> dict[str, Any]:
    if record.id == "358":
        return {"type": "dice", "data": {"result": "0"}}
    if record.id == "359":
        return {"type": "rps", "data": {"result": "0"}}
    data: dict[str, Any] = {"id": record.id}
    if chain_count is not None:
        data["chainCount"] = chain_count
    return {"type": "face", "data": data}


async def send_face(
    event: Any,
    catalog: FaceCatalog,
    face_id: str,
    family: str = "system_face",
    *,
    text: str = "",
    send_mode: str = "auto",
    chain_action: str = "auto",
    chain_tracker: ChainStateTracker | None = None,
) -> str:
    if event.get_platform_name() != "aiocqhttp":
        return "发送失败：当前事件不是 aiocqhttp/OneBot 平台。"
    if family != "system_face":
        return "发送失败：market_face/mface 仅支持理解与学习，尚未开放发送。"
    if not str(face_id).isdigit():
        return "发送失败：face_id 必须是数字。"
    record = catalog.get(str(face_id), family)
    if not record:
        return (
            f"发送失败：目录中没有已确认的 face_id={face_id}；请先调用 search_qq_face。"
        )
    if not record.sendable:
        return f"发送失败：表情 {record.canonical_name} 当前标记为不可发送。"
    if send_mode not in {"auto", "standalone", "mixed"}:
        return "发送失败：send_mode 只能是 auto、standalone 或 mixed。"
    if chain_action not in {"auto", "start", "continue"}:
        return "发送失败：chain_action 只能是 auto、start 或 continue。"

    clean_text = str(text or "").strip()
    effective_mode = send_mode
    if effective_mode == "auto":
        effective_mode = (
            "standalone"
            if record.standalone_preferred
            else ("mixed" if clean_text else "standalone")
        )
    if effective_mode == "mixed" and not clean_text:
        return "发送失败：mixed 模式必须提供非空 text。"
    if effective_mode == "standalone":
        clean_text = ""

    chain_count: int | None = None
    if record.face_kind == "chain_super":
        if record.chain_role == "start":
            if chain_action == "continue":
                return "发送失败：接龙起点不能作为续接表情发送。"
            chain_count = 1
        else:
            if chain_action == "start":
                return "发送失败：接龙中段/收尾不能脱离同组接龙单独起头。"
            if chain_tracker is None:
                return "发送失败：当前没有可验证的接龙状态。"
            chain_count = chain_tracker.continuation_count(_session_id(event), record)
            if chain_count is None:
                return f"发送失败：近期会话中没有可续接的 {record.chain_group} 接龙。"

    uses_raw = record.face_kind == "chain_super" or record.id in {"358", "359"}
    if uses_raw:
        segments: list[dict[str, Any]] = []
        if clean_text:
            segments.append({"type": "text", "data": {"text": clean_text}})
        segments.append(_advanced_segment(record, chain_count))
        try:
            await _send_onebot_segments(event, segments)
        except Exception as exc:
            return f"发送失败：高级 OneBot 表情段发送异常：{exc}"
    else:
        chain = []
        if clean_text:
            chain.append(Plain(text=clean_text))
        chain.append(Face(id=int(record.id)))
        await event.send(MessageChain(chain))

    if chain_tracker and record.face_kind == "chain_super":
        chain_tracker.observe(_session_id(event), record, chain_count)
    event.set_extra("qqface.tool_sent", True)
    kind_label = {
        "normal": "普通表情",
        "super": "超级表情",
        "random_super": "随机超级表情",
        "chain_super": "接龙超级表情",
    }.get(record.face_kind, "表情")
    return f"已发送 QQ {kind_label}：{record.canonical_name}（face_id={record.id}，{effective_mode}）。"
