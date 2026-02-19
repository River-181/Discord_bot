from __future__ import annotations

from typing import Any
import streamlit as st


def render_overview(payload: dict[str, Any], target_guild_id: str | None) -> None:
    if not payload:
        st.info("요약 데이터를 가져오지 못했습니다.")
        return

    bot_state = payload.get("bot_state", {})
    recent = payload.get("recent_24h", {})
    pending = payload.get("recent_unresolved_decisions", [])

    st.subheader("실시간 개요")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "봇 연결",
        "running" if bot_state.get("running") else bot_state.get("status", "unknown"),
    )

    c2.metric("워룸(활성)", str(payload.get("active_warrooms", 0)))
    c3.metric("경고(24h)", str(recent.get("warnings", 0)))
    c4.metric("아카이브(24h)", str(recent.get("archived", 0)))

    st.write(
        f"PID: `{bot_state.get('pid', '-')}` / 점검시각: `{bot_state.get('checked_at', '-')}` "
        f"/ Guild: `{target_guild_id or '-'}`"
    )

    if recent.get("errors"):
        st.warning(f"오류 이벤트: {recent.get('errors')} 건")
    else:
        st.success("최근 24시간 오류 없음")

    st.subheader("결정 미반영 추정 Top3")
    if not pending:
        st.caption("최근 미반영 추정 결정 항목이 없습니다.")
        return

    table_rows = []
    for item in pending[:3]:
        table_rows.append(
            {
                "제목": item.get("title", "-"),
                "담당": item.get("owner", "-"),
                "마감": item.get("due_date", "-"),
                "상태": item.get("status", "open"),
                "생성": item.get("created_at", "-"),
            }
        )
    st.table(table_rows)
