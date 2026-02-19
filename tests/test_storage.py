from __future__ import annotations

import asyncio
from pathlib import Path

from bot.services.storage import DataFiles, StorageService


def _make_storage(tmp_path: Path) -> StorageService:
    files = DataFiles(
        decisions="decisions.jsonl",
        warrooms="warrooms.jsonl",
        summaries="summaries.jsonl",
        ops_events="ops_events.ndjson",
        news_items="news_items.jsonl",
        news_digests="news_digests.jsonl",
        snapshots_dir="snapshots",
    )
    return StorageService(base_dir=tmp_path, files=files)


def test_append_and_latest(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)

    async def _run() -> None:
        await storage.append_warroom({"warroom_id": "w1", "state": "active", "name": "a"})
        await storage.append_warroom({"warroom_id": "w1", "state": "archived", "name": "a"})

    asyncio.run(_run())

    rows = storage.read_jsonl("warrooms")
    assert len(rows) == 2
    latest = storage.all_latest_warrooms()
    assert len(latest) == 1
    assert latest[0]["state"] == "archived"


def test_idempotency(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)

    async def _run() -> tuple[bool, bool]:
        first = await storage.append_ops_event("x", {"a": 1}, idempotency_key="k1")
        second = await storage.append_ops_event("x", {"a": 2}, idempotency_key="k1")
        return first, second

    first, second = asyncio.run(_run())
    assert first is True
    assert second is False
