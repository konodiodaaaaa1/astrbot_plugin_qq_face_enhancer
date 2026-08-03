from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from .catalog import FaceRecord


@dataclass
class ChainState:
    group: str
    last_face_id: str
    count: int
    expires_at: float


class ChainStateTracker:
    def __init__(
        self, ttl_seconds: int = 180, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.ttl_seconds = max(15, min(int(ttl_seconds), 1800))
        self.clock = clock
        self._states: dict[str, ChainState] = {}

    def observe(
        self, session_id: str, record: FaceRecord, chain_count: int | None = None
    ) -> None:
        if (
            not session_id
            or record.face_kind != "chain_super"
            or not record.chain_group
        ):
            return
        now = self.clock()
        previous = self._states.get(session_id)
        if (
            record.chain_role == "start"
            or not previous
            or previous.group != record.chain_group
            or previous.expires_at <= now
        ):
            count = max(1, chain_count or 1)
        else:
            count = max(previous.count + 1, chain_count or 0)
        self._states[session_id] = ChainState(
            group=record.chain_group,
            last_face_id=record.id,
            count=count,
            expires_at=now + self.ttl_seconds,
        )

    def continuation_count(self, session_id: str, record: FaceRecord) -> int | None:
        if record.face_kind != "chain_super" or record.chain_role == "start":
            return 1 if record.chain_role == "start" else None
        state = self._states.get(session_id)
        if (
            not state
            or state.expires_at <= self.clock()
            or state.group != record.chain_group
        ):
            return None
        return state.count + 1

    def describe(self, session_id: str) -> dict[str, Any] | None:
        state = self._states.get(session_id)
        if not state or state.expires_at <= self.clock():
            return None
        return {
            "group": state.group,
            "last_face_id": state.last_face_id,
            "count": state.count,
        }
