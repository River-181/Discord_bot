#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
MAX_TASKS = 12
STATUS_CHOICES = {"active", "completed", "idle", "error"}

AGENT_DEPARTMENTS = {
    "discord-dev": "development",
    "bot-tester": "qa",
    "ops-analyst": "ops",
    "dashboard-dev": "dashboard",
}
AGENT_ORDER = list(AGENT_DEPARTMENTS.keys())


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _data_path() -> Path:
    path = _project_root() / "data" / "agent_sessions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(KST).isoformat()


def _read_sessions() -> list[dict]:
    path = _data_path()
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _append_row(row: dict) -> None:
    with _data_path().open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def _split_tasks(raw: str) -> list[str]:
    if not raw.strip():
        return []
    lines = [line.strip() for line in raw.replace("\r\n", "\n").split("\n")]
    if len(lines) <= 1:
        lines = [line.strip() for line in re.split(r"[;/]+", raw)]
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        line = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
        if not line or line in seen:
            continue
        out.append(line)
        seen.add(line)
        if len(out) >= MAX_TASKS:
            break
    return out


def _default_tasks(mission: str) -> list[tuple[str, str]]:
    return [
        ("discord-dev", f"{mission} implementation"),
        ("bot-tester", f"{mission} test and validation"),
        ("ops-analyst", f"{mission} operational analysis"),
        ("dashboard-dev", f"{mission} dashboard update"),
    ]


def _team_run_id() -> str:
    return f"team-{datetime.now(KST).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _session_key(session: dict) -> str:
    assignment_id = session.get("assignment_id")
    if assignment_id:
        return str(assignment_id)
    return f"{session.get('agent_name','')}::{session.get('task','')}::{session.get('started_at','')}"


def _latest_rows(rows: Iterable[dict]) -> list[dict]:
    latest: dict[str, dict] = {}
    for row in rows:
        latest[_session_key(row)] = row
    return list(latest.values())


@dataclass
class TeamSummary:
    team_run_id: str
    mission: str
    total: int
    active: int
    completed: int
    idle: int
    error: int
    progress_avg: int


def _summaries(rows: list[dict]) -> list[TeamSummary]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in _latest_rows(rows):
        run_id = str(row.get("team_run_id") or "").strip()
        if run_id:
            grouped[run_id].append(row)
    output: list[TeamSummary] = []
    for run_id, items in grouped.items():
        total = max(1, len(items))
        active = sum(1 for x in items if x.get("status") == "active")
        completed = sum(1 for x in items if x.get("status") == "completed")
        idle = sum(1 for x in items if x.get("status") == "idle")
        error = sum(1 for x in items if x.get("status") == "error")
        progress_avg = int(round(sum(int(x.get("progress") or 0) for x in items) / total))
        mission = str(items[0].get("mission") or "unknown mission")
        output.append(
            TeamSummary(
                team_run_id=run_id,
                mission=mission,
                total=total,
                active=active,
                completed=completed,
                idle=idle,
                error=error,
                progress_avg=max(0, min(100, progress_avg)),
            )
        )
    output.sort(key=lambda x: x.team_run_id, reverse=True)
    return output


def cmd_create(args: argparse.Namespace) -> None:
    mission = args.mission.strip()
    parsed = _split_tasks(args.tasks or "")
    run_id = _team_run_id()
    now_iso = _now_iso()
    rows: list[dict] = []

    if parsed:
        items = [(AGENT_ORDER[idx % len(AGENT_ORDER)], task) for idx, task in enumerate(parsed)]
    else:
        items = _default_tasks(mission)

    for idx, (agent_name, task) in enumerate(items, start=1):
        row = {
            "session_id": str(uuid.uuid4()),
            "assignment_id": str(uuid.uuid4()),
            "team_run_id": run_id,
            "mission": mission,
            "agent_name": agent_name,
            "department": AGENT_DEPARTMENTS[agent_name],
            "task": task,
            "status": "active",
            "started_at": now_iso,
            "completed_at": None,
            "updated_at": now_iso,
            "progress": 0,
            "assigned_by": args.assigned_by,
            "sequence": idx,
            "total_assignments": len(items),
            "mode": "local_teamctl",
        }
        rows.append(row)
        _append_row(row)

    print(f"team_run_id={run_id}")
    print(f"assignments={len(rows)}")
    for row in rows:
        print(f"- {row['agent_name']}: {row['task']}")


def cmd_update(args: argparse.Namespace) -> None:
    rows = _read_sessions()
    filtered = [x for x in rows if x.get("agent_name") == args.agent]
    if args.team_run_id:
        filtered = [x for x in filtered if x.get("team_run_id") == args.team_run_id]
    latest = filtered[-1] if filtered else {}

    status = args.status
    if status not in STATUS_CHOICES:
        raise SystemExit(f"invalid status: {status}")

    now_iso = _now_iso()
    progress = int(args.progress)
    if status == "completed":
        progress = 100
    progress = max(0, min(100, progress))

    row = {
        "session_id": str(uuid.uuid4()),
        "assignment_id": latest.get("assignment_id") or str(uuid.uuid4()),
        "team_run_id": args.team_run_id or latest.get("team_run_id"),
        "mission": latest.get("mission"),
        "agent_name": args.agent,
        "department": AGENT_DEPARTMENTS.get(args.agent, "unknown"),
        "task": latest.get("task") or args.note or "manual update",
        "status": status,
        "started_at": latest.get("started_at") or now_iso,
        "completed_at": now_iso if status == "completed" else None,
        "updated_at": now_iso,
        "progress": progress,
        "updated_by": args.updated_by,
        "note": args.note,
        "mode": "local_teamctl",
    }
    _append_row(row)
    print(f"updated agent={args.agent} status={status} progress={progress}")


def cmd_status(args: argparse.Namespace) -> None:
    rows = _read_sessions()
    summary = _summaries(rows)
    if not summary:
        print("no team runs")
        return
    for item in summary[: args.limit]:
        print(
            f"{item.team_run_id} | {item.mission} | "
            f"active {item.active}/{item.total} | completed {item.completed} | "
            f"error {item.error} | avg {item.progress_avg}%"
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Agent Team controller for dashboard.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Create a new team run")
    p_create.add_argument("--mission", required=True, help="Mission name")
    p_create.add_argument("--tasks", default="", help="Tasks separated by newline, ';' or '/'")
    p_create.add_argument("--assigned-by", default="local-operator", help="Operator id/name")
    p_create.set_defaults(func=cmd_create)

    p_update = sub.add_parser("update", help="Update one agent assignment")
    p_update.add_argument("--agent", required=True, choices=AGENT_ORDER)
    p_update.add_argument("--status", required=True, choices=sorted(STATUS_CHOICES))
    p_update.add_argument("--progress", type=int, default=0)
    p_update.add_argument("--note", default="")
    p_update.add_argument("--team-run-id", default="")
    p_update.add_argument("--updated-by", default="local-operator")
    p_update.set_defaults(func=cmd_update)

    p_status = sub.add_parser("status", help="Print team run status")
    p_status.add_argument("--limit", type=int, default=10)
    p_status.set_defaults(func=cmd_status)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
