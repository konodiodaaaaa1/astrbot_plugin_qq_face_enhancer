from __future__ import annotations

import asyncio
from pathlib import Path

from qqface import sender
from qqface.catalog import FaceCatalog


class Event:
    def __init__(self, *, group_id: str = "", sender_id: str = "2452585759"):
        self.group_id = group_id
        self.sender_id = sender_id
        self.extra = {}

    def get_platform_name(self):
        return "aiocqhttp"

    def get_group_id(self):
        return self.group_id

    def get_sender_id(self):
        return self.sender_id

    def set_extra(self, key, value):
        self.extra[key] = value


def test_rainbow_dragon_is_a_searchable_hidden_variant(tmp_path: Path):
    catalog = FaceCatalog(tmp_path)
    record = catalog.search("完整七彩祥龙", hidden="hidden", limit=1)[0]
    assert record.id == "394"
    assert record.send_payload["variants"] == ["rainbow_dragon_2024"]


def test_rainbow_dragon_uses_the_same_tool_for_private_and_group(tmp_path, monkeypatch):
    catalog = FaceCatalog(tmp_path)
    calls = []

    def request(endpoint, token, payload, timeout):
        calls.append((endpoint, token, payload, timeout))
        return {"code": 0, "data": {"message_seq": "9808"}}

    monkeypatch.setattr(sender, "_native_request", request)
    config = {
        "napcat_extended_api_url": "http://127.0.0.1:6099/plugin/face/api",
        "napcat_extended_api_token": "test-token",
    }
    for event in (Event(), Event(group_id="123456789")):
        result = asyncio.run(
            sender.send_face(
                event,
                catalog,
                "394",
                variant="rainbow_dragon_2024",
                config=config,
            )
        )
        assert "已发送 QQ 隐藏表情：七彩祥龙" in result
        assert event.extra["qqface.tool_sent"] is True

    assert calls[0][0].endswith("/send-special")
    assert calls[0][2] == {
        "effect": "rainbow_dragon_2024",
        "peer": {"type": "private", "id": "2452585759"},
    }
    assert calls[1][2] == {
        "effect": "rainbow_dragon_2024",
        "peer": {"type": "group", "id": "123456789"},
    }


def test_school_hidden_face_uses_chain_end_trigger(tmp_path, monkeypatch):
    catalog = FaceCatalog(tmp_path)
    calls = []

    def request(endpoint, token, payload, timeout):
        calls.append(payload)
        return {"code": 0, "data": {"message_seq": "school-hidden"}}

    monkeypatch.setattr(sender, "_native_request", request)
    config = {
        "napcat_extended_api_url": "http://127.0.0.1:6099/plugin/face/api",
        "napcat_extended_api_token": "test-token",
    }
    result = asyncio.run(
        sender.send_face(
            event=Event(),
            catalog=catalog,
            face_id="488",
            variant="school_opening_2026",
            config=config,
        )
    )

    assert "开学大吉" in result
    assert calls[0] == {
        "effect": "school_opening_2026",
        "peer": {"type": "private", "id": "2452585759"},
    }


def test_midautumn_catalog_contains_chain_and_hidden_face(tmp_path, monkeypatch):
    catalog = FaceCatalog(tmp_path)
    chain = catalog.get("502")
    hidden = catalog.search("秋愿达成", hidden="hidden", limit=1)[0]
    assert chain is not None
    assert (chain.chain_group, chain.chain_role) == ("autumn_2026", "end")
    assert hidden.id == "503"
    assert hidden.hidden is True
    assert hidden.face_kind == "super"

    calls = []

    def request(endpoint, token, payload, timeout):
        calls.append(payload)
        return {"code": 0, "data": {"message_id": "midautumn-hidden"}}

    monkeypatch.setattr(sender, "_native_request", request)
    config = {
        "napcat_extended_api_url": "http://127.0.0.1:6099/plugin/face/api",
        "napcat_extended_api_token": "test-token",
    }
    result = asyncio.run(
        sender.send_face(event=Event(), catalog=catalog, face_id="503", config=config)
    )

    assert "秋愿达成" in result
    assert calls[0]["face"] == {
        "face_id": "503",
        "face_type": 3,
        "face_text": "秋愿达成",
        "pack_id": "1",
        "sticker_id": "105",
        "source_type": 1,
        "sticker_type": 1,
        "result_id": "",
        "chain_count": None,
    }
