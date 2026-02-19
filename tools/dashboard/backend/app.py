from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import os

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi import Request

from tools.dashboard.backend.services.jsonl_reader import DashboardDataService
from tools.dashboard.backend.services.runtime import RuntimeStateService


def _project_root() -> Path:
    return Path(os.getenv("DASHBOARD_PROJECT_ROOT") or Path(__file__).resolve().parents[3])


def _load_yaml(root_dir: Path) -> dict[str, Any]:
    settings_path = root_dir / "config" / "settings.yaml"
    if not settings_path.exists():
        return {}
    with settings_path.open("r", encoding="utf-8") as fp:
        payload = yaml.safe_load(fp)
    return payload if isinstance(payload, dict) else {}


def _to_local_iso(data_service: DashboardDataService, value: Any) -> str | None:
    return data_service.format_local_iso(value)


def _normalize_decision_status(raw: Any) -> str:
    status = str(raw or "open").strip().lower()
    if status in {"open", "진행", "진행중", "진행 중", "in_progress"}:
        return "open"
    if status in {"closed", "resolved", "done", "완료", "종료", "closed+"}:
        return "closed"
    return status


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _within_window(iso_value: Any, since: datetime, data_service: DashboardDataService) -> bool:
    dt = data_service.parse_iso_datetime(iso_value)
    if dt is None:
        return False
    return dt >= since


def _is_open_status(raw_status: Any) -> bool:
    return str(raw_status or "open").strip().lower() in {"open", "진행", "진행중", "진행 중", "in_progress", "대기"}


def _is_closed_status(raw_status: Any) -> bool:
    return str(raw_status or "").strip().lower() in {"closed", "resolved", "done", "완료", "종료"}


root_dir = _project_root()
load_dotenv(root_dir / ".env")
settings = _load_yaml(root_dir)

data_config = settings.get("data", {}) if isinstance(settings, dict) else {}
app_config = settings.get("app", {}) if isinstance(settings, dict) else {}
warroom_config = settings.get("warroom", {}) if isinstance(settings, dict) else {}

timezone_name = os.getenv("TZ") or str(app_config.get("timezone", "Asia/Seoul"))

target_guild_id = os.getenv("TARGET_GUILD_ID")
if not target_guild_id:
    env_target = app_config.get("target_guild_id")
    if env_target is not None:
        target_guild_id = str(env_target)

raw_data_dir = os.getenv("DASHBOARD_DATA_DIR")
if raw_data_dir:
    data_dir = Path(raw_data_dir)
    if not data_dir.is_absolute():
        data_dir = (root_dir / data_dir).resolve()
else:
    base = data_config.get("base_dir", "./data")
    data_dir = Path(base)
    if not data_dir.is_absolute():
        data_dir = (root_dir / data_dir).resolve()

files = {
    "decisions": str(data_config.get("decisions_file", "decisions.jsonl")),
    "warrooms": str(data_config.get("warrooms_file", "warrooms.jsonl")),
    "summaries": str(data_config.get("summaries_file", "summaries.jsonl")),
    "ops_events": str(data_config.get("ops_events_file", "ops_events.ndjson")),
}

runtime_label = os.getenv("DASHBOARD_RUNTIME_LABEL", "com.mangsang.orbit.assistant")


data_service = DashboardDataService(
    data_dir=data_dir,
    file_map=files,
    timezone_name=timezone_name,
)
runtime_service = RuntimeStateService(label=runtime_label)


def _runtime_payload() -> dict[str, Any]:
    return runtime_service.collect()


def _missing_files() -> list[str]:
    return [filename for filename in files.values() if not (data_dir / filename).exists()]


def _collect_corrupt_lines() -> int:
    total = 0
    for kind in files:
        total += data_service.get_bundle(kind).corrupt_lines
    return total


def _build_warnings_summary() -> dict[str, int]:
    now_local = datetime.now(data_service.tz)
    since_24h = now_local - timedelta(hours=24)

    warning_count = 0
    archive_count = 0
    error_count = 0

    for row in data_service.list_events("all", limit=500):
        event_type = str(row.get("event_type", "")).lower()
        dt = data_service.parse_iso_datetime(row.get("occurred_at"))
        if dt is None or dt < since_24h:
            continue

        if event_type == "warroom_inactive_warning":
            warning_count += 1
            continue
        if event_type == "warroom_auto_archived":
            archive_count += 1
            continue
        if event_type == "scheduled_inactivity_scan":
            payload = row.get("payload", {})
            if isinstance(payload, dict):
                warning_count += _safe_int(payload.get("warnings"))
                archive_count += _safe_int(payload.get("archived"))

        if "error" in event_type:
            error_count += 1

    return {
        "warnings": warning_count,
        "archived": archive_count,
        "errors": error_count,
    }


def _pending_decisions(limit: int = 3) -> list[dict[str, Any]]:
    rows = [
        row
        for row in data_service.list_decisions("all", limit=limit * 3)
        if _is_open_status(row.get("status"))
    ]
    return [
        {
            "decision_id": row.get("decision_id") or row.get("id"),
            "title": row.get("summary") or row.get("title") or "(제목 없음)",
            "owner": row.get("owner") or "-",
            "due_date": row.get("due_date"),
            "status": _normalize_decision_status(row.get("status")),
            "source_channel_id": row.get("source_channel_id"),
            "context_url": row.get("context_url"),
            "created_at": _to_local_iso(data_service, row.get("created_at")),
        }
        for row in rows[:limit]
    ]


app = FastAPI(title="망상궤도 비서 운영대시보드", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    runtime = _runtime_payload()
    missing = _missing_files()
    missing_count = len(missing)
    corrupt_lines = _collect_corrupt_lines()

    jsonl_ok = missing_count == 0 and corrupt_lines == 0

    return {
        "ok": runtime.get("state") == "running",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "runtime_state": {
            "state": runtime.get("state"),
            "running": runtime.get("running"),
        },
        "data_dir_exists": data_dir.exists(),
        "data_missing": missing_count > 0,
        "missing_files": missing,
        "jsonl_ok": jsonl_ok,
        "corrupt_lines": corrupt_lines,
    }


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    runtime = _runtime_payload()
    counts = _build_warnings_summary()
    warrooms = data_service.list_warrooms("all")

    return {
        "bot_state": {
            "status": runtime.get("state"),
            "running": runtime.get("running"),
            "checked_at": runtime.get("checked_at"),
            "pid": runtime.get("pid"),
            "label": runtime.get("label"),
        },
        "recent_24h": counts,
        "active_warrooms": len([x for x in warrooms if str(x.get("state", "")).lower() == "active"]),
        "recent_unresolved_decisions": _pending_decisions(limit=3),
        "target_guild_id": target_guild_id,
    }


@app.get("/api/warrooms")
def warrooms(
    status: str = Query("all", pattern="^(all|active|archived)$"),
    limit: int = Query(100, ge=1, le=300),
) -> dict[str, Any]:
    rows = data_service.list_warrooms(status=status)
    warning_days = int(warroom_config.get("warning_days", 14)) if isinstance(warroom_config, dict) else 14

    payload: list[dict[str, Any]] = []
    for row in rows[:limit]:
        last_activity = row.get("last_activity_at")
        warning_at: str | None = None

        if str(row.get("state", "")).lower() == "active":
            last_dt = data_service.parse_iso_datetime(last_activity)
            if last_dt is not None:
                warning_at = (last_dt + timedelta(days=warning_days)).isoformat(timespec="seconds")

        payload.append(
            {
                "warroom_id": row.get("warroom_id") or row.get("id"),
                "name": row.get("name"),
                "zone": row.get("zone"),
                "state": str(row.get("state") or "unknown").lower(),
                "last_activity_at": _to_local_iso(data_service, last_activity),
                "warning_at": warning_at,
                "archived_at": _to_local_iso(data_service, row.get("archived_at")),
                "text_channel_id": row.get("text_channel_id"),
                "voice_channel_id": row.get("voice_channel_id"),
            }
        )

    return {
        "rows": payload,
        "count": len(payload),
        "limit": limit,
        "status": status,
    }


@app.get("/api/summaries")
def summaries(
    scope: str = Query("all", pattern="^(all|thread|channel)$"),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    rows = data_service.list_summaries(scope=scope, limit=limit)
    response_rows = [
        {
            "summary_id": row.get("summary_id"),
            "scope": row.get("scope") or "unknown",
            "source_ids": row.get("source_ids", []),
            "model": row.get("model") or "rule-fallback",
            "fallback_used": bool(row.get("fallback_used", False)),
            "created_at": _to_local_iso(data_service, row.get("created_at")),
            "output_message_id": row.get("output_message_id"),
            "source_channel_id": row.get("source_channel_id"),
            "source_guild_id": row.get("source_guild_id"),
        }
        for row in rows
    ]

    return {
        "rows": response_rows,
        "count": len(response_rows),
        "limit": limit,
        "scope": scope,
    }


@app.get("/api/decisions")
def decisions(
    status: str = Query("all", pattern="^(all|open|closed)$"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    rows = data_service.list_decisions(status="all", limit=limit * 2)
    if status == "open":
        rows = [row for row in rows if _is_open_status(row.get("status"))]
    elif status == "closed":
        rows = [row for row in rows if _is_closed_status(row.get("status"))]

    response_rows = [
        {
            "decision_id": row.get("decision_id") or row.get("id"),
            "title": row.get("summary") or row.get("title") or "(제목 없음)",
            "owner": row.get("owner") or "-",
            "due_date": row.get("due_date"),
            "status": _normalize_decision_status(row.get("status")),
            "source_channel_id": row.get("source_channel_id"),
            "context_url": row.get("context_url"),
            "created_at": _to_local_iso(data_service, row.get("created_at")),
        }
        for row in rows[:limit]
    ]

    return {
        "rows": response_rows,
        "count": len(response_rows),
        "limit": limit,
        "status": status,
    }


@app.get("/api/events")
def events(
    event_type: str = Query("all", pattern="^(all|scheduled_inactivity_scan|error|warning)$"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    rows = data_service.list_events(event_type=event_type, limit=limit)
    response_rows = [
        {
            "event_type": row.get("event_type"),
            "occurred_at": _to_local_iso(data_service, row.get("occurred_at")),
            "payload": row.get("payload", {}),
        }
        for row in rows
    ]
    return {
        "rows": response_rows,
        "count": len(response_rows),
        "limit": limit,
        "event_type": event_type,
    }


@app.get("/api/metrics/quick")
def metrics_quick(hours: int = Query(24, ge=1, le=720)) -> dict[str, Any]:
    window_hours = min(hours, 30 * 24)
    since = datetime.now(data_service.tz) - timedelta(hours=window_hours)

    summaries = [
        row
        for row in data_service.read("summaries").rows
        if _within_window(row.get("created_at"), since, data_service)
    ]
    decisions = [
        row
        for row in data_service.read("decisions").rows
        if _within_window(row.get("created_at"), since, data_service)
    ]
    events = [
        row
        for row in data_service.read("ops_events").rows
        if _within_window(row.get("occurred_at"), since, data_service)
    ]

    warnings = 0
    deep_work = 0
    for row in events:
        event_type_value = str(row.get("event_type", "")).lower()
        if event_type_value in {"warroom_inactive_warning", "warroom_auto_archived"}:
            warnings += 1
        elif event_type_value in {"deep_work_intervention", "deep_work_notice"}:
            deep_work += 1

    return {
        "window_hours": window_hours,
        "summaries": len(summaries),
        "decisions": len(decisions),
        "warnings": warnings,
        "deep_work_interventions": deep_work,
    }


@app.post("/api/runtime/refresh")
def runtime_refresh() -> dict[str, Any]:
    data_service.refresh()
    return {
        "runtime": _runtime_payload(),
        "refreshed_at": datetime.now().isoformat(timespec="seconds"),
    }


@app.get("/health")
def plain_health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(Exception)
def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
    return JSONResponse(
        status_code=500,
        content={"error": str(exc)},
    )


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "망상궤도 비서 GUI 백엔드",
        "api": "/api/health",
    }
