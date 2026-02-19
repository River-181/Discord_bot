from __future__ import annotations

from pathlib import Path

from bot.services.news import NewsService
from bot.services.storage import DataFiles, StorageService


def _make_storage(tmp_path: Path) -> StorageService:
    files = DataFiles(
        decisions="decisions.jsonl",
        warrooms="warrooms.jsonl",
        summaries="summaries.jsonl",
        ops_events="ops_events.ndjson",
        news_items="news_items.jsonl",
        news_digests="news_digests.jsonl",
        snapshots_dir="snapshots",
    )
    return StorageService(base_dir=tmp_path, files=files)


def _make_service(tmp_path: Path) -> NewsService:
    storage = _make_storage(tmp_path)
    return NewsService(
        timezone="Asia/Seoul",
        channels_config={},
        news_config={"enabled": True, "topics": [{"name": "Agent Radar", "query": "q"}]},
        storage=storage,
        gemini_api_key=None,
    )


def test_topic_fields_are_split_without_topic_level_ellipsis(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    bullets = [f"• 항목{i} " + ("x" * 80) for i in range(30)]
    embeds, stats = service._build_embeds_paginated(
        kind_label="manual",
        window_hours=24,
        bullets_by_topic={"Agent Radar": bullets},
        selected_count=len(bullets),
        candidate_count=len(bullets),
        per_topic_limit=30,
        max_total_items=30,
    )

    field_names = [field.name for embed in embeds for field in embed.fields]
    assert any(name.endswith("(계속)") for name in field_names)

    for embed in embeds:
        for field in embed.fields:
            assert len(field.value) <= 1024
            assert not field.value.endswith("\n...")

    assert stats["line_truncated_count"] == 0


def test_embed_pagination_when_field_count_exceeds_25(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    bullets_by_topic = {f"Topic {i}": [f"• line {i}"] for i in range(30)}
    embeds, stats = service._build_embeds_paginated(
        kind_label="manual",
        window_hours=12,
        bullets_by_topic=bullets_by_topic,
        selected_count=30,
        candidate_count=30,
        per_topic_limit=30,
        max_total_items=30,
    )

    assert len(embeds) >= 2
    for embed in embeds:
        assert len(embed.fields) <= 25
    assert stats["embed_count"] == len(embeds)


def test_extreme_single_line_gets_truncated_with_tag(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    very_long_line = "• " + ("y" * 3000)
    embeds, stats = service._build_embeds_paginated(
        kind_label="manual",
        window_hours=12,
        bullets_by_topic={"Agent Radar": [very_long_line]},
        selected_count=1,
        candidate_count=1,
        per_topic_limit=1,
        max_total_items=1,
    )

    values = [field.value for embed in embeds for field in embed.fields]
    assert any("(길이 제한)" in value for value in values)
    assert stats["line_truncated_count"] >= 1
