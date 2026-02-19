from __future__ import annotations

from typing import Any
import streamlit as st


def render_warrooms(payload: dict[str, Any]) -> None:
    rows = payload.get("rows", [])
    st.subheader("워룸")
    if not rows:
        st.info("표시할 워룸 데이터가 없습니다.")
        return

    table_rows = [
        {
            "워룸ID": row.get("warroom_id", "-")[:8],
            "이름": row.get("name", "-"),
            "영역": row.get("zone", "-"),
            "상태": row.get("state", "-"),
            "마지막 활동": row.get("last_activity_at", "-"),
            "경고 예정": row.get("warning_at") or "-",
            "아카이브": row.get("archived_at") or "-",
        }
        for row in rows
    ]
    st.dataframe(table_rows, use_container_width=True, hide_index=True)
