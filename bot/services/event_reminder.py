from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import discord

from bot.services.retry import retry_discord_call
from bot.services.storage import StorageService
from bot.utils import find_text_channel_by_name


def _iso_utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class EventReminderScanResult:
    scanned_events: int
    due_events: int
    channel_sent: int
    dm_sent: int
    dm_failed: int
    errors: int
    started_at: str
    completed_at: str


class EventReminderService:
    def __init__(
        self,
        *,
        timezone: str,
        config: dict[str, Any] | None,
        channels_config: dict[str, str],
        storage: StorageService,
    ) -> None:
        cfg = config or {}
        self.tz = ZoneInfo(timezone)
        self.config = cfg
        self.channels_config = channels_config
        self.storage = storage

        self._last_scan: dict[str, Any] = {}

    def diagnostics(self) -> dict[str, Any]:
        cfg = self._current_config()
        return {
            "enabled": cfg["enabled"],
            "reminder_minutes": cfg["reminder_minutes"],
            "scan_cron": cfg["scan_cron"],
            "reminder_channel": cfg["reminder_channel"],
            "mention_mode": cfg["mention_mode"],
            "send_dm": cfg["send_dm"],
            "max_mentions_per_message": cfg["max_mentions_per_message"],
            "last_scan": dict(self._last_scan),
        }

    def update_config(
        self,
        *,
        enabled: bool | None = None,
        reminder_minutes: int | None = None,
        send_dm: bool | None = None,
    ) -> dict[str, Any]:
        if reminder_minutes is not None and reminder_minutes != 5:
            raise ValueError("Phase 1에서는 reminder_minutes=5만 허용됩니다.")
        if enabled is not None:
            self.config["enabled"] = bool(enabled)
        if reminder_minutes is not None:
            self.config["reminder_minutes"] = int(reminder_minutes)
        if send_dm is not None:
            self.config["send_dm"] = bool(send_dm)
        return self.diagnostics()

    def _current_config(self) -> dict[str, Any]:
        reminder_channel = str(self.config.get("reminder_channel", "")).strip()
        if not reminder_channel:
            reminder_channel = str(self.channels_config.get("operation_briefing", "")).strip()
        return {
            "enabled": bool(self.config.get("enabled", False)),
            "reminder_minutes": int(self.config.get("reminder_minutes", 5) or 5),
            "scan_cron": str(self.config.get("scan_cron", "*/1 * * * *")),
            "reminder_channel": reminder_channel,
            "mention_mode": str(self.config.get("mention_mode", "event_subscribers_plus_here")),
            "send_dm": bool(self.config.get("send_dm", True)),
            "max_mentions_per_message": max(1, int(self.config.get("max_mentions_per_message", 20) or 20)),
        }

    @staticmethod
    def _event_status_name(event: discord.ScheduledEvent) -> str:
        status = getattr(event, "status", None)
        if status is None:
            return ""
        name = getattr(status, "name", None)
        if isinstance(name, str):
            return name.lower()
        return str(status).split(".")[-1].lower()

    @staticmethod
    def _event_start_at(event: discord.ScheduledEvent) -> datetime | None:
        start = getattr(event, "start_time", None) or getattr(event, "scheduled_start_time", None)
        if start is None:
            return None
        if start.tzinfo is None:
            return start.replace(tzinfo=UTC)
        return start.astimezone(UTC)

    def _is_due(self, event: discord.ScheduledEvent, now_utc: datetime) -> bool:
        start = self._event_start_at(event)
        if start is None:
            return False
        seconds = (start - now_utc).total_seconds()
        reminder_seconds = self._current_config()["reminder_minutes"] * 60
        return 0 < seconds <= reminder_seconds

    def _format_kst(self, dt: datetime | None) -> str:
        if not dt:
            return "-"
        local = dt.astimezone(self.tz).replace(microsecond=0)
        return local.strftime("%Y-%m-%d %H:%M %Z")

    @staticmethod
    def _event_url(guild_id: int, event: discord.ScheduledEvent) -> str:
        url = str(getattr(event, "url", "") or "").strip()
        if url:
            return url
        return f"https://discord.com/events/{guild_id}/{event.id}"

    async def _event_users(self, event: discord.ScheduledEvent) -> list[discord.abc.User]:
        users: list[discord.abc.User] = []
        async for user in event.users(limit=None):
            if getattr(user, "bot", False):
                continue
            users.append(user)
        return users

    @staticmethod
    def _chunk_mentions(user_ids: list[int], chunk_size: int) -> list[str]:
        if not user_ids:
            return []
        unique_ids = sorted(set(user_ids))
        chunks: list[str] = []
        for i in range(0, len(unique_ids), chunk_size):
            part = unique_ids[i : i + chunk_size]
            chunks.append(" ".join(f"<@{uid}>" for uid in part))
        return chunks

    def _channel_key(self, guild_id: int, event: discord.ScheduledEvent, start_at: datetime | None) -> str:
        start_iso = start_at.isoformat(timespec="seconds").replace("+00:00", "Z") if start_at else "unknown"
        return f"event_reminder:channel:{guild_id}:{event.id}:{start_iso}"

    def _dm_key(self, guild_id: int, event: discord.ScheduledEvent, start_at: datetime | None, user_id: int) -> str:
        start_iso = start_at.isoformat(timespec="seconds").replace("+00:00", "Z") if start_at else "unknown"
        return f"event_reminder:dm:{guild_id}:{event.id}:{start_iso}:{user_id}"

    async def _send_channel_reminder(
        self,
        *,
        guild: discord.Guild,
        reminder_channel: discord.TextChannel,
        event: discord.ScheduledEvent,
        subscribers: list[discord.abc.User],
    ) -> bool:
        cfg = self._current_config()
        start_at = self._event_start_at(event)
        channel_key = self._channel_key(guild.id, event, start_at)
        if self.storage.has_idempotency_key(channel_key):
            return False

        event_url = self._event_url(guild.id, event)
        mentions = self._chunk_mentions(
            [user.id for user in subscribers],
            cfg["max_mentions_per_message"],
        )
        mention_block = "@here"
        if mentions:
            mention_block = f"{mention_block} {mentions[0]}"

        base_message = "\n".join(
            [
                f"⏰ 5분 전: **{event.name}**",
                f"시작시각(KST): {self._format_kst(start_at)}",
                f"이벤트 링크: {event_url}",
                mention_block,
            ]
        )
        allowed_mentions = discord.AllowedMentions(
            everyone=True,
            users=True,
            roles=False,
            replied_user=False,
        )
        await retry_discord_call(
            lambda: reminder_channel.send(base_message, allowed_mentions=allowed_mentions)
        )

        if len(mentions) > 1:
            for idx, chunk in enumerate(mentions[1:], start=2):
                await retry_discord_call(
                    lambda idx=idx, chunk=chunk: reminder_channel.send(
                        f"참가자 멘션 {idx}/{len(mentions)}\n{chunk}",
                        allowed_mentions=allowed_mentions,
                    )
                )

        await self.storage.append_ops_event(
            "event_reminder_channel_sent",
            {
                "guild_id": guild.id,
                "channel_id": reminder_channel.id,
                "user_id": None,
                "command_name": "event_reminder_scan",
                "event_id": event.id,
                "event_name": event.name,
                "subscriber_count": len(subscribers),
                "event_url": event_url,
            },
            idempotency_key=channel_key,
        )
        return True

    async def _send_dm_reminders(
        self,
        *,
        guild: discord.Guild,
        event: discord.ScheduledEvent,
        subscribers: list[discord.abc.User],
    ) -> tuple[int, int]:
        start_at = self._event_start_at(event)
        event_url = self._event_url(guild.id, event)
        dm_sent = 0
        dm_failed = 0
        for user in subscribers:
            key = self._dm_key(guild.id, event, start_at, user.id)
            if self.storage.has_idempotency_key(key):
                continue
            text = "\n".join(
                [
                    f"⏰ 5분 전 알림: {event.name}",
                    f"시작시각(KST): {self._format_kst(start_at)}",
                    f"이벤트 링크: {event_url}",
                ]
            )
            try:
                await retry_discord_call(lambda: user.send(text))
                dm_sent += 1
                await self.storage.append_ops_event(
                    "event_reminder_dm_sent",
                    {
                        "guild_id": guild.id,
                        "channel_id": None,
                        "user_id": user.id,
                        "command_name": "event_reminder_scan",
                        "event_id": event.id,
                        "event_name": event.name,
                        "event_url": event_url,
                    },
                    idempotency_key=key,
                )
            except Exception as exc:
                dm_failed += 1
                await self.storage.append_ops_event(
                    "event_reminder_dm_failed",
                    {
                        "guild_id": guild.id,
                        "channel_id": None,
                        "user_id": user.id,
                        "command_name": "event_reminder_scan",
                        "event_id": event.id,
                        "event_name": event.name,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                    idempotency_key=key,
                )
        return (dm_sent, dm_failed)

    async def scan_and_send(
        self,
        *,
        bot: discord.Client,
        guild_id: int | None,
    ) -> EventReminderScanResult:
        started_at = _iso_utc_now()
        await self.storage.append_ops_event(
            "event_reminder_scan_started",
            {
                "guild_id": guild_id,
                "channel_id": None,
                "user_id": None,
                "command_name": "event_reminder_scan",
                "result": "started",
            },
        )

        cfg = self._current_config()
        scanned_events = 0
        due_events = 0
        channel_sent = 0
        dm_sent = 0
        dm_failed = 0
        errors = 0

        if not cfg["enabled"] or guild_id is None:
            completed_at = _iso_utc_now()
            result = EventReminderScanResult(
                scanned_events=0,
                due_events=0,
                channel_sent=0,
                dm_sent=0,
                dm_failed=0,
                errors=0,
                started_at=started_at,
                completed_at=completed_at,
            )
            self._last_scan = {
                "enabled": cfg["enabled"],
                "scan_started_at": started_at,
                "scan_completed_at": completed_at,
                "scanned_events": result.scanned_events,
                "due_events": result.due_events,
                "channel_sent": result.channel_sent,
                "dm_sent": result.dm_sent,
                "dm_failed": result.dm_failed,
                "errors": result.errors,
            }
            await self.storage.append_ops_event(
                "event_reminder_scan_completed",
                {
                    "guild_id": guild_id,
                    "channel_id": None,
                    "user_id": None,
                    "command_name": "event_reminder_scan",
                    "result": "disabled_or_missing_guild",
                    **self._last_scan,
                },
            )
            return result

        guild = bot.get_guild(int(guild_id))
        if guild is None:
            errors += 1
            await self.storage.append_ops_event(
                "event_reminder_error",
                {
                    "guild_id": guild_id,
                    "channel_id": None,
                    "user_id": None,
                    "command_name": "event_reminder_scan",
                    "error": "guild_not_found",
                },
            )
            completed_at = _iso_utc_now()
            result = EventReminderScanResult(
                scanned_events=0,
                due_events=0,
                channel_sent=0,
                dm_sent=0,
                dm_failed=0,
                errors=errors,
                started_at=started_at,
                completed_at=completed_at,
            )
            self._last_scan = {
                "enabled": cfg["enabled"],
                "scan_started_at": started_at,
                "scan_completed_at": completed_at,
                "scanned_events": result.scanned_events,
                "due_events": result.due_events,
                "channel_sent": result.channel_sent,
                "dm_sent": result.dm_sent,
                "dm_failed": result.dm_failed,
                "errors": result.errors,
            }
            await self.storage.append_ops_event(
                "event_reminder_scan_completed",
                {
                    "guild_id": guild_id,
                    "channel_id": None,
                    "user_id": None,
                    "command_name": "event_reminder_scan",
                    "result": "guild_not_found",
                    **self._last_scan,
                },
            )
            return result

        reminder_channel = find_text_channel_by_name(guild, cfg["reminder_channel"]) if cfg["reminder_channel"] else None
        if reminder_channel is None:
            errors += 1
            await self.storage.append_ops_event(
                "event_reminder_error",
                {
                    "guild_id": guild.id,
                    "channel_id": None,
                    "user_id": None,
                    "command_name": "event_reminder_scan",
                    "error": "reminder_channel_not_found",
                    "reminder_channel": cfg["reminder_channel"],
                },
                idempotency_key=f"event_reminder:missing_channel:{guild.id}:{cfg['reminder_channel']}",
            )

        now_utc = datetime.now(UTC)
        events = await guild.fetch_scheduled_events(with_counts=True)
        scanned_events = len(events)

        for event in events:
            if self._event_status_name(event) != "scheduled":
                continue
            if not self._is_due(event, now_utc):
                continue
            due_events += 1
            try:
                subscribers = await self._event_users(event)
            except Exception as exc:
                errors += 1
                await self.storage.append_ops_event(
                    "event_reminder_error",
                    {
                        "guild_id": guild.id,
                        "channel_id": None,
                        "user_id": None,
                        "command_name": "event_reminder_scan",
                        "event_id": event.id,
                        "event_name": event.name,
                        "error": f"subscriber_fetch_failed:{type(exc).__name__}: {exc}",
                    },
                )
                subscribers = []

            try:
                if reminder_channel is not None:
                    sent = await self._send_channel_reminder(
                        guild=guild,
                        reminder_channel=reminder_channel,
                        event=event,
                        subscribers=subscribers,
                    )
                    if sent:
                        channel_sent += 1
            except Exception as exc:
                errors += 1
                await self.storage.append_ops_event(
                    "event_reminder_error",
                    {
                        "guild_id": guild.id,
                        "channel_id": reminder_channel.id if reminder_channel else None,
                        "user_id": None,
                        "command_name": "event_reminder_scan",
                        "event_id": event.id,
                        "event_name": event.name,
                        "error": f"channel_send_failed:{type(exc).__name__}: {exc}",
                    },
                )

            if cfg["send_dm"] and subscribers:
                sent_count, failed_count = await self._send_dm_reminders(
                    guild=guild,
                    event=event,
                    subscribers=subscribers,
                )
                dm_sent += sent_count
                dm_failed += failed_count

        completed_at = _iso_utc_now()
        result = EventReminderScanResult(
            scanned_events=scanned_events,
            due_events=due_events,
            channel_sent=channel_sent,
            dm_sent=dm_sent,
            dm_failed=dm_failed,
            errors=errors,
            started_at=started_at,
            completed_at=completed_at,
        )
        self._last_scan = {
            "enabled": cfg["enabled"],
            "scan_started_at": started_at,
            "scan_completed_at": completed_at,
            "scanned_events": scanned_events,
            "due_events": due_events,
            "channel_sent": channel_sent,
            "dm_sent": dm_sent,
            "dm_failed": dm_failed,
            "errors": errors,
        }
        await self.storage.append_ops_event(
            "event_reminder_scan_completed",
            {
                "guild_id": guild.id,
                "channel_id": None,
                "user_id": None,
                "command_name": "event_reminder_scan",
                "result": "ok",
                **self._last_scan,
            },
        )
        return result
