from __future__ import annotations

from bot.services.ops_diagnostics import (
    build_curation_runtime,
    build_news_runtime,
    build_recent_failures,
)


def test_build_curation_runtime_counts_and_hook_ratio() -> None:
    submission_rows = [
        {
            "submission_id": "s1",
            "status": "pending",
            "classified_type": "link",
            "created_at": "2026-03-07T00:00:00Z",
        },
        {
            "submission_id": "s2",
            "status": "approved",
            "classified_type": "youtube",
            "created_at": "2026-03-07T01:00:00Z",
            "reviewed_at": "2026-03-07T02:00:00Z",
        },
    ]
    ops_rows = [
        {
            "event_type": "curation_approved",
            "occurred_at": "2026-03-07T02:00:00Z",
            "payload": {"hook_source": "persona"},
        },
        {
            "event_type": "curation_publish_failed",
            "occurred_at": "2026-03-07T03:00:00Z",
            "payload": {"error": "target_channel_missing"},
        },
    ]

    runtime = build_curation_runtime(submission_rows, ops_rows, timezone_name="Asia/Seoul")
    assert runtime["counts"]["pending"] == 1
    assert runtime["counts"]["approved"] == 1
    assert runtime["type_counts"]["link"] == 1
    assert runtime["hook_source_counts"]["persona"] == 1
    assert runtime["hook_persona_ratio"] == 100.0
    assert runtime["last_failure"] == "target_channel_missing"


def test_build_news_runtime_marks_warning_when_completed_with_errors() -> None:
    runtime = build_news_runtime(
        [{"run_at": "2026-03-07T08:00:00Z", "items_count": 12}],
        [
            {
                "event_type": "news_digest_completed",
                "occurred_at": "2026-03-07T08:01:00Z",
                "payload": {"errors": 2},
            }
        ],
        timezone_name="Asia/Seoul",
        morning_cron="0 8 * * *",
        evening_cron="0 18 * * 1-5",
    )
    assert runtime["last_result"] == "warning"
    assert runtime["last_items_count"] == 12
    assert runtime["next_run_at"] is not None


def test_build_recent_failures_filters_error_like_events() -> None:
    failures = build_recent_failures(
        [
            {
                "event_type": "music_command_failed",
                "occurred_at": "2026-03-07T09:00:00Z",
                "payload": {"command_name": "music_play", "error": "ffmpeg_missing"},
            },
            {
                "event_type": "news_digest_completed",
                "occurred_at": "2026-03-07T08:00:00Z",
                "payload": {"errors": 0},
            },
        ],
        "Asia/Seoul",
        limit=5,
    )
    assert len(failures) == 1
    assert failures[0]["event_type"] == "music_command_failed"
