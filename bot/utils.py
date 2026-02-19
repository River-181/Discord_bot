from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import discord


def now_tz(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9가-힣]+", "-", value.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "warroom"


def find_text_channel_by_name(guild: discord.Guild, name: str) -> discord.TextChannel | None:
    for channel in guild.text_channels:
        if channel.name == name:
            return channel
    return None


def find_category_by_name(guild: discord.Guild, name: str) -> discord.CategoryChannel | None:
    for category in guild.categories:
        if category.name == name:
            return category
    return None


def format_kst(dt: datetime | None) -> str:
    if not dt:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


def build_channel_message_link(guild_id: int, channel_id: int, message_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def truncate_text(value: str, max_chars: int, suffix: str = " ...") -> str:
    if len(value) <= max_chars:
        return value
    if max_chars <= len(suffix):
        return value[:max_chars]
    return value[: max_chars - len(suffix)] + suffix
