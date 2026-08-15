from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .catalog import FaceCatalog


class SampleStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "context_samples.jsonl"
        self.state_path = data_dir / "learning_state.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, sample: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(sample, ensure_ascii=False) + "\n")

    def trim(self, max_lines: int) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if len(lines) <= max_lines:
            return
        temp = self.path.with_suffix(".tmp")
        temp.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")
        temp.replace(self.path)

    def read_since(self, last_sample_id: str, limit: int) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        valid_samples: list[dict[str, Any]] = []
        for line in lines:
            try:
                sample = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(sample, dict):
                continue
            valid_samples.append(sample)
        if not last_sample_id:
            return valid_samples[:limit]
        for index, sample in enumerate(valid_samples):
            if sample.get("sample_id") == last_sample_id:
                return valid_samples[index + 1 : index + 1 + limit]
        # Retention may have removed the saved cursor. Process the newest bounded
        # window instead of becoming permanently stuck behind a missing ID.
        return valid_samples[-limit:]

    def get_state(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save_state(self, state: dict[str, Any]) -> None:
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(self.state_path)


def _extract_json(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(
            r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I | re.S
        ).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return []
        return []


class LearningWorker:
    def __init__(
        self, context: Any, catalog: FaceCatalog, config: dict[str, Any]
    ) -> None:
        self.context = context
        self.catalog = catalog
        self.config = config
        self.store = SampleStore(catalog.data_dir)
        self.stop_event = asyncio.Event()

    def record_event(self, event: Any) -> None:
        sample = event.get_extra("qqface.context_sample")
        if not isinstance(sample, dict) or not sample.get("annotations"):
            return
        self.store.append(sample)
        try:
            max_samples = max(
                200, min(int(self.config.get("learning_retained_samples", 5000)), 50000)
            )
        except (TypeError, ValueError):
            max_samples = 5000
        self.store.trim(max_samples)

    async def run(self) -> None:
        while not self.stop_event.is_set():
            delay = self._seconds_until_target()
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=delay)
                return
            except asyncio.TimeoutError:
                await self.run_once()

    def stop(self) -> None:
        self.stop_event.set()

    def _seconds_until_target(self) -> float:
        raw = str(self.config.get("learning_time", "03:30"))
        try:
            hour, minute = (int(value) for value in raw.split(":", 1))
            hour = max(0, min(23, hour))
            minute = max(0, min(59, minute))
        except (ValueError, TypeError):
            hour, minute = 3, 30
        now = datetime.now().astimezone()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return max(1.0, (target - now).total_seconds())

    async def run_once(self) -> None:
        state = self.store.get_state()
        try:
            max_samples = int(self.config.get("learning_max_samples", 100))
        except (TypeError, ValueError):
            max_samples = 100
        samples = self.store.read_since(
            str(state.get("last_sample_id", "")),
            max(1, min(max_samples, 500)),
        )
        if not samples:
            return
        provider_id = str(self.config.get("learning_provider_id", "")).strip()
        provider = (
            self.context.get_provider_by_id(provider_id)
            if provider_id
            else self.context.get_using_provider()
        )
        if not provider:
            logger.warning(
                "qq_face_enhancer: no provider available for nightly learning"
            )
            return
        prompt = json.dumps(samples, ensure_ascii=False)
        system_prompt = (
            "你是 QQ 表情语境整理器。输入包含带具体 face_key、表情位置、随机结果和接龙信息的完整上下文窗口。"
            "请严格区分通用规律与具体案例：meaning、tone、usage_context、avoid_context 只能描述跨话题、"
            "跨场景仍成立的表达功能；case_context、case_evidence 只记录本批样本中的一个去身份化案例，"
            "用于解释证据，不能把案例主题当成表情固有含义。比如高考志愿、退档、某个账号、某个人名"
            "只能放进 case_context/case_evidence，不能写入 meaning 或 usage_context。"
            "至少需要 3 个相互独立的样本，且表达模式一致，才允许 status=active 的 upsert；"
            "只有单一话题、单次出现或证据不足时，使用 status=pending_review，不得提升为通用语义。"
            "避免复述原文中的姓名、QQ号、群名、链接、精确时间和其他可识别信息。"
            "不要修改 ID 或官方名称，不要仅凭一次样本过度推断。只输出 JSON 数组。"
            "每条字段：action(upsert/deprecate/delete), face_key, meaning, tone, usage_context, "
            "avoid_context, case_context, case_evidence, confidence(0到1), evidence_count, "
            "status(active或pending_review)。meaning 是通用表达功能，usage_context 是通用场景；"
            "case_context 不超过 80 字，case_evidence 不超过 240 字。"
            "deprecate/delete 必须精确填写已有 meaning；没有可靠更新时输出空数组。"
        )
        try:
            try:
                timeout_seconds = int(self.config.get("learning_timeout_seconds", 120))
            except (TypeError, ValueError):
                timeout_seconds = 120
            response = await asyncio.wait_for(
                provider.text_chat(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    request_max_retries=1,
                ),
                timeout=max(10, timeout_seconds),
            )
            proposals = _extract_json(response.completion_text or "")
            if isinstance(proposals, list):
                for proposal in proposals:
                    if isinstance(proposal, dict):
                        self.catalog.apply_learning_proposal(proposal)
            state["last_sample_id"] = samples[-1].get("sample_id", "")
            state["last_run_at"] = datetime.now().astimezone().isoformat()
            self.store.save_state(state)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("qq_face_enhancer: nightly learning failed")
