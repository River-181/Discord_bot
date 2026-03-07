from __future__ import annotations

from typing import Any
import time
import os

import httpx
import streamlit as st

from tools.dashboard.frontend.components.overview import render_overview
from tools.dashboard.frontend.components.operations import render_operations
from tools.dashboard.frontend.components.warrooms import render_warrooms
from tools.dashboard.frontend.components.summaries_decisions import render_summaries_decisions
from tools.dashboard.frontend.components.events import render_events
from tools.dashboard.frontend.components.agent_lab import render_agent_lab


st.set_page_config(page_title="망상궤도 운영 대시보드", layout="wide")


BACKEND_URL = (
    os.getenv("DASHBOARD_BACKEND_URL", "http://127.0.0.1:8080")
)


def _backend_url() -> str:
    return os.getenv("DASHBOARD_BACKEND_URL", BACKEND_URL)


def _fetch(path: str, params: dict[str, Any] | None = None, method: str = "get") -> dict[str, Any]:
    url = f"{_backend_url()}{path}"
    try:
        with httpx.Client(timeout=8) as client:
            if method == "post":
                response = client.post(url, params=params)
            else:
                response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        raise RuntimeError(f"백엔드 호출 실패: {path} ({exc})")


def _parse_int_or_default(value: str | None, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _to_hours(days: int) -> int:
    return days * 24


def main() -> None:
    st.title("망상궤도 비서 운영 가시화")
    st.caption("Discord 운영 상태, 워룸, 요약/결정, 이벤트를 한 화면에서 확인합니다.")

    # 15초 자동 새로고침
    st.markdown(
        '<meta http-equiv="refresh" content="15"/>'
        '<style> .main .block-container {padding-top: 1rem;} </style>',
        unsafe_allow_html=True,
    )

    # 탭 구성
    tab_dashboard, tab_lab = st.tabs(["📊 운영 대시보드", "🏭 연구소 타이쿤"])

    with tab_lab:
        render_agent_lab()

    # 사이드바 (탭 바깥에 그대로 유지)
    with st.sidebar:
        st.header("조회 필터")

        st.toggle("자동 새로고침", value=True, disabled=True)

        warroom_status = st.selectbox("워룸 상태", ["all", "active", "archived"], index=0)
        warroom_limit = st.select_slider("워룸 최대 표시 수", options=[20, 50, 100, 200], value=100)

        summary_scope = st.selectbox("요약 범위", ["all", "thread", "channel"], index=0)
        summary_limit = _parse_int_or_default(st.text_input("요약 최대 표시 수", "50"), 50)

        decision_status = st.selectbox("결정 상태", ["all", "open", "closed"], index=1)
        decision_limit = _parse_int_or_default(st.text_input("결정 최대 표시 수", "100"), 100)

        event_filter = st.selectbox("이벤트 타입", ["all", "scheduled_inactivity_scan", "warning", "error"], index=0)
        event_limit = _parse_int_or_default(st.text_input("이벤트 최대 표시 수", "200"), 200)

        metric_hours = st.selectbox("빠른 지표 기간", ["24h", "7d", "30d"], index=0)
        metric_hours_map = {
            "24h": 24,
            "7d": _to_hours(7),
            "30d": _to_hours(30),
        }

        st.divider()
        if st.button("지금 새로고침"):
            st.rerun()

    with tab_dashboard:
        try:
            _fetch("/api/runtime/refresh", method="post")
            health = _fetch("/api/health")
        except Exception as exc:
            st.error(str(exc))
            st.stop()

        st.sidebar.success(f"Health: {'OK' if health.get('ok') else 'WARN'}")
        st.sidebar.metric("파일 결함 라인", health.get("corrupt_lines", 0))
        if health.get("data_missing"):
            st.sidebar.warning("데이터 파일이 누락되어 있습니다.")
        if not health.get("jsonl_ok"):
            st.sidebar.warning("JSONL 파싱/정합성 점검이 필요합니다.")

        runtime_state = health.get("runtime_state", {})
        if runtime_state.get("state") not in {"running", "unknown"}:
            st.sidebar.error("런타임 상태: 중단 또는 미연결")
        else:
            st.sidebar.success(f"런타임 상태: {runtime_state.get('state')}")

        overview = _fetch("/api/overview")
        ops_overview = _fetch("/api/ops/overview")
        metrics = _fetch("/api/metrics/quick", params={"hours": metric_hours_map[metric_hours]})
        warrooms = _fetch("/api/warrooms", params={"status": warroom_status, "limit": warroom_limit})
        summaries = _fetch("/api/summaries", params={"scope": summary_scope, "limit": summary_limit})
        decisions = _fetch(
            "/api/decisions",
            params={
                "status": decision_status,
                "limit": decision_limit,
            },
        )
        events = _fetch(
            "/api/events",
            params={
                "event_type": event_filter,
                "limit": event_limit,
            },
        )

        target_guild_id = overview.get("target_guild_id")

        render_overview(overview, target_guild_id=target_guild_id)
        st.markdown("---")
        render_operations(ops_overview)

        st.markdown("---")
        st.subheader("빠른 지표")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("요약 건수", metrics.get("summaries", 0))
        c2.metric("결정 건수", metrics.get("decisions", 0))
        c3.metric("경고/전환 건수", metrics.get("warnings", 0))
        c4.metric("Deep Work 개입", metrics.get("deep_work_interventions", 0))

        render_warrooms(warrooms)
        st.markdown("---")
        render_summaries_decisions(summaries, decisions, target_guild_id)
        st.markdown("---")
        render_events(events, event_filter)

        st.caption(f"업데이트: {time.strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
