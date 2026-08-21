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
