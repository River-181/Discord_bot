from __future__ import annotations

import asyncio
from pathlib import Path

import discord

from bot.services.news import NewsService, build_google_news_rss_url
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


def test_build_google_news_rss_url() -> None:
    url = build_google_news_rss_url("AI agent OR MCP")
    assert "news.google.com/rss/search?q=" in url
    assert "hl=ko" in url
    assert "gl=KR" in url


def test_parse_rss_basic(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    service = NewsService(
        timezone="Asia/Seoul",
        channels_config={},
        news_config={"enabled": True, "topics": [{"name": "t", "query": "q"}]},
        storage=storage,
        gemini_api_key=None,
    )

    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Hello World - Example</title>
      <link>https://example.com/a</link>
      <pubDate>Tue, 18 Feb 2026 00:00:00 GMT</pubDate>
      <description><![CDATA[<b>desc</b> text]]></description>
    </item>
  </channel>
</rss>
"""
    entries = service.parse_rss(xml)
    assert len(entries) == 1
    assert "title" in entries[0]
    assert "link" in entries[0]


class _FakeThread:
    def __init__(self) -> None:
        self.sent_embeds: list[discord.Embed] = []
        self.jump_url = "https://discord.com/channels/thread"

    async def send(self, *, embed: discord.Embed) -> None:
        self.sent_embeds.append(embed)


class _FakeMessage:
    def __init__(self, *, allow_thread: bool = True) -> None:
        self.allow_thread = allow_thread
        self.id = 101
        self.jump_url = "https://discord.com/channels/msg/101"
        self.thread = _FakeThread()

    async def create_thread(self, name: str, auto_archive_duration: int):  # noqa: ARG002
        if not self.allow_thread:
            raise RuntimeError("thread blocked")
        return self.thread


class _FakeChannel:
    def __init__(self, *, allow_thread: bool = True) -> None:
        self.allow_thread = allow_thread
        self.sent_embeds: list[discord.Embed] = []
        self.last_message: _FakeMessage | None = None

    async def send(self, *, embed: discord.Embed) -> _FakeMessage:
        self.sent_embeds.append(embed)
        msg = _FakeMessage(allow_thread=self.allow_thread)
        self.last_message = msg
        return msg


def test_post_paginated_digest_thread_for_page_2_plus(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    service = NewsService(
        timezone="Asia/Seoul",
        channels_config={},
        news_config={"enabled": True, "topics": [{"name": "t", "query": "q"}]},
        storage=storage,
        gemini_api_key=None,
    )
    channel = _FakeChannel(allow_thread=True)
    embeds = [
        discord.Embed(title="p1"),
        discord.Embed(title="p2"),
        discord.Embed(title="p3"),
    ]

    with asyncio.Runner() as runner:
        message, pages_in_thread, thread_jump = runner.run(
            service._post_paginated_digest(digest_channel=channel, embeds=embeds)
        )

    assert message is not None
    assert len(channel.sent_embeds) == 1
    assert pages_in_thread == 2
    assert thread_jump == "https://discord.com/channels/thread"
    assert channel.last_message is not None
    assert len(channel.last_message.thread.sent_embeds) == 2


def test_post_paginated_digest_fallback_to_channel_when_thread_fails(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    service = NewsService(
        timezone="Asia/Seoul",
        channels_config={},
        news_config={"enabled": True, "topics": [{"name": "t", "query": "q"}]},
        storage=storage,
        gemini_api_key=None,
    )
    channel = _FakeChannel(allow_thread=False)
    embeds = [
        discord.Embed(title="p1"),
        discord.Embed(title="p2"),
        discord.Embed(title="p3"),
    ]

    with asyncio.Runner() as runner:
        message, pages_in_thread, thread_jump = runner.run(
            service._post_paginated_digest(digest_channel=channel, embeds=embeds)
        )

    assert message is not None
    assert len(channel.sent_embeds) == 3
    assert pages_in_thread == 0
    assert thread_jump is None
