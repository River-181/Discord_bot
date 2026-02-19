from __future__ import annotations

import os
from typing import TYPE_CHECKING

import discord
from discord import app_commands

if TYPE_CHECKING:
    from bot.app import MangsangBot


def register(bot: "MangsangBot") -> None:
    @app_commands.command(name="bot_status", description="봇 상태를 확인합니다.")
    async def bot_status(interaction: discord.Interaction) -> None:
        active_rooms = len(bot.storage.active_warrooms())
        all_rooms = len(bot.storage.all_latest_warrooms())
        decisions = len(bot.storage.read_jsonl("decisions"))
        summaries = len(bot.storage.read_jsonl("summaries"))
        news_items = len(bot.storage.read_jsonl("news_items"))
        news_digests = len(bot.storage.read_jsonl("news_digests"))
        dm_cfg = bot.settings.dm_assistant if hasattr(bot.settings, "dm_assistant") else {}
        dm_enabled = bool(dm_cfg.get("enabled", False))
        dm_mode = str(dm_cfg.get("mode", "hybrid"))
        dm_allowlist_count = len(dm_cfg.get("allowlist_user_ids", []) or [])
        dm_news_cooldown = int(dm_cfg.get("news_run_cooldown_seconds", 600) or 600)
        music_diag = bot.music_service.diagnostics() if hasattr(bot, "music_service") else {}
        music_enabled = bool(music_diag.get("enabled", False))
        music_allowlist_count = int(music_diag.get("allowlist_count", 0) or 0)
        music_notice_policy = str(music_diag.get("notice_policy", "low_noise"))
        music_active_sessions = int(music_diag.get("active_sessions", 0) or 0)
        event_diag = bot.event_reminder_service.diagnostics() if hasattr(bot, "event_reminder_service") else {}
        event_enabled = bool(event_diag.get("enabled", False))
        event_scan_cron = str(event_diag.get("scan_cron", "*/1 * * * *"))
        event_send_dm = bool(event_diag.get("send_dm", True))
        event_channel = str(event_diag.get("reminder_channel", ""))
        process_mode = (
            "launchd"
            if os.getenv("XPC_SERVICE_NAME") == "com.mangsang.orbit.assistant"
            else "daemon"
        )
        guild_command_count = 0
        has_meeting_summary = False
        has_meeting_summary_v2 = False
        meeting_options_equal = False
        command_fetch_error = None
        try:
            if bot.command_guild:
                guild_commands = await bot.tree.fetch_commands(guild=bot.command_guild)
                names = {command.name for command in guild_commands}
                guild_command_count = len(guild_commands)
                has_meeting_summary = "meeting_summary" in names
                has_meeting_summary_v2 = "meeting_summary_v2" in names
                v1_opts: list[str] = []
                v2_opts: list[str] = []
                for command in guild_commands:
                    if command.name == "meeting_summary":
                        v1_opts = sorted(option.name for option in command.options)
                    if command.name == "meeting_summary_v2":
                        v2_opts = sorted(option.name for option in command.options)
                meeting_options_equal = bool(v1_opts and v2_opts and v1_opts == v2_opts)
        except Exception as exc:  # pragma: no cover - runtime safety path
            command_fetch_error = f"{type(exc).__name__}: {exc}"

        lines = [
            "봇 상태",
            f"- guild_id: {bot.settings.target_guild_id}",
            f"- process_mode: {process_mode}",
            f"- active_warrooms: {active_rooms}",
            f"- warrooms_total(latest): {all_rooms}",
            f"- decisions(log lines): {decisions}",
            f"- summaries(log lines): {summaries}",
            f"- news_items(log lines): {news_items}",
            f"- news_digests(log lines): {news_digests}",
            f"- dm_enabled: {dm_enabled}",
            f"- dm_mode: {dm_mode}",
            f"- dm_allowlist_count: {dm_allowlist_count}",
            f"- dm_news_cooldown: {dm_news_cooldown}",
            f"- music_enabled: {music_enabled}",
            f"- music_active_guilds: {1 if music_active_sessions > 0 else 0}",
            f"- music_active_sessions: {music_active_sessions}",
            f"- music_allowlist_count: {music_allowlist_count}",
            f"- music_notice_policy: {music_notice_policy}",
            f"- event_reminder_enabled: {event_enabled}",
            f"- event_reminder_scan_cron: {event_scan_cron}",
            f"- event_reminder_send_dm: {event_send_dm}",
            f"- event_reminder_channel: {event_channel}",
            f"- scheduler_started: {bot.bot_scheduler.started}",
            f"- guild_command_count: {guild_command_count}",
            f"- has_meeting_summary: {has_meeting_summary}",
            f"- has_meeting_summary_v2: {has_meeting_summary_v2}",
            f"- meeting_options_equal: {meeting_options_equal}",
            f"- timezone: {bot.settings.timezone}",
        ]
        if command_fetch_error:
            lines.append(f"- command_fetch_error: {command_fetch_error}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    if bot.command_guild:
        bot.tree.add_command(bot_status, guild=bot.command_guild)
    else:
        bot.tree.add_command(bot_status)
