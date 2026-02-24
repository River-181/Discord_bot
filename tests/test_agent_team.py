from __future__ import annotations

from bot.commands.agent import (
    _build_team_assignments,
    _split_team_tasks,
    _summarize_team_runs,
)


def test_split_team_tasks_parses_and_deduplicates() -> None:
    raw = """
    - API 스키마 정의
    - API 스키마 정의
    2) slash command 연결
    • 대시보드 반영
    """
    tasks = _split_team_tasks(raw)
    assert tasks == ["API 스키마 정의", "slash command 연결", "대시보드 반영"]


def test_build_team_assignments_round_robin() -> None:
    team_run_id, records = _build_team_assignments(
        mission="Agent Team 실행",
        tasks=["A", "B", "C", "D", "E"],
        assigned_by="tester",
        now_iso="2026-02-20T12:00:00+09:00",
    )
    assert team_run_id.startswith("team-")
    assert len(records) == 5
    assert [r["agent_name"] for r in records] == [
        "discord-dev",
        "bot-tester",
        "ops-analyst",
        "dashboard-dev",
        "discord-dev",
    ]
    assert all(r["team_run_id"] == team_run_id for r in records)


def test_summarize_team_runs_uses_latest_assignment_state() -> None:
    sessions = [
        {
            "assignment_id": "a1",
            "team_run_id": "team-x",
            "mission": "M1",
            "agent_name": "discord-dev",
            "status": "active",
            "progress": 40,
            "updated_at": "2026-02-20T01:00:00+09:00",
        },
        {
            "assignment_id": "a1",
            "team_run_id": "team-x",
            "mission": "M1",
            "agent_name": "discord-dev",
            "status": "completed",
            "progress": 100,
            "updated_at": "2026-02-20T02:00:00+09:00",
        },
        {
            "assignment_id": "a2",
            "team_run_id": "team-x",
            "mission": "M1",
            "agent_name": "bot-tester",
            "status": "active",
            "progress": 50,
            "updated_at": "2026-02-20T02:10:00+09:00",
        },
    ]
    summary = _summarize_team_runs(sessions)
    assert len(summary) == 1
    run = summary[0]
    assert run["team_run_id"] == "team-x"
    assert run["total"] == 2
    assert run["completed"] == 1
    assert run["active"] == 1
    assert run["progress_avg"] == 75
