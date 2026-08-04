from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
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


def _native_endpoint(config: dict[str, Any] | None) -> str:
    value = str((config or {}).get("napcat_extended_api_url", "") or "").strip()
    return value.rstrip("/") + "/send" if value else ""


def _native_request(
    endpoint: str,
    token: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any] | None:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **({"x-qqface-token": token} if token else {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict):
            raise RuntimeError("NapCat native sender returned a non-object response")
        if result.get("code", 0) != 0:
            raise RuntimeError(str(result.get("message") or "request rejected"))
        return result
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError:
        return None


async def _send_native_face(
    event: Any,
    record: FaceRecord,
    *,
    text: str,
    result_id: str,
    chain_count: int | None,
    config: dict[str, Any] | None,
) -> tuple[bool, str]:
    endpoint = _native_endpoint(config)
    if not endpoint:
        return False, ""
    group_id = str(event.get_group_id() or "")
    sender_id = str(event.get_sender_id() or "")
    if group_id.isdigit():
        peer = {"type": "group", "id": group_id}
    elif sender_id.isdigit():
        peer = {"type": "private", "id": sender_id}
    else:
        return True, "NapCat 原生表情发送失败：当前事件缺少可路由的群号或用户号"
    payload = {
        "peer": peer,
        "text": text,
        "face": {
            "face_id": record.id,
            "face_type": record.face_type,
            "face_text": record.literal_description or record.canonical_name,
            "pack_id": record.pack_id,
            "sticker_id": record.sticker_id,
            "source_type": 1,
            "sticker_type": record.sticker_type,
            "result_id": result_id,
            "chain_count": chain_count,
        },
    }
    token = str((config or {}).get("napcat_extended_api_token", "") or "").strip()
    try:
        timeout = float((config or {}).get("napcat_extended_api_timeout_seconds", 8) or 8)
    except (TypeError, ValueError):
        timeout = 8.0
    try:
        result = await asyncio.to_thread(
            _native_request, endpoint, token, payload, max(1.0, min(timeout, 30.0))
        )
    except Exception as exc:
        return True, f"NapCat 原生表情发送失败：{exc}"
    return (True, "") if result is not None else (False, "")


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
    record: FaceRecord,
    chain_count: int | None = None,
    result_id: str = "",
) -> dict[str, Any]:
    # NapCat's dice/rps shortcuts ignore their result field. An explicit
    # result_id therefore must use a face segment so it reaches resultId.
    if record.id == "358" and not result_id:
        return {"type": "dice", "data": {"result": "0"}}
    if record.id == "359" and not result_id:
        return {"type": "rps", "data": {"result": "0"}}
    data: dict[str, Any] = {"id": record.id}
    if result_id:
        data["resultId"] = result_id
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
    result_id: str = "",
    chain_count: int | str | None = None,
    chain_tracker: ChainStateTracker | None = None,
    config: dict[str, Any] | None = None,
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

    raw_result_id = "" if result_id is None else str(result_id)
    if len(raw_result_id) > 128 or any(ord(char) < 32 for char in raw_result_id):
        return "发送失败：result_id 必须是不超过 128 个字符的单行字符串。"
    clean_result_id = raw_result_id.strip()

    explicit_chain_count = chain_count not in (None, "")
    parsed_chain_count: int | None = None
    if explicit_chain_count:
        if record.face_kind != "chain_super":
            return "发送失败：chain_count 仅适用于接龙超级表情（chain_super）。"
        raw_chain_count = str(chain_count).strip()
        if not raw_chain_count or any(
            char not in "0123456789" for char in raw_chain_count
        ):
            return "发送失败：chain_count 必须是正整数。"
        parsed_chain_count = int(raw_chain_count)
        if parsed_chain_count <= 0:
            return "发送失败：chain_count 必须是正整数。"

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

    effective_chain_count: int | None = None
    if record.face_kind == "chain_super":
        if parsed_chain_count is not None:
            if record.chain_role == "start" and chain_action == "continue":
                return "发送失败：接龙起点不能作为续接表情发送。"
            if record.chain_role != "start" and chain_action == "start":
                return "发送失败：接龙中段/收尾不能作为接龙起点发送。"
            effective_chain_count = parsed_chain_count
        elif record.chain_role == "start":
            if chain_action == "continue":
                return "发送失败：接龙起点不能作为续接表情发送。"
            effective_chain_count = 1
        else:
            if chain_action == "start":
                return "发送失败：接龙中段/收尾不能脱离同组接龙单独起头。"
            if chain_tracker is None:
                return "发送失败：当前没有可验证的接龙状态。"
            effective_chain_count = chain_tracker.continuation_count(
                _session_id(event), record
            )
            if effective_chain_count is None:
                return f"发送失败：近期会话中没有可续接的 {record.chain_group} 接龙。"

    native_required = bool(
        record.face_kind in {"super", "random_super", "chain_super"}
        or int(record.id) > 432
    )
    if native_required and _native_endpoint(config):
        used, error = await _send_native_face(
            event,
            record,
            text=clean_text,
            result_id=clean_result_id,
            chain_count=effective_chain_count,
            config=config,
        )
        if used:
            if error:
                return error
            if chain_tracker and record.face_kind == "chain_super":
                chain_tracker.observe(_session_id(event), record, effective_chain_count)
            event.set_extra("qqface.tool_sent", True)
            details = [f"face_id={record.id}", effective_mode, "native=napcat"]
            if clean_result_id:
                details.append(f"resultId={clean_result_id}")
            if parsed_chain_count is not None:
                details.append(f"chainCount={parsed_chain_count}")
            return f"已发送 QQ {record.canonical_name}（{'，'.join(details)}）。"

    uses_raw = (
        record.face_kind == "chain_super"
        or record.id in {"358", "359"}
        or bool(clean_result_id)
        or parsed_chain_count is not None
    )
    if uses_raw:
        segments: list[dict[str, Any]] = []
        if clean_text:
            segments.append({"type": "text", "data": {"text": clean_text}})
        segments.append(
            _advanced_segment(record, effective_chain_count, clean_result_id)
        )
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
        chain_tracker.observe(_session_id(event), record, effective_chain_count)
    event.set_extra("qqface.tool_sent", True)
    kind_label = {
        "normal": "普通表情",
        "super": "超级表情",
        "random_super": "随机超级表情",
        "chain_super": "接龙超级表情",
    }.get(record.face_kind, "表情")
    details = [f"face_id={record.id}", effective_mode]
    if clean_result_id:
        details.append(f"resultId={clean_result_id}")
    if parsed_chain_count is not None:
        details.append(f"chainCount={parsed_chain_count}")
    return f"已发送 QQ {kind_label}：{record.canonical_name}（{'，'.join(details)}）。"
