from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord

from bot.views.thread_recommend_view import ThreadRecommendationView


class ThreadHygieneEngine:
    def __init__(self, timezone: str, config: dict) -> None:
        self.enabled = bool(config.get("enabled", True))
        self.message_threshold = int(config.get("message_threshold", 6))
        self.window_minutes = int(config.get("window_minutes", 10))
        self.min_unique_authors = int(config.get("min_unique_authors", 2))
        self.cooldown_minutes = int(config.get("cooldown_minutes", 20))
        self.exempt_channels = set(config.get("exempt_channels", []))
        self.tz = ZoneInfo(timezone)

        self._channel_events: dict[int, deque[tuple[datetime, int, int]]] = defaultdict(deque)
        self._last_notice_at: dict[int, datetime] = {}

    def _now(self) -> datetime:
        return datetime.now(self.tz)

    async def handle_message(self, message: discord.Message) -> None:
        if not self.enabled:
            return
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if isinstance(message.channel, discord.Thread):
            return
        if message.channel.name in self.exempt_channels:
            return

        now = self._now()
        window_start = now - timedelta(minutes=self.window_minutes)
        events = self._channel_events[message.channel.id]
        events.append((now, message.author.id, message.id))

        while events and events[0][0] < window_start:
            events.popleft()

        if len(events) < self.message_threshold:
            return

        unique_authors = len({author_id for _, author_id, _ in events})
        if unique_authors < self.min_unique_authors:
            return

        last_notice = self._last_notice_at.get(message.channel.id)
        if last_notice and now - last_notice < timedelta(minutes=self.cooldown_minutes):
            return

        target_message_id = events[-1][2]
        view = ThreadRecommendationView(target_message_id=target_message_id)
        await message.channel.send(
            "대화가 길어지고 있어요. 스레드로 전환하면 본문 채널이 깔끔해집니다.",
            view=view,
        )
        self._last_notice_at[message.channel.id] = now
