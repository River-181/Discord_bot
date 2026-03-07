from __future__ import annotations

from typing import Any

import streamlit as st


def _status_badge(value: str) -> str:
    normalized = str(value or "-").lower()
    if normalized in {"ok", "active"}:
        return "정상"
    if normalized == "warning":
        return "주의"
    if normalized == "error":
        return "장애"
    if normalized in {"idle", "never"}:
        return "대기"
    return str(value or "-")


def render_operations(payload: dict[str, Any]) -> None:
    cards = payload.get("cards", {})
    failures = payload.get("recent_failures", [])
    if not cards:
        st.info("운영 상태판 데이터를 가져오지 못했습니다.")
        return

    st.subheader("기능별 운영 상태")
    c1, c2, c3, c4 = st.columns(4)

    news = cards.get("news", {})
    c1.metric("뉴스", _status_badge(news.get("last_result")), news.get("last_run_at") or "-")
    c1.caption(f"다음 실행: {news.get('next_run_at') or '-'}")

    curation = cards.get("curation", {})
    c2.metric("큐레이션", str((curation.get("counts") or {}).get("pending", 0)), "pending")
    c2.caption(
        f"persona 비율 {curation.get('hook_persona_ratio', 0)}% / oldest {curation.get('pending_oldest_age_hours') or '-'}h"
    )

    music = cards.get("music", {})
    c3.metric("음악", _status_badge(music.get("last_result")), f"sessions {music.get('active_sessions', 0)}")
    c3.caption(f"최근 실패: {music.get('last_failure_at') or '-'}")

    event_reminder = cards.get("event_reminder", {})
    c4.metric("이벤트", _status_badge(event_reminder.get("last_result")), event_reminder.get("last_run_at") or "-")
    c4.caption(f"다음 실행: {event_reminder.get('next_run_at') or '-'}")

    st.subheader("최근 실패")
    if not failures:
        st.caption("최근 실패 이벤트가 없습니다.")
        return

    rows = [
        {
            "시간": row.get("occurred_at", "-"),
            "이벤트": row.get("event_type", "-"),
            "명령": row.get("command_name") or "-",
            "상세": row.get("detail", "-"),
        }
        for row in failures
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
