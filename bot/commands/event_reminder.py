from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

if TYPE_CHECKING:
    from bot.app import MangsangBot


def _is_event_reminder_admin(interaction: discord.Interaction) -> bool:
    member = interaction.user
    perms = getattr(member, "guild_permissions", None)
    if not perms:
        return False
    return bool(getattr(perms, "administrator", False) or getattr(perms, "manage_guild", False))


def register(bot: "MangsangBot") -> None:
    @app_commands.command(name="event_reminder_status", description="이벤트 5분 전 알림 설정/최근 실행 상태를 확인합니다.")
    async def event_reminder_status(interaction: discord.Interaction) -> None:
        diag = bot.event_reminder_service.diagnostics()
        last_scan = diag.get("last_scan", {}) if isinstance(diag.get("last_scan"), dict) else {}
        lines = [
            "이벤트 리마인더 상태",
            f"- enabled: `{diag.get('enabled')}`",
            f"- reminder_minutes: `{diag.get('reminder_minutes')}`",
            f"- scan_cron: `{diag.get('scan_cron')}`",
            f"- reminder_channel: `{diag.get('reminder_channel')}`",
            f"- mention_mode: `{diag.get('mention_mode')}`",
            f"- send_dm: `{diag.get('send_dm')}`",
            f"- max_mentions_per_message: `{diag.get('max_mentions_per_message')}`",
            f"- last_scan_started_at: `{last_scan.get('scan_started_at', '-')}`",
            f"- last_scan_completed_at: `{last_scan.get('scan_completed_at', '-')}`",
            f"- last_scanned_events: `{last_scan.get('scanned_events', 0)}`",
            f"- last_due_events: `{last_scan.get('due_events', 0)}`",
            f"- last_channel_sent: `{last_scan.get('channel_sent', 0)}`",
            f"- last_dm_sent: `{last_scan.get('dm_sent', 0)}`",
            f"- last_dm_failed: `{last_scan.get('dm_failed', 0)}`",
            f"- last_errors: `{last_scan.get('errors', 0)}`",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="event_reminder_config", description="이벤트 5분 전 알림 설정을 변경합니다. (운영자 전용)")
    @app_commands.describe(
        enabled="기능 활성/비활성",
        reminder_minutes="Phase 1에서 5만 허용",
        send_dm="참가자 DM 발송 여부",
    )
    async def event_reminder_config(
        interaction: discord.Interaction,
        enabled: bool,
        reminder_minutes: app_commands.Range[int, 1, 60],
        send_dm: bool,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("길드 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not _is_event_reminder_admin(interaction):
            await interaction.response.send_message(
                "권한 부족: `Manage Guild` 또는 `Administrator` 권한이 필요합니다.",
                ephemeral=True,
            )
            return
        if int(reminder_minutes) != 5:
            await interaction.response.send_message(
                "Phase 1에서는 `reminder_minutes=5`만 허용됩니다.",
                ephemeral=True,
            )
            return

        try:
            diag = bot.event_reminder_service.update_config(
                enabled=enabled,
                reminder_minutes=int(reminder_minutes),
                send_dm=send_dm,
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await bot.storage.append_ops_event(
            "event_reminder_config_updated",
            {
                "guild_id": interaction.guild.id,
                "channel_id": interaction.channel.id if interaction.channel else None,
                "user_id": interaction.user.id if interaction.user else None,
                "command_name": "event_reminder_config",
                "result": "ok",
                "enabled": diag.get("enabled"),
                "reminder_minutes": diag.get("reminder_minutes"),
                "send_dm": diag.get("send_dm"),
            },
        )

        await interaction.response.send_message(
            "\n".join(
                [
                    "이벤트 리마인더 설정을 업데이트했습니다.",
                    f"- enabled: `{diag.get('enabled')}`",
                    f"- reminder_minutes: `{diag.get('reminder_minutes')}`",
                    f"- send_dm: `{diag.get('send_dm')}`",
                    f"- reminder_channel: `{diag.get('reminder_channel')}`",
                ]
            ),
            ephemeral=True,
        )

    if bot.command_guild:
        bot.tree.add_command(event_reminder_status, guild=bot.command_guild)
        bot.tree.add_command(event_reminder_config, guild=bot.command_guild)
    else:
        bot.tree.add_command(event_reminder_status)
        bot.tree.add_command(event_reminder_config)

