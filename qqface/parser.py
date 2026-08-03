from __future__ import annotations

import hashlib
import time
from typing import Any

from astrbot.core.message.components import At, AtAll, Dice, Face, Plain, Reply, RPS

from .catalog import FaceCatalog, FaceRecord
from .chain import ChainStateTracker


KIND_LABELS = {
    "normal": "QQ表情",
    "super": "QQ超级表情",
    "random_super": "QQ随机超级表情",
    "chain_super": "QQ接龙超级表情",
}
CHAIN_LABELS = {"start": "接龙起点", "middle": "接龙中段", "end": "接龙收尾"}


def _raw_segments(raw_message: Any) -> list[dict[str, Any]]:
    if not hasattr(raw_message, "get"):
        return []
    message = raw_message.get("message", [])
    return (
        [item for item in message if isinstance(item, dict)]
        if isinstance(message, list)
        else []
    )


def _data(raw_segment: dict[str, Any]) -> dict[str, Any]:
    value = raw_segment.get("data")
    return value if isinstance(value, dict) else {}


def _nested_values(raw_segment: dict[str, Any]) -> list[dict[str, Any]]:
    data = _data(raw_segment)
    containers = [data]
    for key in ("raw", "faceElement"):
        value = data.get(key)
        if isinstance(value, dict):
            containers.append(value)
    raw = data.get("raw")
    if isinstance(raw, dict) and isinstance(raw.get("faceElement"), dict):
        containers.append(raw["faceElement"])
    return containers


def _field(raw_segment: dict[str, Any], *keys: str) -> Any:
    for container in _nested_values(raw_segment):
        for key in keys:
            value = container.get(key)
            if value not in (None, ""):
                return value
    return None


def _face_text(raw_segment: dict[str, Any]) -> str:
    value = _field(raw_segment, "faceText", "QDes", "text", "summary")
    return str(value or "").removeprefix("/")


def _session_id(event: Any) -> str:
    value = getattr(event, "unified_msg_origin", "")
    if value:
        return str(value)
    getter = getattr(event, "get_session_id", None)
    return str(getter() or "") if callable(getter) else ""


def _message_position(raw_segments: list[dict[str, Any]]) -> str:
    emotions = 0
    other = False
    for segment in raw_segments:
        segment_type = str(segment.get("type", ""))
        if segment_type in {"face", "mface", "dice", "rps"}:
            emotions += 1
        elif segment_type == "text":
            if str(_data(segment).get("text", "")).strip():
                other = True
        elif segment_type not in {"reply"}:
            other = True
    return "单独发送" if emotions == 1 and not other else "混合消息"


def _find_raw(
    raw_segments: list[dict[str, Any]], consumed: set[int], wanted: str
) -> tuple[dict[str, Any] | None, int | None]:
    for index, segment in enumerate(raw_segments):
        if index not in consumed and segment.get("type") == wanted:
            consumed.add(index)
            return segment, index
    return None, None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _annotation(
    record: FaceRecord | None,
    face_id: str,
    family: str,
    raw_segment: dict[str, Any],
    position: str,
) -> dict[str, Any]:
    result_id = _field(raw_segment, "resultId", "result")
    chain_count = _int_or_none(_field(raw_segment, "chainCount"))
    face_text = _face_text(raw_segment)
    return {
        "face_key": record.key if record else f"onebot_v11:{family}:{face_id}",
        "family": family,
        "id": str(face_id),
        "name": record.canonical_name if record else (face_text or "未知"),
        "face_text": face_text,
        "known": bool(record),
        "face_kind": record.face_kind if record else "unknown",
        "position": position,
        "result_id": str(result_id) if result_id not in (None, "") else "",
        "chain_count": chain_count,
        "chain_group": record.chain_group if record else "",
        "chain_role": record.chain_role if record else "",
        "raw_face_type": _int_or_none(_field(raw_segment, "faceType")),
    }


def _marker(record: FaceRecord | None, annotation: dict[str, Any]) -> str:
    if annotation["family"] == "market_face":
        label = "QQ商城表情"
        id_label = "emoji_id"
    else:
        label = KIND_LABELS.get(annotation["face_kind"], "QQ表情")
        id_label = "face_id"
    parts = [
        annotation["name"],
        f"{id_label}={annotation['id']}",
        annotation["position"],
    ]
    if record and record.chain_role:
        parts.append(CHAIN_LABELS.get(record.chain_role, record.chain_role))
    if annotation.get("chain_count"):
        parts.append(f"接龙次数={annotation['chain_count']}")
    if annotation.get("result_id"):
        parts.append(f"结果={annotation['result_id']}")
    return f"[{label}:{'|'.join(parts)}]"


def annotate_event(
    event: Any,
    catalog: FaceCatalog,
    enabled: bool = True,
    chain_tracker: ChainStateTracker | None = None,
) -> list[dict[str, Any]]:
    """Build model-facing markers while leaving AstrBot's component chain untouched."""
    annotations: list[dict[str, Any]] = []
    if not enabled:
        event.set_extra("qqface.annotations", annotations)
        return annotations

    message_obj = getattr(event, "message_obj", None)
    message_chain = getattr(message_obj, "message", []) or []
    raw_segments = _raw_segments(getattr(message_obj, "raw_message", None))
    position = (
        _message_position(raw_segments)
        if raw_segments
        else ("单独发送" if len(message_chain) == 1 else "混合消息")
    )
    consumed: set[int] = set()
    rendered: list[str] = []
    session_id = _session_id(event)

    def consume_system(face_id: str, wanted: str = "face") -> str:
        raw, _ = _find_raw(raw_segments, consumed, wanted)
        record = catalog.get(face_id)
        annotation = _annotation(record, face_id, "system_face", raw or {}, position)
        annotations.append(annotation)
        if chain_tracker and record:
            chain_tracker.observe(session_id, record, annotation.get("chain_count"))
        return _marker(record, annotation)

    def render_component(component: Any) -> str:
        if isinstance(component, Plain):
            return component.text
        if isinstance(component, Face):
            return consume_system(str(component.id))
        if isinstance(component, Dice):
            return consume_system("358", "dice")
        if isinstance(component, RPS):
            return consume_system("359", "rps")
        if isinstance(component, AtAll):
            return " @全体成员 "
        if isinstance(component, At):
            return f" @{component.name or component.qq} "
        if isinstance(component, Reply):
            nested = "".join(render_component(item) for item in (component.chain or []))
            return f"[引用消息:{nested or component.message_str}]"
        return ""

    rendered.extend(render_component(component) for component in message_chain)

    # Some AstrBot adapter versions drop NapCat extension segments. Recover them
    # from the original OneBot event after pairing all components that survived.
    for index, segment in enumerate(raw_segments):
        if index in consumed or segment.get("type") not in {
            "face",
            "mface",
            "dice",
            "rps",
        }:
            continue
        segment_type = str(segment.get("type"))
        data = _data(segment)
        if segment_type == "mface":
            face_id = str(data.get("emoji_id") or data.get("key") or "")
            if not face_id:
                continue
            record = catalog.observe_market_face(
                face_id,
                str(data.get("summary", "")) or _face_text(segment),
                str(data.get("emoji_package_id", "")),
                str(data.get("key", "")),
            )
            annotation = _annotation(record, face_id, "market_face", segment, position)
            annotation.update(
                {
                    "package_id": str(data.get("emoji_package_id", "")),
                    "summary": str(data.get("summary", "")),
                }
            )
        else:
            face_id = (
                "358"
                if segment_type == "dice"
                else "359"
                if segment_type == "rps"
                else str(data.get("id", ""))
            )
            if not face_id:
                continue
            record = catalog.get(face_id)
            annotation = _annotation(record, face_id, "system_face", segment, position)
            if chain_tracker and record:
                chain_tracker.observe(session_id, record, annotation.get("chain_count"))
        annotations.append(annotation)
        rendered.append(_marker(record, annotation))

    text = "".join(rendered).strip()
    if not text:
        text = str(getattr(event, "message_str", "") or "").strip()
    event.message_str = text
    if message_obj is not None:
        message_obj.message_str = text
    event.set_extra("qqface.annotations", annotations)
    event.set_extra(
        "qqface.context_sample",
        {
            "sample_id": hashlib.sha256(
                f"{time.time_ns()}:{text}".encode()
            ).hexdigest()[:20],
            "timestamp": int(time.time()),
            "text": text[:4000],
            "annotations": annotations,
        },
    )
    return annotations
