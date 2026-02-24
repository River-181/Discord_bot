from __future__ import annotations

import json
import shutil
from asyncio import Lock
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class DataFiles:
    decisions: str
    warrooms: str
    summaries: str
    ops_events: str
    news_items: str
    news_digests: str
    snapshots_dir: str
    curation_submissions: str = "curation_submissions.jsonl"
    curation_posts: str = "curation_posts.jsonl"


class StorageService:
    def __init__(self, base_dir: Path, files: DataFiles) -> None:
        self.base_dir = base_dir
        self.files = files
        self._lock = Lock()
        self._idempotency_keys: set[str] = set()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._bootstrap_files()
        self._load_idempotency_keys()

    def _bootstrap_files(self) -> None:
        for path in self._all_data_paths():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def _all_data_paths(self) -> list[Path]:
        return [
            self.decisions_path,
            self.warrooms_path,
            self.summaries_path,
            self.ops_events_path,
            self.news_items_path,
            self.news_digests_path,
            self.curation_submissions_path,
            self.curation_posts_path,
        ]

    def _load_idempotency_keys(self) -> None:
        for row in self.read_jsonl_path(self.ops_events_path):
            key = row.get("idempotency_key")
            if key:
                self._idempotency_keys.add(str(key))

    @property
    def decisions_path(self) -> Path:
        return self.base_dir / self.files.decisions

    @property
    def warrooms_path(self) -> Path:
        return self.base_dir / self.files.warrooms

    @property
    def summaries_path(self) -> Path:
        return self.base_dir / self.files.summaries

    @property
    def ops_events_path(self) -> Path:
        return self.base_dir / self.files.ops_events

    @property
    def news_items_path(self) -> Path:
        return self.base_dir / self.files.news_items

    @property
    def news_digests_path(self) -> Path:
        return self.base_dir / self.files.news_digests

    @property
    def snapshot_dir(self) -> Path:
        return self.base_dir / self.files.snapshots_dir

    @property
    def curation_submissions_path(self) -> Path:
        return self.base_dir / self.files.curation_submissions

    @property
    def curation_posts_path(self) -> Path:
        return self.base_dir / self.files.curation_posts

    def _timestamp(self) -> str:
        return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    def read_jsonl_path(self, path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    # Corrupted line is ignored to isolate read failure.
                    continue
        return rows

    def read_jsonl(self, kind: str) -> list[dict[str, Any]]:
        return self.read_jsonl_path(self._path_for_kind(kind))

    def _path_for_kind(self, kind: str) -> Path:
        mapping = {
            "decisions": self.decisions_path,
            "warrooms": self.warrooms_path,
            "summaries": self.summaries_path,
            "ops_events": self.ops_events_path,
            "news_items": self.news_items_path,
            "news_digests": self.news_digests_path,
            "curation_submissions": self.curation_submissions_path,
            "curation_posts": self.curation_posts_path,
        }
        if kind not in mapping:
            raise ValueError(f"Unsupported kind: {kind}")
        return mapping[kind]

    async def append_jsonl(self, kind: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            path = self._path_for_kind(kind)
            line = json.dumps(payload, ensure_ascii=False)
            with path.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")

    async def append_decision(self, payload: dict[str, Any]) -> None:
        if "created_at" not in payload:
            payload["created_at"] = self._timestamp()
        await self.append_jsonl("decisions", payload)

    async def append_warroom(self, payload: dict[str, Any]) -> None:
        if "event_at" not in payload:
            payload["event_at"] = self._timestamp()
        await self.append_jsonl("warrooms", payload)

    async def append_summary(self, payload: dict[str, Any]) -> None:
        if "created_at" not in payload:
            payload["created_at"] = self._timestamp()
        await self.append_jsonl("summaries", payload)

    async def append_news_item(self, payload: dict[str, Any]) -> None:
        if "fetched_at" not in payload:
            payload["fetched_at"] = self._timestamp()
        await self.append_jsonl("news_items", payload)

    async def append_news_digest(self, payload: dict[str, Any]) -> None:
        if "run_at" not in payload:
            payload["run_at"] = self._timestamp()
        await self.append_jsonl("news_digests", payload)

    async def append_curation_submission(self, payload: dict[str, Any]) -> None:
        if "created_at" not in payload:
            payload["created_at"] = self._timestamp()
        await self.append_jsonl("curation_submissions", payload)

    async def append_curation_post(self, payload: dict[str, Any]) -> None:
        if "published_at" not in payload:
            payload["published_at"] = self._timestamp()
        await self.append_jsonl("curation_posts", payload)

    async def append_ops_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> bool:
        async with self._lock:
            if idempotency_key and idempotency_key in self._idempotency_keys:
                return False
            row = {
                "event_type": event_type,
                "occurred_at": self._timestamp(),
                "payload": payload,
            }
            if idempotency_key:
                row["idempotency_key"] = idempotency_key
                self._idempotency_keys.add(idempotency_key)
            line = json.dumps(row, ensure_ascii=False)
            with self.ops_events_path.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")
            return True

    def has_idempotency_key(self, key: str) -> bool:
        return key in self._idempotency_keys

    def latest_by_key(
        self,
        kind: str,
        key: str,
        key_filter: callable | None = None,
    ) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self.read_jsonl(kind):
            item_key = row.get(key)
            if item_key is None:
                continue
            item_key = str(item_key)
            if key_filter and not key_filter(row):
                continue
            latest[item_key] = row
        return latest

    def all_latest_warrooms(self) -> list[dict[str, Any]]:
        by_id = self.latest_by_key("warrooms", "warroom_id")
        return list(by_id.values())

    def active_warrooms(self) -> list[dict[str, Any]]:
        return [x for x in self.all_latest_warrooms() if x.get("state") == "active"]

    def snapshots(self) -> Iterable[Path]:
        return sorted(self.snapshot_dir.glob("*"))

    async def create_daily_snapshot(self, day_key: str | None = None) -> Path:
        async with self._lock:
            day_key = day_key or datetime.now(UTC).strftime("%Y-%m-%d")
            dest_dir = self.snapshot_dir / day_key
            dest_dir.mkdir(parents=True, exist_ok=True)
            for src in self._all_data_paths():
                if src.exists():
                    shutil.copy2(src, dest_dir / src.name)
            return dest_dir
