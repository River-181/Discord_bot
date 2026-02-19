from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import discord

from bot.services.event_reminder import EventReminderService
from bot.services.storage import DataFiles, StorageService


def _make_storage(tmp_path) -> StorageService:
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


@dataclass
class _FakeUser:
    id: int
    can_dm: bool = True
    bot: bool = False

    def __post_init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, text: str) -> None:
        if not self.can_dm:
            raise RuntimeError("dm blocked")
        self.messages.append(text)


class _FakeEvent:
    def __init__(
        self,
        *,
        event_id: int,
        name: str,
        start_time: datetime,
        users: list[_FakeUser],
        status: discord.EventStatus = discord.EventStatus.scheduled,
    ) -> None:
        self.id = event_id
        self.name = name
        self.start_time = start_time
        self.status = status
        self.url = f"https://discord.com/events/1401492009486651452/{event_id}"
        self._users = users

    async def users(self, *, limit=None, before=None, after=None, oldest_first=False):  # noqa: ANN001, ARG002
        for user in self._users:
            yield user


class _FakeTextChannel:
    def __init__(self, channel_id: int, name: str) -> None:
        self.id = channel_id
        self.name = name
        self.sent: list[str] = []

    async def send(self, text: str, allowed_mentions=None):  # noqa: ANN001, ARG002
        self.sent.append(text)


class _FakeGuild:
    def __init__(self, guild_id: int, text_channel: _FakeTextChannel, events: list[_FakeEvent]) -> None:
        self.id = guild_id
        self.text_channels = [text_channel]
        self._events = events

    async def fetch_scheduled_events(self, *, with_counts: bool = True):  # noqa: ARG002
        return self._events


class _FakeBot:
    def __init__(self, guild: _FakeGuild) -> None:
        self._guild = guild

    def get_guild(self, guild_id: int):
        if self._guild.id == guild_id:
            return self._guild
        return None


def test_chunk_mentions(tmp_path) -> None:
    service = EventReminderService(
        timezone="Asia/Seoul",
        config={"enabled": True, "max_mentions_per_message": 2},
        channels_config={"operation_briefing": "운영-브리핑"},
        storage=_make_storage(tmp_path),
    )
    chunks = service._chunk_mentions([5, 1, 2, 3, 4, 5], 2)  # type: ignore[attr-defined]
    assert chunks == [
        "<@1> <@2>",
        "<@3> <@4>",
        "<@5>",
    ]


def test_due_window_logic(tmp_path) -> None:
    service = EventReminderService(
        timezone="Asia/Seoul",
        config={"enabled": True, "reminder_minutes": 5},
        channels_config={"operation_briefing": "운영-브리핑"},
        storage=_make_storage(tmp_path),
    )
    now = datetime.now(UTC)
    due_event = _FakeEvent(event_id=1, name="due", start_time=now + timedelta(minutes=4), users=[])
    future_event = _FakeEvent(event_id=2, name="future", start_time=now + timedelta(minutes=8), users=[])
    past_event = _FakeEvent(event_id=3, name="past", start_time=now - timedelta(minutes=1), users=[])

    assert service._is_due(due_event, now) is True  # type: ignore[arg-type]
    assert service._is_due(future_event, now) is False  # type: ignore[arg-type]
    assert service._is_due(past_event, now) is False  # type: ignore[arg-type]


def test_scan_sends_channel_and_dm_with_idempotency(tmp_path) -> None:
    storage = _make_storage(tmp_path)
    service = EventReminderService(
        timezone="Asia/Seoul",
        config={
            "enabled": True,
            "reminder_minutes": 5,
            "reminder_channel": "운영-브리핑",
            "send_dm": True,
            "max_mentions_per_message": 2,
        },
        channels_config={"operation_briefing": "운영-브리핑"},
        storage=storage,
    )
    users = [_FakeUser(1001), _FakeUser(1002), _FakeUser(1003)]
    event = _FakeEvent(
        event_id=10,
        name="망상궤도-디스코드 미팅",
        start_time=datetime.now(UTC) + timedelta(minutes=4),
        users=users,
    )
    channel = _FakeTextChannel(3001, "운영-브리핑")
    guild = _FakeGuild(1401492009486651452, channel, [event])
    bot = _FakeBot(guild)

    with asyncio.Runner() as runner:
        first = runner.run(service.scan_and_send(bot=bot, guild_id=guild.id))
        second = runner.run(service.scan_and_send(bot=bot, guild_id=guild.id))

    assert first.scanned_events == 1
    assert first.due_events == 1
    assert first.channel_sent == 1
    assert first.dm_sent == 3
    assert first.dm_failed == 0
    assert len(channel.sent) == 2  # 본문 1 + 멘션 분할 1
    assert second.channel_sent == 0
    assert second.dm_sent == 0


def test_dm_failure_does_not_block_channel_alert(tmp_path) -> None:
    storage = _make_storage(tmp_path)
    service = EventReminderService(
        timezone="Asia/Seoul",
        config={
            "enabled": True,
            "reminder_minutes": 5,
            "reminder_channel": "운영-브리핑",
            "send_dm": True,
        },
        channels_config={"operation_briefing": "운영-브리핑"},
        storage=storage,
    )
    users = [_FakeUser(2001, can_dm=False)]
    event = _FakeEvent(
        event_id=11,
        name="dm-fail-event",
        start_time=datetime.now(UTC) + timedelta(minutes=4),
        users=users,
    )
    channel = _FakeTextChannel(3002, "운영-브리핑")
    guild = _FakeGuild(1401492009486651452, channel, [event])
    bot = _FakeBot(guild)

    with asyncio.Runner() as runner:
        result = runner.run(service.scan_and_send(bot=bot, guild_id=guild.id))

    assert result.channel_sent == 1
    assert result.dm_sent == 0
    assert result.dm_failed == 1
