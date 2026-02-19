from __future__ import annotations

from typing import Any
import streamlit as st


def render_events(payload: dict[str, Any], filter_type: str) -> None:
    rows = payload.get("rows", [])
    st.subheader(f"Ops 이벤트 (필터: {filter_type})")
    if not rows:
        st.caption("이벤트 데이터가 없습니다.")
        return

    table_rows = []
    for row in rows:
        row_payload = row.get("payload")
        if isinstance(row_payload, dict):
            payload_text = ", ".join(f"{k}={v}" for k, v in row_payload.items())
        else:
            payload_text = str(row_payload or "")
        table_rows.append(
            {
                "시간": row.get("occurred_at", "-"),
                "이벤트": row.get("event_type", "-"),
                "상세": payload_text or "-",
            }
        )
    st.dataframe(table_rows, use_container_width=True, hide_index=True)
