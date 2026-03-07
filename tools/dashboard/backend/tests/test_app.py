from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


class _FakeRuntime:
    def __init__(self, state: str = "running", running: bool = True) -> None:
        self.state = state
        self.running = running

    def collect(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "running": self.running,
            "pid": "12345",
            "label": "test.label",
            "checked_at": "2026-02-17T00:00:00",
        }


def _bootstrap_module(tmp_path: Path, root: Path) -> Any:
    env_runtime = _FakeRuntime()
    import os

    os.environ["DASHBOARD_PROJECT_ROOT"] = str(root)
    os.environ["DASHBOARD_DATA_DIR"] = str(tmp_path)
    os.environ["DASHBOARD_RUNTIME_LABEL"] = "test.label"

    module = importlib.reload(importlib.import_module("tools.dashboard.backend.app"))
    module.runtime_service = env_runtime
    return module


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_health_with_missing_files_and_corrupt_lines(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[4]
    module = _bootstrap_module(tmp_path, root)
    module.runtime_service = _FakeRuntime("running", True)

    # create one file only, include one malformed line.
    for file_name in module.files.values():
        (tmp_path / file_name).unlink(missing_ok=True)
    (tmp_path / module.files["ops_events"]).write_text("{bad json\n", encoding="utf-8")

    with TestClient(module.app) as client:
        response = client.get("/api/health")
    data = response.json()
    assert response.status_code == 200
    assert data["data_missing"] is True
    assert data["jsonl_ok"] is False
    assert data["corrupt_lines"] >= 1
    assert data["runtime_state"]["state"] == "running"


def test_warrooms_sorted_latest_and_status_filter(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[4]
    module = _bootstrap_module(tmp_path, root)
    module.runtime_service = _FakeRuntime("running", True)

    _write_jsonl(
        tmp_path / module.files["warrooms"],
        [
            {"warroom_id": "w1", "name": "old", "state": "active", "zone": "core", "last_activity_at": "2026-02-16T01:00:00Z", "text_channel_id": 11, "voice_channel_id": 12},
            {"warroom_id": "w2", "name": "new", "state": "active", "zone": "product", "last_activity_at": "2026-02-16T03:00:00Z", "text_channel_id": 21, "voice_channel_id": 22},
            {"warroom_id": "w3", "name": "arch", "state": "archived", "zone": "growth", "last_activity_at": "2026-02-16T02:00:00Z", "text_channel_id": 31, "voice_channel_id": 32},
        ],
    )
    _write_jsonl(tmp_path / module.files["decisions"], [])
    _write_jsonl(tmp_path / module.files["summaries"], [])
    _write_jsonl(tmp_path / module.files["ops_events"], [])

    with TestClient(module.app) as client:
        response = client.get("/api/warrooms", params={"status": "active", "limit": 2})
    assert response.status_code == 200

    rows = response.json()["rows"]
    assert rows[0]["name"] == "new"
    assert rows[1]["name"] == "old"


def test_events_limit_and_metrics(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[4]
    module = _bootstrap_module(tmp_path, root)
    module.runtime_service = _FakeRuntime("running", True)
    now = datetime.now(timezone.utc).replace(microsecond=0)

    _write_jsonl(tmp_path / module.files["decisions"], [])
    _write_jsonl(tmp_path / module.files["summaries"], [])
    _write_jsonl(
        tmp_path / module.files["ops_events"],
        [
            {
                "event_type": "warroom_auto_archived",
                "occurred_at": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
                "payload": {"archived": 1},
            },
            {
                "event_type": "warroom_inactive_warning",
                "occurred_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                "payload": {},
            },
        ],
    )
    _write_jsonl(
        tmp_path / module.files["warrooms"],
        [{"warroom_id": "w", "name": "x", "state": "active", "last_activity_at": "2026-02-16T00:00:00Z"}],
    )

    with TestClient(module.app) as client:
        response = client.get("/api/events", params={"event_type": "all", "limit": 1})
    assert response.status_code == 200
    assert response.json()["rows"][0]["event_type"] == "warroom_inactive_warning"

    with TestClient(module.app) as client2:
        metric = client2.get("/api/metrics/quick", params={"hours": 24}).json()
    assert metric["warnings"] == 2
    assert metric["summaries"] == 0


def test_curation_overview_counts_and_recent(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[4]
    module = _bootstrap_module(tmp_path, root)
    module.runtime_service = _FakeRuntime("running", True)

    _write_jsonl(
        tmp_path / module.files["curation_submissions"],
        [
            {
                "submission_id": "s1",
                "status": "pending",
                "classified_type": "link",
                "normalized_title": "[LINK] a",
                "created_at": "2026-02-16T01:00:00Z",
            },
            {
                "submission_id": "s1",
                "status": "approved",
                "classified_type": "link",
                "normalized_title": "[LINK] a",
                "created_at": "2026-02-16T02:00:00Z",
            },
            {
                "submission_id": "s2",
                "status": "rejected",
                "classified_type": "idea",
                "normalized_title": "[IDEA] b",
                "created_at": "2026-02-16T03:00:00Z",
            },
        ],
    )
    _write_jsonl(
        tmp_path / module.files["curation_posts"],
        [
            {
                "post_id": "p1",
                "submission_id": "s1",
                "target_channel_id": 123,
                "target_message_id": 456,
                "published_at": "2026-02-16T02:30:00Z",
            }
        ],
    )
    _write_jsonl(tmp_path / module.files["decisions"], [])
    _write_jsonl(tmp_path / module.files["summaries"], [])
    _write_jsonl(tmp_path / module.files["warrooms"], [])
    _write_jsonl(tmp_path / module.files["ops_events"], [])

    with TestClient(module.app) as client:
        response = client.get("/api/curation/overview", params={"limit": 10})
    assert response.status_code == 200
    data = response.json()
    assert data["counts"]["total"] == 2
    assert data["counts"]["approved"] == 1
    assert data["counts"]["rejected"] == 1
    assert len(data["submissions"]) == 2
    assert len(data["posts"]) == 1


def test_ops_overview_cards_and_failures(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[4]
    module = _bootstrap_module(tmp_path, root)
    module.runtime_service = _FakeRuntime("running", True)

    _write_jsonl(
        tmp_path / module.files["news_digests"],
        [{"digest_id": "d1", "run_at": "2026-03-07T08:00:00Z", "items_count": 10}],
    )
    _write_jsonl(
        tmp_path / module.files["curation_submissions"],
        [{"submission_id": "s1", "status": "pending", "classified_type": "link", "created_at": "2026-03-07T07:00:00Z"}],
    )
    _write_jsonl(
        tmp_path / module.files["ops_events"],
        [
            {
                "event_type": "news_digest_completed",
                "occurred_at": "2026-03-07T08:01:00Z",
                "payload": {"errors": 0},
            },
            {
                "event_type": "music_command_failed",
                "occurred_at": "2026-03-07T08:05:00Z",
                "payload": {"command_name": "music_play", "error": "ffmpeg_missing"},
            },
        ],
    )
    _write_jsonl(tmp_path / module.files["decisions"], [])
    _write_jsonl(tmp_path / module.files["summaries"], [])
    _write_jsonl(tmp_path / module.files["warrooms"], [])
    _write_jsonl(tmp_path / module.files["curation_posts"], [])

    with TestClient(module.app) as client:
        response = client.get("/api/ops/overview", params={"limit": 5})
    assert response.status_code == 200
    data = response.json()
    assert "news" in data["cards"]
    assert "curation" in data["cards"]
    assert data["cards"]["news"]["last_result"] == "ok"
    assert data["recent_failures"][0]["event_type"] == "music_command_failed"
