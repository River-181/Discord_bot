from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import time
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ReadBundle:
    rows: list[dict[str, Any]]
    corrupt_lines: int
    data_missing: bool


class DashboardDataService:
    def __init__(
        self,
        data_dir: Path,
        file_map: dict[str, str],
        timezone_name: str,
        cache_ttl_seconds: int = 5,
    ) -> None:
        self.data_dir = data_dir
        self.file_map = file_map
        self.cache_ttl_seconds = cache_ttl_seconds
        self.tz = ZoneInfo(timezone_name)
        self._cache: dict[str, tuple[float, ReadBundle]] = {}

    def refresh(self) -> None:
        self._cache.clear()

    def _path(self, kind: str) -> Path:
        filename = self.file_map.get(kind)
        if not filename:
            raise ValueError(f"Unknown data kind: {kind}")
        path = self.data_dir / filename
        return path

    def parse_iso_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                match = re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value)
                if match:
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                else:
                    return None
        else:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(self.tz)

    def format_local_iso(self, value: Any) -> str | None:
        parsed = self.parse_iso_datetime(value)
        if parsed is None:
            return None
        return parsed.isoformat(timespec="seconds")

    def _read_file(self, path: Path) -> ReadBundle:
        if not path.exists():
            return ReadBundle(rows=[], corrupt_lines=0, data_missing=True)

        rows: list[dict[str, Any]] = []
        corrupt_lines = 0
        with path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    corrupt_lines += 1
                    continue

        return ReadBundle(rows=rows, corrupt_lines=corrupt_lines, data_missing=False)

    def read(self, kind: str) -> ReadBundle:
        path = self._path(kind)
        cache_key = str(path)

        now = time()
        cached = self._cache.get(cache_key)
        if cached and now - cached[0] < self.cache_ttl_seconds:
            return cached[1]

        bundle = self._read_file(path)
        self._cache[cache_key] = (now, bundle)
        return bundle

    def _sort_records(self, rows: list[dict[str, Any]], ts_key: str) -> list[dict[str, Any]]:
        def _key(row: dict[str, Any]) -> tuple[float, str]:
            dt = row.get(ts_key)
            parsed = self.parse_iso_datetime(dt)
            if parsed is None:
                return (0.0, str(dt or ""))
            return (parsed.timestamp(), parsed.isoformat())

        return sorted(rows, key=_key, reverse=True)

    @staticmethod
    def _dedupe_latest(rows: list[dict[str, Any]], key: str = "warroom_id") -> list[dict[str, Any]]:
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for row in rows:
            raw_id = row.get(key) or row.get("id")
            if raw_id is None:
                deduped.append(row)
                continue

            row_id = str(raw_id)
            if row_id in seen:
                continue
            seen.add(row_id)
            deduped.append(row)
        return deduped

    def list_decisions(self, status: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        bundle = self.read("decisions")
        rows = list(bundle.rows)
        if status != "all":
            filtered = []
            open_statuses = {"open", "진행", "진행중", "대기"}
            closed_statuses = {"closed", "done", "완료", "resolved"}
            for row in rows:
                row_status = str(row.get("status") or "open").strip().lower()
                if status == "open" and row_status not in open_statuses:
                    continue
                if status == "closed" and row_status not in closed_statuses:
                    continue
                filtered.append(row)
            rows = filtered

        sorted_rows = self._sort_records(rows, "created_at")
        return sorted_rows[:limit]

    def list_summaries(self, scope: str = "all", limit: int = 50) -> list[dict[str, Any]]:
        bundle = self.read("summaries")
        rows = list(bundle.rows)
        if scope != "all":
            rows = [row for row in rows if str(row.get("scope", "")).lower() == scope.lower()]
        sorted_rows = self._sort_records(rows, "created_at")
        return sorted_rows[:limit]

    def list_warrooms(self, status: str = "all") -> list[dict[str, Any]]:
        bundle = self.read("warrooms")
        rows = self._sort_records(list(bundle.rows), "last_activity_at")
        rows = self._dedupe_latest(rows, key="warroom_id")
        if status != "all":
            rows = [row for row in rows if str(row.get("state", "")).lower() == status.lower()]
        return rows

    def list_events(self, event_type: str = "all", limit: int = 200) -> list[dict[str, Any]]:
        bundle = self.read("ops_events")
        rows = list(bundle.rows)
        if event_type != "all":
            if event_type == "error":
                rows = [row for row in rows if "error" in str(row.get("event_type", "")).lower()]
            elif event_type == "warning":
                rows = [
                    row
                    for row in rows
                    if str(row.get("event_type", "")).lower() in {
                        "warroom_inactive_warning",
                        "warroom_auto_archived",
                    }
                ]
            elif event_type == "scheduled_inactivity_scan":
                rows = [row for row in rows if row.get("event_type") == event_type]
            else:
                rows = [row for row in rows if row.get("event_type") == event_type]
        sorted_rows = self._sort_records(rows, "occurred_at")
        return sorted_rows[:limit]

    def get_bundle(self, kind: str) -> ReadBundle:
        return self.read(kind)
