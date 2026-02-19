from __future__ import annotations

from typing import Any
import streamlit as st


def _build_message_link(guild_id: str | None, channel_id: str | int | None, message_id: str | int | None) -> str:
    if not (guild_id and channel_id and message_id):
        return ""
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def render_summaries(payload: dict[str, Any], guild_id: str | None, event_url_prefix: bool = True) -> None:
    _ = event_url_prefix
    rows = payload.get("rows", [])
    st.subheader("요약 기록")
    if not rows:
        st.caption("요약 데이터가 없습니다.")
        return

    table_rows = []
    for row in rows:
        channel_id = row.get("source_channel_id")
        message_id = row.get("output_message_id")
        summary_source_url = row.get("context_url")
        link = _build_message_link(guild_id, channel_id, message_id)
        if not link and summary_source_url:
            link = str(summary_source_url)

        table_rows.append(
            {
                "id": row.get("summary_id", "-"),
                "범위": row.get("scope", "-"),
                "모델": row.get("model", "-"),
                "fallback": row.get("fallback_used", False),
                "생성": row.get("created_at", "-"),
                "원문": link or "-",
            }
        )
    st.dataframe(table_rows, use_container_width=True, hide_index=True)


def render_decisions(payload: dict[str, Any]) -> None:
    rows = payload.get("rows", [])
    st.subheader("결정 목록")
    if not rows:
        st.caption("결정 데이터가 없습니다.")
        return

    table_rows = []
    for row in rows:
        context_url = row.get("context_url")
        link = str(context_url) if context_url else ""
        if not link:
            channel_id = row.get("source_channel_id")
            message_id = row.get("source_message_id")
            guild_id = row.get("source_guild_id") or row.get("guild_id")
            link = _build_message_link(guild_id, channel_id, message_id)
        table_rows.append(
            {
                "id": row.get("decision_id", "-")[:8],
                "제목": row.get("title", "-"),
                "담당": row.get("owner", "-"),
                "마감": row.get("due_date", "-"),
                "상태": row.get("status", "-"),
                "채널": row.get("source_channel_id") or "-",
                "링크": link or "-",
                "생성": row.get("created_at", "-"),
            }
        )
    st.dataframe(table_rows, use_container_width=True, hide_index=True)


def render_summaries_decisions(
    summaries_payload: dict[str, Any],
    decisions_payload: dict[str, Any],
    guild_id: str | None = None,
    target_guild_id: str | None = None,
    **_: Any,
) -> None:
    if guild_id is None:
        guild_id = target_guild_id
    tab_summary, tab_decision = st.tabs(["요약", "결정"])
    with tab_summary:
        render_summaries(summaries_payload, guild_id)
    with tab_decision:
        render_decisions(decisions_payload)
