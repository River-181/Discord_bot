from __future__ import annotations

from pathlib import Path

from tools.dashboard.backend.services.jsonl_reader import DashboardDataService


def _service(tmp_path: Path) -> DashboardDataService:
    file_map = {
        "decisions": "decisions.jsonl",
        "warrooms": "warrooms.jsonl",
        "summaries": "summaries.jsonl",
        "ops_events": "ops_events.ndjson",
    }
    for name in file_map.values():
        (tmp_path / name).touch()

    return DashboardDataService(
        data_dir=tmp_path,
        file_map=file_map,
        timezone_name="Asia/Seoul",
    )


def test_jsonl_reader_filter_sort_and_corrupt_lines(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with (tmp_path / "decisions.jsonl").open("w", encoding="utf-8") as fp:
        fp.write('{"decision_id":"d1","status":"open","created_at":"2026-02-16T01:00:00Z"}\n')
        fp.write('{"decision_id":"d2","status":"done","created_at":"2026-02-16T02:00:00Z"}\n')
        fp.write('bad json line\n')

    with (tmp_path / "summaries.jsonl").open("w", encoding="utf-8") as fp:
        fp.write('{"summary_id":"s1","scope":"thread","created_at":"2026-02-16T01:00:00Z"}\n')
        fp.write('{"summary_id":"s2","scope":"channel","created_at":"2026-02-16T03:00:00Z"}\n')

    with (tmp_path / "warrooms.jsonl").open("w", encoding="utf-8") as fp:
        fp.write('{"warroom_id":"w1","state":"archived","name":"A","last_activity_at":"2026-02-15T00:00:00Z"}\n')
        fp.write('{"warroom_id":"w2","state":"active","name":"B","last_activity_at":"2026-02-16T02:00:00Z"}\n')

    with (tmp_path / "ops_events.ndjson").open("w", encoding="utf-8") as fp:
        fp.write('{"event_type":"warroom_auto_archived","occurred_at":"2026-02-16T03:00:00Z","payload":{}}\n')

    open_rows = service.list_decisions("open", limit=10)
    assert len(open_rows) == 1
    assert open_rows[0]["decision_id"] == "d1"

    closed_rows = service.list_decisions("closed", limit=10)
    assert len(closed_rows) == 1
    assert closed_rows[0]["decision_id"] == "d2"

    summary_channel = service.list_summaries("channel", limit=10)
    assert len(summary_channel) == 1
    assert summary_channel[0]["summary_id"] == "s2"

    warrooms_active = service.list_warrooms("active")
    assert len(warrooms_active) == 1
    assert warrooms_active[0]["name"] == "B"

    bundle = service.get_bundle("decisions")
    assert bundle.corrupt_lines == 1
    assert not bundle.data_missing


def test_parse_iso_datetime(tmp_path: Path) -> None:
    service = _service(tmp_path)
    dt = service.parse_iso_datetime("2026-02-16T12:30:00+00:00")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.tzinfo.key == "Asia/Seoul"


def test_warroom_latest_only(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with (tmp_path / "warrooms.jsonl").open("w", encoding="utf-8") as fp:
        fp.write('{"warroom_id":"w1","state":"active","name":"A","last_activity_at":"2026-02-16T01:00:00Z"}\n')
        fp.write('{"warroom_id":"w1","state":"archived","name":"A","last_activity_at":"2026-02-16T02:00:00Z"}\n')
        fp.write('{"warroom_id":"w1","state":"active","name":"A","last_activity_at":"2026-02-16T03:00:00Z"}\n')

    rows = service.list_warrooms("all")
    assert len(rows) == 1
    assert rows[0]["state"] == "active"
    assert rows[0]["last_activity_at"] == "2026-02-16T03:00:00Z"


def test_timestamp_sort_desc(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with (tmp_path / "decisions.jsonl").open("w", encoding="utf-8") as fp:
        fp.write('{"decision_id":"d1","created_at":"2026-02-16T10:59:00+00:00","status":"open"}\n')
        fp.write('{"decision_id":"d2","created_at":"2026-02-16T11:10:00+00:00","status":"open"}\n')

    rows = service.list_decisions("all")
    assert rows[0]["decision_id"] == "d2"
