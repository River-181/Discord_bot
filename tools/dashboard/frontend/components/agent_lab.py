from __future__ import annotations

import json
import re
import statistics
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import time

import streamlit as st


KST = ZoneInfo("Asia/Seoul")

DEPARTMENTS = {
    "개발실": {"icon": "🔬", "agents": ["discord-dev"]},
    "QA 랩": {"icon": "🧪", "agents": ["bot-tester"]},
    "운영 센터": {"icon": "📊", "agents": ["ops-analyst"]},
    "대시보드 랩": {"icon": "🖥️", "agents": ["dashboard-dev"]},
}

STATUS_CONFIG = {
    "active": {"label": "활성", "color": "#00ff88", "bg": "#003322", "dot": "🟢"},
    "completed": {"label": "완료", "color": "#4488ff", "bg": "#001133", "dot": "🔵"},
    "idle": {"label": "대기", "color": "#ffaa00", "bg": "#332200", "dot": "🟡"},
    "error": {"label": "오류", "color": "#ff4444", "bg": "#330000", "dot": "🔴"},
}

AGENT_DEPARTMENTS = {
    "discord-dev": "development",
    "bot-tester": "qa",
    "ops-analyst": "ops",
    "dashboard-dev": "dashboard",
}
AGENT_ORDER = ["discord-dev", "bot-tester", "ops-analyst", "dashboard-dev"]
MAX_TASKS = 12

LAB_CSS = """
<style>
/* 연구소 전체 테마 */
.lab-header {
    background: linear-gradient(135deg, #0a0a1a 0%, #1a0a2e 50%, #0a1a2e 100%);
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 20px 28px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.lab-title {
    font-size: 1.6rem;
    font-weight: 800;
    color: #00ccff;
    text-shadow: 0 0 20px #00ccff88;
    letter-spacing: 2px;
}
.lab-live {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: #003322;
    border: 1px solid #00ff88;
    border-radius: 20px;
    padding: 4px 14px;
    font-size: 0.8rem;
    color: #00ff88;
}
.lab-live-dot {
    width: 8px;
    height: 8px;
    background: #00ff88;
    border-radius: 50%;
    animation: pulse 1.5s ease-in-out infinite;
    display: inline-block;
}
@keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.4; transform: scale(0.8); }
}

/* 부서 카드 */
.dept-card {
    background: linear-gradient(160deg, #0d0d1f 0%, #0a0a1a 100%);
    border: 1px solid #1a1a3a;
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 12px;
}
.dept-title {
    font-size: 1rem;
    font-weight: 700;
    color: #8888cc;
    margin-bottom: 12px;
    letter-spacing: 1px;
}

/* 에이전트 카드 */
.agent-card {
    border-radius: 8px;
    padding: 14px;
    margin-bottom: 8px;
    border: 1px solid #1e1e3e;
    position: relative;
}
.agent-name {
    font-size: 0.9rem;
    font-weight: 700;
    margin-bottom: 6px;
    font-family: monospace;
}
.agent-task {
    font-size: 0.75rem;
    color: #888899;
    margin-bottom: 10px;
    min-height: 16px;
}
.agent-badge {
    display: inline-block;
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 0.7rem;
    font-weight: 600;
    margin-bottom: 8px;
}
.progress-track {
    background: #1a1a2e;
    border-radius: 4px;
    height: 6px;
    overflow: hidden;
    margin-top: 6px;
}
.progress-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.5s ease;
}
.agent-stat {
    font-size: 0.7rem;
    color: #666688;
    margin-top: 6px;
    text-align: right;
}

.facility-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
    margin: 12px 0 18px 0;
}

.facility-title {
    font-size: 0.92rem;
    color: #88ccff;
    letter-spacing: 0.8px;
    margin-bottom: 8px;
    font-weight: 700;
}

.facility-card {
    border-radius: 10px;
    border: 1px solid #1d2a4a;
    padding: 12px;
    background: linear-gradient(140deg, #09091a 0%, #070f2a 100%);
    min-height: 120px;
}

.facility-card-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 8px;
}

.facility-card-title {
    font-weight: 700;
    font-size: 0.78rem;
    color: #b8daff;
    letter-spacing: 0.6px;
}

.facility-card-status {
    font-size: 0.68rem;
    color: #8ea0c8;
    font-family: monospace;
}

.facility-task {
    font-size: 0.72rem;
    color: #8899bb;
    min-height: 42px;
    line-height: 1.35;
    margin-bottom: 8px;
}

.facility-stats {
    font-size: 0.66rem;
    color: #667;
    margin-top: 6px;
}

.mission-board {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
}

.mission-card {
    border: 1px solid #2a365f;
    border-radius: 10px;
    padding: 12px;
    background: linear-gradient(140deg, #0f0f24 0%, #11142a 100%);
}

.mission-name {
    font-weight: 700;
    color: #8ed6ff;
    margin-bottom: 6px;
}

.mission-meta {
    color: #7081a3;
    font-size: 0.68rem;
    margin-bottom: 8px;
}

.task-pill {
    display: inline-block;
    border: 1px solid #25345a;
    border-radius: 999px;
    padding: 2px 8px;
    margin: 3px 4px 0 0;
    font-size: 0.64rem;
    color: #c2d8ff;
}

.task-pill.done {
    border-color: #2a7d5d;
    color: #8ff5b3;
}

.task-pill.warn {
    border-color: #5d2b2b;
    color: #ff9a7e;
}

.mission-summary {
    margin-top: 8px;
    font-size: 0.64rem;
    color: #6f7ea1;
}

/* 활동 로그 */
.log-container {
    background: #050510;
    border: 1px solid #1a1a3a;
    border-radius: 10px;
    padding: 16px;
    font-family: 'Courier New', monospace;
    font-size: 0.78rem;
    color: #aaaacc;
    max-height: 260px;
    overflow-y: auto;
}
.log-entry {
    padding: 4px 0;
    border-bottom: 1px solid #0d0d1a;
    line-height: 1.5;
}
.log-time {
    color: #555577;
    margin-right: 8px;
}
.log-agent {
    font-weight: 700;
    margin-right: 4px;
}
.log-msg {
    color: #9999bb;
}

/* 통계 바 */
.stat-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 20px;
}
.stat-box {
    background: #0a0a1a;
    border: 1px solid #1a1a3a;
    border-radius: 8px;
    padding: 12px;
    text-align: center;
}
.stat-value {
    font-size: 1.8rem;
    font-weight: 800;
    color: #00ccff;
    line-height: 1;
}
.stat-label {
    font-size: 0.72rem;
    color: #555577;
    margin-top: 4px;
    letter-spacing: 0.5px;
}
</style>
"""


def _load_sessions(data_dir: Path) -> tuple[list[dict], int]:
    """agent_sessions.jsonl 로드"""
    path = data_dir / "agent_sessions.jsonl"
    if not path.exists():
        return [], 0
    sessions = []
    corrupt_lines = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            sessions.append(json.loads(line))
        except json.JSONDecodeError:
            corrupt_lines += 1
            continue
    return sessions, corrupt_lines


def _get_agent_display(sessions: list[dict], agent_name: str) -> dict:
    """특정 에이전트의 최신 세션 정보 반환"""
    agent_sessions = [s for s in sessions if s.get("agent_name") == agent_name]
    if not agent_sessions:
        return {
            "status": "idle",
            "task": "대기 중",
            "progress": 0,
            "completed_count": 0,
        }
    latest = agent_sessions[-1]
    completed = sum(1 for s in agent_sessions if s.get("status") == "completed")
    return {
        "status": latest.get("status", "idle"),
        "task": latest.get("task", "대기 중"),
        "progress": latest.get("progress", 0),
        "completed_count": completed,
    }


def _session_key(session: dict) -> str:
    assignment_id = session.get("assignment_id")
    if assignment_id:
        return str(assignment_id)
    agent = session.get("agent_name", "unknown")
    task = session.get("task", "")
    started_at = session.get("started_at", "")
    return f"{agent}::{task}::{started_at}"


def _latest_sessions(sessions: list[dict]) -> list[dict]:
    latest: dict[str, dict] = {}
    for session in sessions:
        latest[_session_key(session)] = session
    return list(latest.values())


def _build_team_run_summaries(sessions: list[dict]) -> list[dict]:
    latest = _latest_sessions(sessions)
    grouped: dict[str, dict] = {}
    for session in latest:
        team_run_id = str(session.get("team_run_id") or "").strip()
        if not team_run_id:
            continue
        info = grouped.setdefault(
            team_run_id,
            {
                "team_run_id": team_run_id,
                "mission": session.get("mission") or "미션 미상",
                "active": 0,
                "completed": 0,
                "idle": 0,
                "error": 0,
                "total": 0,
                "progress_total": 0,
                "latest_at": "",
            },
        )
        status = str(session.get("status", "idle"))
        if status not in STATUS_CONFIG:
            status = "idle"
        info[status] += 1
        info["total"] += 1
        info["progress_total"] += int(session.get("progress") or 0)
        latest_at = str(session.get("updated_at") or session.get("completed_at") or session.get("started_at") or "")
        if latest_at and latest_at > str(info["latest_at"]):
            info["latest_at"] = latest_at

    summaries = []
    for item in grouped.values():
        total = max(1, int(item["total"]))
        item["progress_avg"] = int(round(int(item["progress_total"]) / total))
        summaries.append(item)
    summaries.sort(key=lambda x: str(x.get("latest_at") or ""), reverse=True)
    return summaries


def _render_agent_card(agent_name: str, info: dict) -> str:
    """에이전트 카드 HTML 생성"""
    status = info["status"]
    cfg = STATUS_CONFIG.get(status, STATUS_CONFIG["idle"])
    progress = info["progress"]

    # 진행률 바 색상
    if status == "active":
        bar_color = "#00ff88"
    elif status == "completed":
        bar_color = "#4488ff"
    else:
        bar_color = "#555566"

    return f"""
<div class="agent-card" style="background: {cfg['bg']}; border-color: {cfg['color']}33;">
    <div style="display: flex; justify-content: space-between; align-items: flex-start;">
        <div class="agent-name" style="color: {cfg['color']};">{agent_name}</div>
        <span class="agent-badge" style="background: {cfg['bg']}; color: {cfg['color']}; border: 1px solid {cfg['color']}66;">
            {cfg['dot']} {cfg['label']}
        </span>
    </div>
    <div class="agent-task">{info['task']}</div>
    <div class="progress-track">
        <div class="progress-fill" style="width: {progress}%; background: linear-gradient(90deg, {bar_color}88, {bar_color});"></div>
    </div>
    <div class="agent-stat">완료: {info['completed_count']}건 | 진행률: {progress}%</div>
</div>
"""


def _render_facility_card(agent_name: str, info: dict, dept_name: str) -> str:
    """연구소 시설 카드 HTML 생성"""
    status = info["status"]
    cfg = STATUS_CONFIG.get(status, STATUS_CONFIG["idle"])
    progress = info["progress"]
    if status == "active":
        bar_color = "#00ff88"
    elif status == "completed":
        bar_color = "#4488ff"
    else:
        bar_color = "#555566"

    return f"""
<div class="facility-card" style="border-color: {cfg['color']}55;">
    <div class="facility-card-header">
        <div class="facility-card-title">[{dept_name}] {agent_name}</div>
        <div class="facility-card-status">{cfg['dot']} {cfg['label']}</div>
    </div>
    <div class="facility-task">{_safe_text(info['task'], 76)}</div>
    <div class="progress-track">
        <div class="progress-fill" style="width: {progress}%; background: linear-gradient(90deg, {bar_color}88, {bar_color});"></div>
    </div>
    <div class="facility-stats">완료 누적 {info['completed_count']}건 / 진행률 {progress}%</div>
</div>
"""


def _render_log_entries(sessions: list[dict]) -> str:
    """활동 로그 HTML 생성"""
    completed = [s for s in sessions if s.get("status") == "completed"]
    active = [s for s in sessions if s.get("status") == "active"]

    all_entries = []

    for s in completed:
        if s.get("completed_at"):
            try:
                dt = datetime.fromisoformat(s["completed_at"])
                time_str = dt.astimezone(KST).strftime("%H:%M")
            except Exception:
                time_str = "--:--"
            agent = s.get("agent_name", "?")
            task = s.get("task", "")
            dept = s.get("department", "")
            cfg = STATUS_CONFIG["completed"]
            all_entries.append((time_str, agent, f"{task} 완료", cfg["color"]))

    for s in active:
        if s.get("started_at"):
            try:
                dt = datetime.fromisoformat(s["started_at"])
                time_str = dt.astimezone(KST).strftime("%H:%M")
            except Exception:
                time_str = "--:--"
            agent = s.get("agent_name", "?")
            task = s.get("task", "")
            cfg = STATUS_CONFIG["active"]
            all_entries.append((time_str, agent, f"{task} 진행 중...", cfg["color"]))

    all_entries.sort(key=lambda x: x[0], reverse=True)

    html_parts = []
    for time_str, agent, msg, color in all_entries[:20]:
        html_parts.append(
            f'<div class="log-entry">'
            f'<span class="log-time">[{time_str}]</span>'
            f'<span class="log-agent" style="color: {color};">{agent}:</span>'
            f'<span class="log-msg"> {msg}</span>'
            f'</div>'
        )

    return "\n".join(html_parts) if html_parts else '<div class="log-entry" style="color: #333355;">활동 기록이 없습니다.</div>'


def _safe_text(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    return value[: max_len - 3] + "..."


def _run_id_label(team_run_id: str) -> str:
    if not team_run_id:
        return "standalone"
    if len(team_run_id) <= 10:
        return team_run_id
    return team_run_id[:7] + "..." + team_run_id[-3:]


def _gauge_value(values: list[float]) -> float:
    if not values:
        return 0.0
    return statistics.mean(values)


def _build_run_board_data(sessions: list[dict]) -> list[dict]:
    latest = _latest_sessions(sessions)
    by_run: dict[str, list[dict]] = {}
    for session in latest:
        team_run_id = str(session.get("team_run_id") or "").strip()
        if not team_run_id:
            continue
        by_run.setdefault(team_run_id, []).append(session)

    cards: list[dict] = []
    for team_run_id, run_sessions in by_run.items():
        run_sessions.sort(key=lambda x: int(x.get("sequence", 0) or 0))
        mission = str((run_sessions[0] if run_sessions else {}).get("mission") or "미션 미상")
        total = max(1, int(run_sessions[0].get("total_assignments") or len(run_sessions)))
        active = sum(1 for s in run_sessions if s.get("status") == "active")
        completed = sum(1 for s in run_sessions if s.get("status") == "completed")
        error = sum(1 for s in run_sessions if s.get("status") == "error")
        latest_at = ""
        for s in run_sessions:
            stamp = str(s.get("updated_at") or s.get("started_at") or "")
            if stamp > latest_at:
                latest_at = stamp
        try:
            time_sort = datetime.fromisoformat(latest_at).astimezone(KST)
            latest_at_label = time_sort.strftime("%m-%d %H:%M")
        except Exception:
            latest_at_label = "--:--"

        progress_avg = int(
            round(_gauge_value([float(s.get("progress") or 0) for s in run_sessions]))
        )
        progress_avg = max(0, min(100, progress_avg))

        pending = total - completed - active - error
        cards.append({
            "team_run_id": team_run_id,
            "team_run_label": _run_id_label(team_run_id),
            "mission": mission,
            "total": total,
            "active": active,
            "completed": completed,
            "error": error,
            "pending": max(0, pending),
            "progress_avg": progress_avg,
            "updated_at": latest_at,
            "updated_label": latest_at_label,
            "assignments": run_sessions[:8],
        })

    cards.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return cards[:10]


def _append_agent_session(data_dir: Path, row: dict) -> None:
    path = data_dir / "agent_sessions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def _now_iso() -> str:
    return datetime.now(KST).isoformat()


def _split_tasks(tasks_raw: str) -> list[str]:
    if not tasks_raw.strip():
        return []
    lines = [line.strip() for line in tasks_raw.replace("\r\n", "\n").split("\n")]
    if len(lines) <= 1:
        lines = [line.strip() for line in re.split(r"[;/]+", tasks_raw)]
    cleaned: list[str] = []
    seen: set[str] = set()
    for line in lines:
        line = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
        if not line:
            continue
        if line in seen:
            continue
        cleaned.append(line)
        seen.add(line)
        if len(cleaned) >= MAX_TASKS:
            break
    return cleaned


def _build_default_tasks(mission: str) -> list[tuple[str, str]]:
    return [
        ("discord-dev", f"{mission} implementation"),
        ("bot-tester", f"{mission} test and validation"),
        ("ops-analyst", f"{mission} operational analysis"),
        ("dashboard-dev", f"{mission} dashboard update"),
    ]


def _create_team_records(mission: str, tasks_raw: str, assigned_by: str) -> tuple[str, list[dict]]:
    parsed_tasks = _split_tasks(tasks_raw)
    team_run_id = f"team-{datetime.now(KST).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    now_iso = _now_iso()

    if parsed_tasks:
        assignments = [(AGENT_ORDER[idx % len(AGENT_ORDER)], task) for idx, task in enumerate(parsed_tasks)]
    else:
        assignments = _build_default_tasks(mission)

    records: list[dict] = []
    for idx, (agent_name, task) in enumerate(assignments, start=1):
        records.append(
            {
                "session_id": str(uuid.uuid4()),
                "assignment_id": str(uuid.uuid4()),
                "team_run_id": team_run_id,
                "mission": mission,
                "agent_name": agent_name,
                "department": AGENT_DEPARTMENTS.get(agent_name, "unknown"),
                "task": task,
                "status": "active",
                "started_at": now_iso,
                "completed_at": None,
                "updated_at": now_iso,
                "progress": 0,
                "assigned_by": assigned_by.strip() or "dashboard-operator",
                "sequence": idx,
                "total_assignments": len(assignments),
                "mode": "local_dashboard",
            }
        )
    return team_run_id, records


def _latest_assignment_for_agent(sessions: list[dict], agent_name: str, team_run_id: str) -> dict | None:
    for session in reversed(sessions):
        if session.get("agent_name") != agent_name:
            continue
        if session.get("team_run_id") != team_run_id:
            continue
        return session
    return None


def _build_update_record(
    sessions: list[dict],
    team_run_id: str,
    agent_name: str,
    status: str,
    progress: int,
    note: str,
    updated_by: str,
) -> dict | None:
    latest = _latest_assignment_for_agent(sessions, agent_name=agent_name, team_run_id=team_run_id)
    if not latest:
        return None

    now_iso = _now_iso()
    normalized_progress = 100 if status == "completed" else int(progress)
    normalized_progress = max(0, min(100, normalized_progress))

    return {
        "session_id": str(uuid.uuid4()),
        "assignment_id": latest.get("assignment_id") or str(uuid.uuid4()),
        "team_run_id": team_run_id,
        "mission": latest.get("mission"),
        "agent_name": agent_name,
        "department": AGENT_DEPARTMENTS.get(agent_name, "unknown"),
        "task": latest.get("task") or note or "manual update",
        "status": status,
        "started_at": latest.get("started_at") or now_iso,
        "completed_at": now_iso if status == "completed" else None,
        "updated_at": now_iso,
        "progress": normalized_progress,
        "updated_by": updated_by.strip() or "dashboard-operator",
        "note": note.strip() or None,
        "mode": "local_dashboard",
    }


def _build_team_options(sessions: list[dict]) -> list[tuple[str, str]]:
    cards = _build_run_board_data(sessions)
    options: list[tuple[str, str]] = []
    for card in cards:
        team_run_id = str(card.get("team_run_id") or "")
        mission = str(card.get("mission") or "미션 미상")
        label = f"{team_run_id} | {mission}"
        options.append((label, team_run_id))
    return options


def render_agent_lab(data_dir: Path | None = None) -> None:
    """망상 궤도 연구소 타이쿤 UI 메인 렌더링 함수"""
    if data_dir is None:
        data_dir = Path(__file__).parents[4] / "data"

    sessions, corrupt_lines = _load_sessions(data_dir)

    st.markdown(LAB_CSS, unsafe_allow_html=True)

    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    st.markdown(f"""
<div class="lab-header">
    <div class="lab-title">🏭 망상 궤도 연구소 운영 대시보드</div>
    <div class="lab-live">
        <span class="lab-live-dot"></span>
        실시간 &nbsp;|&nbsp; {now_kst}
    </div>
</div>
""", unsafe_allow_html=True)

    if corrupt_lines:
        st.warning(f"agent_sessions.jsonl 파싱 실패 라인: {corrupt_lines} (유효 라인만 표시)")

    with st.expander("🛠️ Agent Lab 제어면 (개발/운영 전용)", expanded=False):
        st.caption("Discord 명령이 아닌 로컬 대시보드 입력으로 팀 미션을 제어합니다.")
        create_col, update_col = st.columns(2)

        with create_col:
            st.markdown("**새 팀 미션 생성**")
            with st.form("agent_lab_create_form"):
                mission = st.text_input("mission", placeholder="예: 뉴스 레이다 노이즈 감소")
                tasks_raw = st.text_area(
                    "tasks (선택)",
                    placeholder="줄바꿈, ';', '/' 로 구분. 비우면 기본 4개 역할 자동 배치",
                    height=120,
                )
                assigned_by = st.text_input("assigned_by", value="dashboard-operator")
                submitted_create = st.form_submit_button("Create")

                if submitted_create:
                    mission = mission.strip()
                    if not mission:
                        st.error("mission은 필수입니다.")
                    else:
                        team_run_id, records = _create_team_records(
                            mission=mission,
                            tasks_raw=tasks_raw,
                            assigned_by=assigned_by,
                        )
                        for row in records:
                            _append_agent_session(data_dir, row)
                        st.success(f"team_run_id `{team_run_id}` 생성 완료 ({len(records)} assignments)")
                        st.rerun()

        with update_col:
            st.markdown("**Assignment 상태 업데이트**")
            team_options = _build_team_options(sessions)
            if not team_options:
                st.info("업데이트할 팀 런이 없습니다. 먼저 미션을 생성하세요.")
            else:
                with st.form("agent_lab_update_form"):
                    labels = [label for label, _ in team_options]
                    selected_label = st.selectbox("team_run", options=labels)
                    selected_team_run_id = dict(team_options).get(selected_label, "")
                    agent_name = st.selectbox("agent", options=AGENT_ORDER)
                    status = st.selectbox("status", options=list(STATUS_CONFIG.keys()))
                    progress = st.slider("progress", min_value=0, max_value=100, value=0, step=5)
                    note = st.text_input("note", placeholder="선택 메모")
                    updated_by = st.text_input("updated_by", value="dashboard-operator")
                    submitted_update = st.form_submit_button("Update")

                    if submitted_update:
                        if not selected_team_run_id:
                            st.error("team_run_id가 필요합니다.")
                        else:
                            row = _build_update_record(
                                sessions=sessions,
                                team_run_id=selected_team_run_id,
                                agent_name=agent_name,
                                status=status,
                                progress=progress,
                                note=note,
                                updated_by=updated_by,
                            )
                            if row is None:
                                st.error("선택한 team_run에서 해당 agent의 assignment를 찾지 못했습니다.")
                            else:
                                _append_agent_session(data_dir, row)
                                st.success(f"업데이트 완료: {agent_name} / {status} / {row['progress']}%")
                                st.rerun()

    latest = _latest_sessions(sessions)
    latest_by_agent: dict[str, dict] = {}
    for item in latest:
        agent_name = str(item.get("agent_name", ""))
        if agent_name:
            latest_by_agent[agent_name] = item

    # 상단 운영 지표 (타이쿤식)
    total_agents = sum(len(v["agents"]) for v in DEPARTMENTS.values())
    active_count = sum(1 for s in latest_by_agent.values() if s.get("status") == "active")
    completed_count = sum(1 for s in sessions if s.get("status") == "completed")
    error_count = sum(1 for s in latest_by_agent.values() if s.get("status") == "error")
    utilization = round((active_count / max(1, total_agents)) * 100, 1)
    avg_progress = _gauge_value([float(x.get("progress") or 0) for x in latest_by_agent.values()]) if latest_by_agent else 0.0
    avg_progress = round(max(0.0, min(100.0, avg_progress)), 1)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("총 시설", total_agents)
    with c2:
        st.metric("가동 중", active_count, delta=f"{utilization}% 가동률")
    with c3:
        st.metric("완료 누적", completed_count)
    with c4:
        st.metric("오류", error_count)
    with c5:
        st.metric("평균 진행률", f"{avg_progress}%")

    st.markdown("<div class='stat-box'><div class='stat-label'>타이쿤 미션: 한 번에 여러 팀 동시 가동 가능</div></div>", unsafe_allow_html=True)

    # 미션 라인 보드
    st.markdown("#### 🛰️ 연구원 팀 미션 라인")
    team_runs = _build_run_board_data(sessions)
    if not team_runs:
        st.info("상단 제어면 또는 `tools/dashboard/scripts/agent_teamctl.py`로 팀 미션을 생성하세요.")
    else:
        with st.container(border=True):
            run_cards = []
            for run in team_runs:
                chips = []
                for assignment in run["assignments"]:
                    status = str(assignment.get("status", "idle"))
                    if status == "completed":
                        css = "task-pill done"
                        status_icon = "✅"
                    elif status == "error":
                        css = "task-pill warn"
                        status_icon = "⚠️"
                    else:
                        css = "task-pill"
                        status_icon = "⚙️"
                    task_label = _safe_text(str(assignment.get("task", "작업 대기")), 24)
                    chips.append(f'<span class="{css}">{status_icon} {task_label}</span>')

                run_cards.append(
                    f"""
<div class='mission-card'>
    <div class='mission-name'>{_safe_text(run['mission'], 44)}</div>
    <div class='mission-meta'>팀: {run['team_run_label']} · 업데이트: {run['updated_label']} · 총 {run['total']}개 슬롯</div>
    <div class='progress-track'><div class='progress-fill' style='width: {run['progress_avg']}%; background: linear-gradient(90deg, #ffcc33, #ffdd66);'></div></div>
    <div class='mission-summary'>활성 {run['active']} / 완료 {run['completed']} / 오류 {run['error']} / 대기 {run['pending']} | 평균 {run['progress_avg']}%</div>
    <div>{''.join(chips)}</div>
</div>
"""
                )

            st.markdown(f"<div class='mission-board'>{''.join(run_cards)}</div>", unsafe_allow_html=True)

    st.markdown("---")

    # 연구소 시설 대시보드
    st.markdown("#### 🏭 시설 패널")
    facility_lines = ['<div class="facility-grid">']
    for dept_name, dept_info in DEPARTMENTS.items():
        dept_agents = dept_info["agents"]
        dept_active = 0
        dept_error = 0
        for agent_name in dept_agents:
            display = _get_agent_display(sessions, agent_name)
            if display.get("status") == "active":
                dept_active += 1
            if display.get("status") == "error":
                dept_error += 1

        facility_lines.append(
            f"""
<div class='facility-title'>{dept_info['icon']} {dept_name} (가동 {dept_active} / 오류 {dept_error})</div>
"""
        )
        for agent_name in dept_agents:
            display = _get_agent_display(sessions, agent_name)
            facility_lines.append(_render_facility_card(agent_name, display, dept_name))

    facility_lines.append("</div>")
    st.markdown("".join(facility_lines), unsafe_allow_html=True)

    # 실시간 활동 로그
    st.markdown("#### 📡 실시간 에이전트 활동 로그")
    log_html = _render_log_entries(sessions)
    st.markdown(f'<div class="log-container">{log_html}</div>', unsafe_allow_html=True)

    with st.expander("📋 세션 데이터 (JSON)"):
        if sessions:
            st.json(sessions)
        else:
            st.info("data/agent_sessions.jsonl 파일이 없거나 비어있습니다.")
        if corrupt_lines:
            st.caption(f"파싱 실패 라인 수: {corrupt_lines}")

    st.caption(f"연구소 업데이트: {time.strftime('%Y-%m-%d %H:%M:%S')}")
