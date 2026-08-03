from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


CATALOG_FILE = Path(__file__).with_name("default_catalog.json")
NAPCAT_CACHE_FILE = "napcat_catalog.json"
FACE_KINDS = {0: "normal", 1: "super", 2: "random_super", 3: "chain_super"}
FACE_KIND_ALIASES = {
    "normal": "普通 基础 normal",
    "super": "超级 动画 super",
    "random_super": "随机 随机超级 random random_super",
    "chain_super": "接龙 连击 接龙超级 chain chain_super",
}
CHAIN_ROLE_ALIASES = {
    "start": "起点 开始 start",
    "middle": "中段 续接 middle",
    "end": "收尾 结束 end",
}
CHAIN_GROUPS = {
    "392": ("dragon_2024", "start"),
    "393": ("dragon_2024", "middle"),
    "394": ("dragon_2024", "end"),
    "415": ("dragon_boat", "start"),
    "416": ("dragon_boat", "middle"),
    "417": ("dragon_boat", "end"),
    "419": ("train", "start"),
    "420": ("train", "middle"),
    "421": ("train", "end"),
    "429": ("snake_2025", "start"),
    "430": ("snake_2025", "middle"),
    "431": ("snake_2025", "end"),
}


def _as_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(path)


@dataclass
class FaceRecord:
    protocol: str = "onebot_v11"
    adapter: str = "aiocqhttp"
    family: str = "system_face"
    id: str = ""
    canonical_name: str = ""
    literal_description: str = ""
    aliases: list[str] = field(default_factory=list)
    social_meanings: list[str] = field(default_factory=list)
    tone: list[str] = field(default_factory=list)
    usage_contexts: list[str] = field(default_factory=list)
    avoid_contexts: list[str] = field(default_factory=list)
    face_kind: str = "normal"
    face_type: int = 1
    sticker_type: int = 0
    pack_id: str = ""
    pack_name: str = ""
    sticker_id: str = ""
    em_code: str = ""
    hidden: bool = False
    standalone_preferred: bool = False
    chain_group: str = ""
    chain_role: str = ""
    sendable: bool = False
    send_payload: dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    source_revision: str = ""
    confidence: float = 0.0
    updated_at: str = ""

    @property
    def key(self) -> str:
        return f"{self.protocol}:{self.family}:{self.id}"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FaceRecord":
        fields = set(cls.__dataclass_fields__)
        data = {key: value[key] for key in fields if key in value}
        data["id"] = str(data.get("id", ""))
        for key in (
            "aliases",
            "social_meanings",
            "tone",
            "usage_contexts",
            "avoid_contexts",
        ):
            data[key] = _as_strings(data.get(key))
        data["send_payload"] = (
            data.get("send_payload")
            if isinstance(data.get("send_payload"), dict)
            else {}
        )
        for key in ("hidden", "standalone_preferred", "sendable"):
            data[key] = bool(data.get(key, False))
        for key in ("face_type", "sticker_type"):
            try:
                data[key] = int(data.get(key, 0))
            except (TypeError, ValueError):
                data[key] = 0
        try:
            data["confidence"] = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            data["confidence"] = 0.0
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def searchable_text(self) -> str:
        return " ".join(
            [
                self.id,
                self.canonical_name,
                self.literal_description,
                self.face_kind,
                self.pack_name,
                *self.aliases,
                *self.social_meanings,
                *self.tone,
                *self.usage_contexts,
                *self.avoid_contexts,
            ]
        ).lower()


def normalize_napcat_payload(
    payload: Any, source_revision: str = "local"
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("sysface"), list):
        raise ValueError("NapCat 配置必须是包含非空 sysface 数组的 JSON 对象。")
    items = payload["sysface"]
    if not items:
        raise ValueError("NapCat sysface 数组为空。")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"sysface[{index}] 不是对象。")
        face_id = str(item.get("QSid", "")).strip()
        name = str(item.get("QDes", "")).removeprefix("/").strip()
        if not face_id.isdigit() or not name:
            raise ValueError(f"sysface[{index}] 缺少有效的 QSid/QDes。")
        if face_id in seen:
            raise ValueError(f"sysface 存在重复 QSid={face_id}。")
        seen.add(face_id)
        try:
            sticker_type = int(item.get("AniStickerType") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"QSid={face_id} 的 AniStickerType 无效。") from exc
        if sticker_type not in FACE_KINDS:
            sticker_type = 0
        group, role = CHAIN_GROUPS.get(face_id, ("", ""))
        records.append(
            {
                "protocol": "onebot_v11",
                "adapter": "aiocqhttp",
                "family": "system_face",
                "id": face_id,
                "canonical_name": name,
                "literal_description": name,
                "face_kind": FACE_KINDS[sticker_type],
                "face_type": 3 if sticker_type else (2 if int(face_id) >= 222 else 1),
                "sticker_type": sticker_type,
                "pack_id": str(item.get("AniStickerPackId") or ""),
                "pack_name": str(item.get("AniStickerPackName") or ""),
                "sticker_id": str(item.get("AniStickerId") or ""),
                "em_code": str(item.get("EMCode") or ""),
                "hidden": str(item.get("QHide") or "0") == "1",
                "standalone_preferred": sticker_type in {1, 2, 3},
                "chain_group": group,
                "chain_role": role,
                "sendable": True,
                "send_payload": {"type": "face", "data": {"id": face_id}},
                "source": "napcat_local",
                "source_revision": source_revision,
                "confidence": 0.98,
                "updated_at": datetime.now().astimezone().date().isoformat(),
            }
        )
    return records


class FaceCatalog:
    def __init__(self, data_dir: Path, config: dict[str, Any] | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.config = config or {}
        self.records: dict[str, FaceRecord] = {}
        self.observations: dict[str, list[dict[str, Any]]] = {}
        self.catalog_meta: dict[str, Any] = {}
        self.last_load_error = ""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.load()

    @property
    def observations_path(self) -> Path:
        return self.data_dir / "observations.json"

    @property
    def napcat_cache_path(self) -> Path:
        return self.data_dir / NAPCAT_CACHE_FILE

    @property
    def market_faces_path(self) -> Path:
        return self.data_dir / "observed_market_faces.json"

    @property
    def audit_path(self) -> Path:
        return self.data_dir / "learning_audit.jsonl"

    def load(self) -> None:
        self.records.clear()
        self.catalog_meta = {}
        self.last_load_error = ""
        self._merge_file(CATALOG_FILE, "builtin")
        self._merge_file(self.napcat_cache_path, "napcat_cache")
        self._merge_file(self.market_faces_path, "observed_market")
        external_path = str(self.config.get("external_catalog_path", "")).strip()
        self._merge_file(
            Path(external_path), "external"
        ) if external_path else self._merge_file(
            self.data_dir / "external_catalog.json", "external"
        )
        configured_napcat = str(self.config.get("napcat_face_config_path", "")).strip()
        if configured_napcat:
            try:
                self._merge_napcat(Path(configured_napcat))
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                self.last_load_error = f"NapCat 配置加载失败：{exc}"
        self._load_observations()

    def _merge_file(self, path: Path, source_hint: str) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return
        if source_hint == "builtin" and isinstance(payload, dict):
            self.catalog_meta = {
                key: value for key, value in payload.items() if key != "faces"
            }
        items = payload.get("faces", []) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            record = FaceRecord.from_dict(item)
            if not record.id:
                continue
            existing = self.records.get(record.key)
            if existing and source_hint == "external":
                merged = existing.to_dict()
                merged.update(item)
                record = FaceRecord.from_dict(merged)
            elif existing and source_hint == "napcat_cache":
                record = self._preserve_semantics(existing, record)
            self.records[record.key] = record

    @staticmethod
    def _preserve_semantics(
        existing: FaceRecord, replacement: FaceRecord
    ) -> FaceRecord:
        for field_name in (
            "aliases",
            "social_meanings",
            "tone",
            "usage_contexts",
            "avoid_contexts",
        ):
            if not getattr(replacement, field_name):
                setattr(replacement, field_name, list(getattr(existing, field_name)))
        return replacement

    def _merge_napcat(self, path: Path) -> None:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        normalized = normalize_napcat_payload(
            payload, source_revision=f"local:{path.name}"
        )
        if len(normalized) < 100:
            raise ValueError(
                f"sysface 只有 {len(normalized)} 条，拒绝作为完整目录加载。"
            )
        for item in normalized:
            record = FaceRecord.from_dict(item)
            existing = self.records.get(record.key)
            self.records[record.key] = (
                self._preserve_semantics(existing, record) if existing else record
            )

    def sync_napcat(self, path: Path | None = None) -> dict[str, Any]:
        selected = path or Path(
            str(self.config.get("napcat_face_config_path", "")).strip()
        )
        if not str(selected).strip() or str(selected) == ".":
            raise ValueError(
                "未配置 napcat_face_config_path；先执行 /qqface napcat find。"
            )
        selected = selected.expanduser().resolve()
        if selected.name.lower() != "face_config.json" or not selected.is_file():
            raise ValueError(f"找不到有效的 face_config.json：{selected}")
        payload = json.loads(selected.read_text(encoding="utf-8-sig"))
        normalized = normalize_napcat_payload(
            payload, source_revision=f"local:{selected}"
        )
        if len(normalized) < 100:
            raise ValueError(f"sysface 只有 {len(normalized)} 条，拒绝覆盖完整目录。")
        before = {record.id: record for record in self.system_records()}
        after = {item["id"]: FaceRecord.from_dict(item) for item in normalized}
        added = sorted(set(after) - set(before), key=int)
        removed = sorted(set(before) - set(after), key=int)
        changed = sorted(
            (
                face_id
                for face_id in set(before) & set(after)
                if (before[face_id].canonical_name, before[face_id].face_kind)
                != (after[face_id].canonical_name, after[face_id].face_kind)
            ),
            key=int,
        )
        _atomic_json(
            self.napcat_cache_path,
            {
                "schema_version": 1,
                "source": str(selected),
                "synced_at": datetime.now().astimezone().isoformat(),
                "faces": normalized,
            },
        )
        self.load()
        return {
            "path": str(selected),
            "total": len(normalized),
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "added_sample": added[:8],
            "removed_sample": removed[:8],
            "changed_sample": changed[:8],
        }

    def sync_external(self) -> str:
        url = str(self.config.get("external_catalog_url", "")).strip()
        if not url:
            return "未配置 external_catalog_url。"
        if urllib.parse.urlparse(url).scheme != "https":
            raise ValueError("外部目录只允许 HTTPS URL。")
        try:
            timeout = max(5, min(120, int(self.config.get("sync_timeout_seconds", 20))))
        except (TypeError, ValueError):
            timeout = 20
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "qq-face-enhancer/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items = payload.get("faces", []) if isinstance(payload, dict) else payload
        if not isinstance(items, list) or not items:
            raise ValueError("外部目录不是非空表情数组。")
        for item in items:
            if (
                not isinstance(item, dict)
                or not str(item.get("id", "")).strip()
                or not item.get("family")
            ):
                raise ValueError("外部目录存在缺少 id/family 的记录。")
        _atomic_json(self.data_dir / "external_catalog.json", {"faces": items})
        return f"已同步 {len(items)} 条外部目录记录。"

    def _load_observations(self) -> None:
        try:
            payload = json.loads(self.observations_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.observations = {}
            return
        self.observations = payload if isinstance(payload, dict) else {}

    def save_observations(self) -> None:
        _atomic_json(self.observations_path, self.observations)

    def get(self, face_id: str | int, family: str = "system_face") -> FaceRecord | None:
        return self.records.get(f"onebot_v11:{family}:{face_id}")

    def all_records(self) -> Iterable[FaceRecord]:
        return self.records.values()

    def system_records(self) -> list[FaceRecord]:
        return [
            record for record in self.records.values() if record.family == "system_face"
        ]

    def stats(self) -> dict[str, int]:
        counts = Counter(record.face_kind for record in self.system_records())
        return {
            "total": len(self.system_records()),
            "normal": counts["normal"],
            "super": counts["super"],
            "random_super": counts["random_super"],
            "chain_super": counts["chain_super"],
            "market_face": sum(
                record.family == "market_face" for record in self.records.values()
            ),
            "observed_faces": sum(bool(value) for value in self.observations.values()),
        }

    def observe_market_face(
        self,
        emoji_id: str,
        name: str,
        package_id: str = "",
        key: str = "",
    ) -> FaceRecord:
        face_id = str(emoji_id).strip()
        if not face_id:
            raise ValueError("market face emoji_id must not be empty")
        existing = self.get(face_id, "market_face")
        display_name = str(name).strip() or (
            existing.canonical_name if existing else "未知商城表情"
        )
        if existing:
            changed = False
            if (
                display_name != "未知商城表情"
                and existing.canonical_name != display_name
            ):
                existing.canonical_name = display_name
                existing.literal_description = display_name
                changed = True
            if key and key not in existing.aliases:
                existing.aliases.append(key)
                changed = True
            if package_id and existing.pack_id != package_id:
                existing.pack_id = package_id
                changed = True
            if not changed:
                return existing
            record = existing
        else:
            record = FaceRecord(
                family="market_face",
                id=face_id,
                canonical_name=display_name,
                literal_description=display_name,
                aliases=[key] if key else [],
                face_kind="market",
                pack_id=str(package_id),
                sendable=False,
                source="observed_onebot_mface",
                confidence=0.8,
                updated_at=datetime.now().astimezone().isoformat(),
            )
            self.records[record.key] = record
        market_records = [
            item.to_dict()
            for item in self.records.values()
            if item.family == "market_face" and item.source == "observed_onebot_mface"
        ]
        _atomic_json(
            self.market_faces_path,
            {"schema_version": 1, "faces": market_records},
        )
        return record

    def search(
        self,
        query: str,
        *,
        tone: str = "",
        family: str = "",
        kind: str = "",
        hidden: str = "any",
        chain_role: str = "",
        limit: int = 5,
    ) -> list[FaceRecord]:
        query_terms = [
            term for term in re.findall(r"[\w\u4e00-\u9fff]+", query.lower()) if term
        ]
        tone_term = tone.strip().lower()
        has_structured_filter = bool(kind or hidden != "any" or chain_role)
        scored: list[tuple[int, float, FaceRecord]] = []
        for record in self.records.values():
            if family and record.family != family:
                continue
            if kind and record.face_kind != kind:
                continue
            if hidden == "hidden" and not record.hidden:
                continue
            if hidden == "visible" and record.hidden:
                continue
            if chain_role and record.chain_role != chain_role:
                continue
            haystack = " ".join(
                (
                    record.searchable_text(),
                    FACE_KIND_ALIASES.get(record.face_kind, ""),
                    "隐藏 hidden" if record.hidden else "可见 visible",
                    CHAIN_ROLE_ALIASES.get(record.chain_role, ""),
                )
            ).lower()
            learned = " ".join(
                str(item.get("meaning", ""))
                for item in self.observations.get(record.key, [])
                if item.get("status") == "active"
            ).lower()
            score = sum(
                6
                if term == record.id
                else 4
                if term in record.canonical_name.lower()
                else 2
                if term in learned
                else 1
                for term in query_terms
                if term in haystack or term in learned
            )
            if tone_term and tone_term in " ".join(record.tone).lower():
                score += 3
            if score or (not query_terms and has_structured_filter):
                scored.append((score, record.confidence, record))
        scored.sort(
            key=lambda item: (
                -item[0],
                -item[1],
                int(item[2].id) if item[2].id.isdigit() else 10**9,
            )
        )
        return [item[2] for item in scored[: max(1, min(limit, 20))]]

    def add_observation(self, face_key: str, observation: dict[str, Any]) -> bool:
        if face_key not in self.records:
            return False
        meaning = str(observation.get("meaning", "")).strip()
        if not meaning:
            return False
        try:
            confidence = float(observation.get("confidence", 0.0))
            evidence_count = int(observation.get("evidence_count", 1))
        except (TypeError, ValueError):
            confidence, evidence_count = 0.0, 1
        clean = {
            "meaning": meaning,
            "tone": _as_strings(observation.get("tone")),
            "usage_context": str(observation.get("usage_context", "")).strip(),
            "avoid_context": str(observation.get("avoid_context", "")).strip(),
            "confidence": max(0.0, min(1.0, confidence)),
            "evidence_count": max(1, evidence_count),
            "status": str(observation.get("status", "active")),
            "source": "nightly_learning",
            "updated_at": datetime.now().astimezone().isoformat(),
        }
        current = self.observations.setdefault(face_key, [])
        for item in current:
            if item.get("meaning") == meaning:
                item.update(clean)
                self.save_observations()
                return True
        current.append(clean)
        self.save_observations()
        return True

    def apply_learning_proposal(self, proposal: dict[str, Any]) -> bool:
        face_key = str(proposal.get("face_key", ""))
        if face_key not in self.records:
            return False
        action = str(proposal.get("action", "upsert")).lower()
        meaning = str(proposal.get("meaning", "")).strip()
        changed = False
        if action == "upsert":
            changed = self.add_observation(face_key, proposal)
        elif action in {"deprecate", "delete"} and meaning:
            current = self.observations.get(face_key, [])
            for item in current:
                if item.get("meaning") == meaning:
                    if action == "delete":
                        current.remove(item)
                    else:
                        item["status"] = "deprecated"
                        item["updated_at"] = datetime.now().astimezone().isoformat()
                    changed = True
                    break
            if changed:
                self.save_observations()
        if changed:
            audit = {
                "at": datetime.now().astimezone().isoformat(),
                "face_key": face_key,
                "action": action,
                "meaning": meaning,
                "source": "nightly_learning",
            }
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(audit, ensure_ascii=False) + "\n")
        return changed

    def display(self, record: FaceRecord) -> dict[str, Any]:
        result = record.to_dict()
        result["learned_observations"] = [
            item
            for item in self.observations.get(record.key, [])
            if item.get("status") == "active"
        ][:8]
        return result


def find_napcat_face_configs(
    max_results: int = 12,
    extra_roots: Iterable[Path] = (),
    include_system_roots: bool = True,
) -> list[Path]:
    """Search likely Windows NapCat roots with bounded depth and result count."""
    roots: list[Path] = [Path(root) for root in extra_roots]
    if include_system_roots:
        for env_name in ("NAPCAT_HOME", "NAPCAT_ROOT"):
            value = os.environ.get(env_name)
            if value:
                roots.append(Path(value))
        for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            value = os.environ.get(env_name)
            if value:
                base = Path(value)
                roots.extend(
                    (base / "NapCat", base / "NapCatQQ", base / "Programs" / "NapCat")
                )
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            home = Path(user_profile)
            roots.extend(
                (
                    home / "NapCat",
                    home / "Desktop" / "NapCat",
                    home / "Downloads" / "NapCat",
                )
            )
        for drive in ("C:/", "D:/"):
            for name in (
                "NapCat",
                "NapCatQQ",
                "QQ",
                "Program Files/NapCat",
                "Program Files/NapCatQQ",
            ):
                roots.append(Path(drive) / name)

    results: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.expanduser().resolve()
        except OSError:
            continue
        key = os.path.normcase(str(resolved))
        if key in seen or not resolved.exists() or not resolved.is_dir():
            continue
        seen.add(key)
        direct_candidates = (
            resolved / "face_config.json",
            resolved
            / "resources"
            / "app"
            / "napcat"
            / "napcat"
            / "core"
            / "external"
            / "face_config.json",
            resolved / "packages" / "napcat-core" / "external" / "face_config.json",
            resolved / "napcat" / "core" / "external" / "face_config.json",
        )
        for candidate in direct_candidates:
            if candidate.is_file() and candidate not in results:
                results.append(candidate.resolve())
                if len(results) >= max_results:
                    return results
        try:
            for candidate in resolved.glob("*/*/external/face_config.json"):
                if candidate.is_file() and candidate.resolve() not in results:
                    results.append(candidate.resolve())
                    if len(results) >= max_results:
                        return results
        except OSError:
            continue
    return results
