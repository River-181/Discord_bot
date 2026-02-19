from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord


class DeepWorkGuard:
    def __init__(self, timezone: str, config: dict) -> None:
        self.enabled = bool(config.get("enabled", True))
        self.weekdays = set(int(x) for x in config.get("weekdays", [0, 1, 2, 3, 4]))
        self.start_hour = int(config.get("start_hour", 14))
        self.end_hour = int(config.get("end_hour", 16))
        self.notice_cooldown_minutes = int(config.get("notice_cooldown_minutes", 30))
        self.urgent_keywords = [str(x).lower() for x in config.get("urgent_keywords", [])]
        self.allowlist_channels = set(config.get("allowlist_channels", []))
        self.exempt_roles = set(config.get("exempt_roles", []))
        self.tz = ZoneInfo(timezone)

        self._last_notice_by_channel: dict[int, datetime] = {}

    def _now(self) -> datetime:
        return datetime.now(self.tz)

    def _in_deep_work_window(self, now: datetime) -> bool:
        if now.weekday() not in self.weekdays:
            return False
        return self.start_hour <= now.hour < self.end_hour

    def _author_is_exempt(self, member: discord.Member | discord.User) -> bool:
        if not isinstance(member, discord.Member):
            return False
        role_names = {role.name for role in member.roles}
        return bool(role_names & self.exempt_roles)

    def _is_urgent(self, content: str) -> bool:
        lower = content.lower()
        return any(keyword in lower for keyword in self.urgent_keywords)

    def _has_mentions(self, message: discord.Message) -> bool:
        if message.mention_everyone:
            return True
        if message.role_mentions:
            return True
        return any(not user.bot for user in message.mentions)

    async def handle_message(self, message: discord.Message) -> None:
        if not self.enabled:
            return
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if message.channel.name in self.allowlist_channels:
            return
        if self._author_is_exempt(message.author):
            return
        if not self._has_mentions(message):
            return
        if self._is_urgent(message.content):
            return

        now = self._now()
        if not self._in_deep_work_window(now):
            return

        last_notice = self._last_notice_by_channel.get(message.channel.id)
        if last_notice and now - last_notice < timedelta(minutes=self.notice_cooldown_minutes):
            return

        await message.channel.send(
            "현재 Deep Work 시간(평일 14:00~16:00, Asia/Seoul)입니다. "
            "비긴급 내용은 비동기로 남겨주세요. 긴급 건은 `운영-브리핑` 채널을 사용해 주세요."
        )
        self._last_notice_by_channel[message.channel.id] = now
