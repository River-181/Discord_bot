from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import discord

from bot.services.retry import retry_discord_call
from bot.services.storage import StorageService
from bot.services.summarizer import SummarizerService
from bot.utils import find_category_by_name, find_text_channel_by_name, now_tz, slugify, truncate_text


class WarroomService:
    def __init__(
        self,
        timezone: str,
        config: dict[str, Any],
        channels_config: dict[str, str],
        storage: StorageService,
        summarizer: SummarizerService,
    ) -> None:
        self.timezone = timezone
        self.config = config
        self.channels_config = channels_config
        self.storage = storage
        self.summarizer = summarizer
        self._last_touch_write: dict[str, datetime] = {}

    def _now(self) -> datetime:
        return now_tz(self.timezone)

    def _iso_now(self) -> str:
        return self._now().isoformat(timespec="seconds")

    def _text_category_name(self, zone: str) -> str:
        zone_map = self.config.get("text_category_by_zone", {})
        return str(zone_map.get(zone, zone_map.get("product", "")))

    async def _ensure_category(self, guild: discord.Guild, name: str) -> discord.CategoryChannel | None:
        if not name:
            return None
        category = find_category_by_name(guild, name)
        if category:
            return category
        return await retry_discord_call(
            lambda: guild.create_category(name=name, reason="warroom category auto-create")
        )

    async def _unique_warroom_slug(self, guild: discord.Guild, base_name: str) -> str:
        base_slug = slugify(base_name)
        existing_names = {channel.name for channel in guild.channels}
        if f"wr-{base_slug}" not in existing_names:
            return base_slug
        date_suffix = self._now().strftime("%m%d")
        candidate = f"{base_slug}-{date_suffix}"
        if f"wr-{candidate}" not in existing_names:
            return candidate
        seq = 2
        while f"wr-{candidate}-{seq}" in existing_names:
            seq += 1
        return f"{candidate}-{seq}"

    def _active_record_by_name(self, name: str) -> dict[str, Any] | None:
        name_slug = slugify(name)
        for record in self.storage.active_warrooms():
            if record.get("name") == name:
                return record
            if record.get("slug") == name_slug:
                return record
            if record.get("text_channel_name") == name:
                return record
        return None

    async def open_warroom(
        self,
        guild: discord.Guild,
        name: str,
        zone: str,
        ttl_days: int,
        created_by: discord.abc.User,
    ) -> dict[str, Any]:
        slug = await self._unique_warroom_slug(guild, name)
        text_category_name = self._text_category_name(zone)
        voice_category_name = str(self.config.get("voice_category", ""))

        text_category = await self._ensure_category(guild, text_category_name)
        voice_category = await self._ensure_category(guild, voice_category_name)

        text_channel_name = f"wr-{slug}"
        voice_channel_name = f"wr-{slug}"

        text_channel = await retry_discord_call(
            lambda: guild.create_text_channel(
                name=text_channel_name,
                category=text_category,
                topic=f"warroom:{name} zone:{zone}",
                reason=f"warroom_open by {created_by}",
            )
        )
        voice_channel = await retry_discord_call(
            lambda: guild.create_voice_channel(
                name=voice_channel_name,
                category=voice_category,
                reason=f"warroom_open by {created_by}",
            )
        )

        now_iso = self._iso_now()
        record = {
            "warroom_id": str(uuid.uuid4()),
            "name": name,
            "slug": slug,
            "zone": zone,
            "text_channel_id": text_channel.id,
            "text_channel_name": text_channel.name,
            "voice_channel_id": voice_channel.id,
            "voice_channel_name": voice_channel.name,
            "created_at": now_iso,
            "last_activity_at": now_iso,
            "state": "active",
            "archived_at": None,
            "ttl_days": ttl_days,
            "warning_sent_at": None,
            "created_by": created_by.id,
        }
        await self.storage.append_warroom(record)
        await self.storage.append_ops_event(
            "warroom_open",
            {"warroom_id": record["warroom_id"], "name": name, "zone": zone},
        )
        return record

    async def touch_activity_from_message(self, message: discord.Message) -> None:
        if not isinstance(message.channel, discord.TextChannel):
            return
        channel_id = message.channel.id
        for record in self.storage.active_warrooms():
            if record.get("text_channel_id") != channel_id:
                continue
            warroom_id = str(record["warroom_id"])
            now = self._now()
            last_write = self._last_touch_write.get(warroom_id)
            if last_write and now - last_write < timedelta(minutes=5):
                return
            updated = dict(record)
            updated["last_activity_at"] = now.isoformat(timespec="seconds")
            updated["event"] = "activity_touch"
            await self.storage.append_warroom(updated)
            self._last_touch_write[warroom_id] = now
            return

    async def _move_to_archive(
        self,
        guild: discord.Guild,
        record: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        archive_category_name = str(self.config.get("archive_category", ""))
        archive_category = await self._ensure_category(guild, archive_category_name)

        text_channel = guild.get_channel(int(record.get("text_channel_id", 0)))
        voice_channel = guild.get_channel(int(record.get("voice_channel_id", 0)))

        if isinstance(text_channel, discord.TextChannel):
            archived_name = text_channel.name
            if not archived_name.startswith("arch-"):
                archived_name = ("arch-" + archived_name)[:100]
            await retry_discord_call(
                lambda: text_channel.edit(name=archived_name, category=archive_category, reason=reason)
            )
        if isinstance(voice_channel, discord.VoiceChannel):
            archived_name = voice_channel.name
            if not archived_name.startswith("arch-"):
                archived_name = ("arch-" + archived_name)[:100]
            await retry_discord_call(
                lambda: voice_channel.edit(name=archived_name, category=archive_category, reason=reason)
            )

        updated = dict(record)
        updated["state"] = "archived"
        updated["archived_at"] = self._iso_now()
        updated["event"] = "archived"
        await self.storage.append_warroom(updated)
        return updated

    async def _post_close_summary(
        self,
        guild: discord.Guild,
        record: dict[str, Any],
        reason: str,
    ) -> None:
        text_channel = guild.get_channel(int(record.get("text_channel_id", 0)))
        summary_text = f"워룸 `{record.get('name')}` 종료. 사유: {reason}"
        decisions: list[str] = []

        if isinstance(text_channel, discord.TextChannel):
            messages: list[dict[str, Any]] = []
            async for msg in text_channel.history(limit=120, oldest_first=False):
                if msg.author.bot:
                    continue
                if not msg.content:
                    continue
                messages.append(
                    {
                        "author": msg.author.display_name,
                        "content": msg.content,
                        "created_at": msg.created_at,
                    }
                )
            messages.reverse()
            if messages:
                result = self.summarizer.summarize(messages, scope_label=f"warroom:{record.get('name')}")
                summary_text = result.summary_text
                if result.fallback_used:
                    summary_text = f"[품질 저하: fallback] {summary_text}"
                decisions = result.decisions

        decision_ch = find_text_channel_by_name(guild, self.channels_config.get("decision_log", ""))
        knowledge_ch = find_text_channel_by_name(guild, self.channels_config.get("knowledge_base", ""))
        target_channels = []
        for ch in [decision_ch, knowledge_ch]:
            if ch is not None and ch not in target_channels:
                target_channels.append(ch)

        if not target_channels:
            return

        summary_desc = (
            f"워룸 `{record.get('name')}` 종료 요약\n"
            f"종료 사유: {reason}\n\n"
            f"{summary_text}"
        )
        summary_embed = discord.Embed(
            title="🧩 워룸 종료 요약",
            description=truncate_text(summary_desc, 3800),
            color=discord.Colour.purple(),
        )
        if decisions:
            decision_lines = [f"- {item}" for item in decisions[:8]]
            summary_embed.add_field(
                name="결정",
                value=truncate_text("\n".join(decision_lines), 1024),
                inline=False,
            )

        for channel in target_channels:
            await retry_discord_call(lambda channel=channel: channel.send(embed=summary_embed))

    async def close_warroom(
        self,
        guild: discord.Guild,
        name: str,
        reason: str,
        closed_by: discord.abc.User,
    ) -> dict[str, Any] | None:
        record = self._active_record_by_name(name)
        if not record:
            return None
        archived = await self._move_to_archive(guild, record, reason=f"warroom_close by {closed_by}")
        await self._post_close_summary(guild, record, reason)
        await self.storage.append_ops_event(
            "warroom_close",
            {"warroom_id": archived["warroom_id"], "reason": reason, "by": closed_by.id},
        )
        return archived

    def list_warrooms(self, status: str) -> list[dict[str, Any]]:
        latest = self.storage.all_latest_warrooms()
        if status == "all":
            return latest
        return [x for x in latest if x.get("state") == status]

    async def run_inactivity_scan(self, bot: discord.Client, guild_id: int | None) -> tuple[int, int]:
        if guild_id is None:
            return (0, 0)
        guild = bot.get_guild(guild_id)
        if not guild:
            return (0, 0)

        warning_days = int(self.config.get("warning_days", 14))
        archive_days = int(self.config.get("archive_days", 30))

        warning_count = 0
        archive_count = 0

        for record in self.storage.active_warrooms():
            last_activity = record.get("last_activity_at")
            if not last_activity:
                continue
            try:
                last_dt = datetime.fromisoformat(str(last_activity))
            except ValueError:
                continue
            now = self._now()
            inactive_days = (now - last_dt).days

            text_channel = guild.get_channel(int(record.get("text_channel_id", 0)))

            if inactive_days >= archive_days:
                await self._move_to_archive(guild, record, reason="inactive auto-archive")
                archive_count += 1
                await self.storage.append_ops_event(
                    "warroom_auto_archived",
                    {
                        "warroom_id": record.get("warroom_id"),
                        "inactive_days": inactive_days,
                    },
                    idempotency_key=f"auto-archive:{record.get('warroom_id')}",
                )
                continue

            warned_at = record.get("warning_sent_at")
            if inactive_days >= warning_days and not warned_at:
                if isinstance(text_channel, discord.TextChannel):
                    await retry_discord_call(
                        lambda: text_channel.send(
                            f"워룸 비활성 {inactive_days}일 경과. {archive_days}일 시 자동 아카이브됩니다."
                        )
                    )
                updated = dict(record)
                updated["warning_sent_at"] = self._iso_now()
                updated["event"] = "inactive_warning"
                await self.storage.append_warroom(updated)
                warning_count += 1
                await self.storage.append_ops_event(
                    "warroom_inactive_warning",
                    {
                        "warroom_id": record.get("warroom_id"),
                        "inactive_days": inactive_days,
                    },
                    idempotency_key=f"inactive-warning:{record.get('warroom_id')}",
                )

        return warning_count, archive_count
