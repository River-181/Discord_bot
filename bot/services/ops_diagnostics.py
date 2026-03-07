from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger


def parse_iso_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def format_local_iso(value: Any, timezone_name: str) -> str | None:
    dt = parse_iso_datetime(value)
    if dt is None:
        return None
    return dt.astimezone(ZoneInfo(timezone_name)).isoformat(timespec="seconds")


def next_run_at(cron_expr: str, timezone_name: str) -> str | None:
    try:
        tz = ZoneInfo(timezone_name)
        trigger = CronTrigger.from_crontab(cron_expr, timezone=tz)
        next_fire = trigger.get_next_fire_time(None, datetime.now(tz))
        if next_fire is None:
            return None
        return next_fire.isoformat(timespec="seconds")
    except Exception:
        return None


def nearest_next_run_at(cron_exprs: Iterable[str], timezone_name: str) -> str | None:
    candidates: list[datetime] = []
    tz = ZoneInfo(timezone_name)
    for expr in cron_exprs:
        dt = parse_iso_datetime(next_run_at(expr, timezone_name))
        if dt is not None:
            candidates.append(dt.astimezone(tz))
    if not candidates:
        return None
    return min(candidates).isoformat(timespec="seconds")


def latest_rows_by_key(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        raw_key = row.get(key)
        if raw_key is None:
            continue
        latest[str(raw_key)] = row
    return latest


def _latest_row(
    rows: list[dict[str, Any]],
    *,
    timestamp_key: str,
    predicate: callable | None = None,
) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    latest_dt: datetime | None = None
    for row in rows:
        if predicate and not predicate(row):
            continue
        dt = parse_iso_datetime(row.get(timestamp_key))
        if dt is None:
            continue
        if latest_dt is None or dt > latest_dt:
            latest = row
            latest_dt = dt
    return latest


def _latest_matching_event(
    ops_rows: list[dict[str, Any]],
    *,
    event_types: set[str] | None = None,
    event_type_contains: tuple[str, ...] = (),
    result_prefixes: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    def _matches(row: dict[str, Any]) -> bool:
        event_type = str(row.get("event_type", "")).lower()
        payload = row.get("payload", {})
        result = str(payload.get("result", "")).lower() if isinstance(payload, dict) else ""
        if event_types and event_type in event_types:
            return True
        if event_type_contains and any(token in event_type for token in event_type_contains):
            return True
        if result_prefixes and any(result.startswith(prefix) for prefix in result_prefixes):
            return True
        return False

    return _latest_row(ops_rows, timestamp_key="occurred_at", predicate=_matches)


def build_recent_failures(
    ops_rows: list[dict[str, Any]],
    timezone_name: str,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in ops_rows:
        event_type = str(row.get("event_type", "")).lower()
        payload = row.get("payload", {}) if isinstance(row.get("payload"), dict) else {}
        result = str(payload.get("result", "")).lower()
        error = str(payload.get("error", "")).strip()
        if not (
            "error" in event_type
            or "failed" in event_type
            or result.startswith(("error", "blocked", "missing"))
            or error
        ):
            continue
        failures.append(
            {
                "event_type": row.get("event_type"),
                "occurred_at": format_local_iso(row.get("occurred_at"), timezone_name) or "-",
                "command_name": payload.get("command_name") if isinstance(payload, dict) else None,
                "detail": error or str(payload.get("result", "") or "-"),
            }
        )
    failures.sort(key=lambda row: row.get("occurred_at", ""), reverse=True)
    return failures[:limit]


def build_news_runtime(
    news_digests_rows: list[dict[str, Any]],
    ops_rows: list[dict[str, Any]],
    *,
    timezone_name: str,
    morning_cron: str,
    evening_cron: str,
) -> dict[str, Any]:
    latest_digest = _latest_row(news_digests_rows, timestamp_key="run_at")
    latest_completed = _latest_matching_event(ops_rows, event_types={"news_digest_completed"})
    latest_failure = _latest_matching_event(ops_rows, event_types={"news_post_error", "news_fetch_error"})

    completed_dt = parse_iso_datetime(latest_completed.get("occurred_at")) if latest_completed else None
    failure_dt = parse_iso_datetime(latest_failure.get("occurred_at")) if latest_failure else None
    last_result = "never"
    if latest_completed is not None:
        payload = latest_completed.get("payload", {})
        errors = int(payload.get("errors", 0)) if isinstance(payload, dict) else 0
        last_result = "warning" if errors > 0 else "ok"
    if failure_dt and (completed_dt is None or failure_dt > completed_dt):
        last_result = "error"

    failure_payload = latest_failure.get("payload", {}) if latest_failure and isinstance(latest_failure.get("payload"), dict) else {}
    return {
        "last_run_at": format_local_iso(
            (latest_digest or {}).get("run_at") or (latest_completed or {}).get("occurred_at"),
            timezone_name,
        ),
        "last_result": last_result,
        "next_run_at": nearest_next_run_at((morning_cron, evening_cron), timezone_name),
        "last_items_count": int((latest_digest or {}).get("items_count", 0) or 0),
        "last_failure_at": format_local_iso((latest_failure or {}).get("occurred_at"), timezone_name),
        "last_failure": str(failure_payload.get("error", "")).strip() or None,
    }


def build_event_reminder_runtime(
    ops_rows: list[dict[str, Any]],
    *,
    timezone_name: str,
    scan_cron: str,
    last_scan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latest_completed = _latest_matching_event(ops_rows, event_types={"event_reminder_scan_completed"})
    latest_failure = _latest_matching_event(ops_rows, event_types={"event_reminder_error"})
    scan = dict(last_scan or {})
    if not scan and latest_completed and isinstance(latest_completed.get("payload"), dict):
        scan = dict(latest_completed["payload"])

    errors = int(scan.get("errors", 0) or 0)
    last_result = "error" if errors > 0 else str(scan.get("result", "ok") or "ok")
    failure_payload = latest_failure.get("payload", {}) if latest_failure and isinstance(latest_failure.get("payload"), dict) else {}
    return {
        "last_run_at": format_local_iso(
            scan.get("scan_completed_at") or scan.get("scan_started_at") or (latest_completed or {}).get("occurred_at"),
            timezone_name,
        ),
        "last_result": last_result,
        "next_run_at": next_run_at(scan_cron, timezone_name),
        "last_due_events": int(scan.get("due_events", 0) or 0),
        "last_errors": errors,
        "last_failure_at": format_local_iso((latest_failure or {}).get("occurred_at"), timezone_name),
        "last_failure": str(failure_payload.get("error", "")).strip() or None,
    }


def build_music_runtime(
    ops_rows: list[dict[str, Any]],
    timezone_name: str,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    latest_failure = _latest_matching_event(
        ops_rows,
        event_types={"music_error", "music_join_failed", "music_command_failed"},
        result_prefixes=("error", "blocked", "missing"),
    )
    latest_started = _latest_matching_event(ops_rows, event_types={"music_track_started"})
    failure_payload = latest_failure.get("payload", {}) if latest_failure and isinstance(latest_failure.get("payload"), dict) else {}
    return {
        "last_run_at": format_local_iso((latest_started or {}).get("occurred_at"), timezone_name),
        "last_result": "error" if latest_failure else ("active" if diagnostics.get("active_sessions") else "idle"),
        "active_sessions": int(diagnostics.get("active_sessions", 0) or 0),
        "default_control_channel": str(diagnostics.get("default_control_channel", "auto")),
        "ffmpeg_available": bool(diagnostics.get("ffmpeg_available", False)),
        "voice_dependency_ok": bool(diagnostics.get("voice_dependency_ok", False)),
        "last_failure_at": format_local_iso((latest_failure or {}).get("occurred_at"), timezone_name),
        "last_failure": str(failure_payload.get("error") or failure_payload.get("result") or "").strip() or None,
    }


def build_curation_runtime(
    submission_rows: list[dict[str, Any]],
    ops_rows: list[dict[str, Any]],
    *,
    timezone_name: str,
) -> dict[str, Any]:
    latest_by_submission = latest_rows_by_key(submission_rows, "submission_id")
    counts = {"pending": 0, "approved": 0, "rejected": 0, "merged": 0, "total": 0}
    type_counts: Counter[str] = Counter()
    oldest_pending_at: datetime | None = None
    latest_reviewed: dict[str, datetime | None] = {"approved": None, "rejected": None, "merged": None}

    for row in latest_by_submission.values():
        counts["total"] += 1
        status = str(row.get("status", "pending")).lower()
        if status in counts:
            counts[status] += 1
        type_counts[str(row.get("classified_type", "unknown")).lower()] += 1
        created_dt = parse_iso_datetime(row.get("created_at"))
        reviewed_dt = parse_iso_datetime(row.get("reviewed_at"))
        if status == "pending" and created_dt is not None:
            if oldest_pending_at is None or created_dt < oldest_pending_at:
                oldest_pending_at = created_dt
        if status in latest_reviewed and reviewed_dt is not None:
            current = latest_reviewed[status]
            if current is None or reviewed_dt > current:
                latest_reviewed[status] = reviewed_dt

    hook_sources: Counter[str] = Counter()
    for row in ops_rows:
        if str(row.get("event_type", "")).lower() != "curation_approved":
            continue
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            continue
        hook_source = str(payload.get("hook_source", "")).strip().lower()
        if hook_source:
            hook_sources[hook_source] += 1

    hook_total = sum(hook_sources.values())
    persona_ratio = round((hook_sources.get("persona", 0) / hook_total) * 100, 1) if hook_total else 0.0
    latest_failure = _latest_matching_event(
        ops_rows,
        event_types={"curation_publish_failed"},
        event_type_contains=("error",),
    )
    pending_age_hours: int | None = None
    if oldest_pending_at is not None:
        pending_age_hours = max(0, int((datetime.now(UTC) - oldest_pending_at).total_seconds() // 3600))
    failure_payload = latest_failure.get("payload", {}) if latest_failure and isinstance(latest_failure.get("payload"), dict) else {}

    return {
        "counts": counts,
        "type_counts": dict(type_counts),
        "hook_source_counts": dict(hook_sources),
        "hook_persona_ratio": persona_ratio,
        "pending_oldest_at": format_local_iso(oldest_pending_at, timezone_name),
        "pending_oldest_age_hours": pending_age_hours,
        "latest_approved_at": format_local_iso(latest_reviewed["approved"], timezone_name),
        "latest_rejected_at": format_local_iso(latest_reviewed["rejected"], timezone_name),
        "latest_merged_at": format_local_iso(latest_reviewed["merged"], timezone_name),
        "last_failure_at": format_local_iso((latest_failure or {}).get("occurred_at"), timezone_name),
        "last_failure": str(failure_payload.get("error", "")).strip() or None,
    }
