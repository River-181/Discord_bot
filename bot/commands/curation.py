from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

if TYPE_CHECKING:
    from bot.app import MangsangBot


def _is_curation_admin(interaction: discord.Interaction) -> bool:
    member = interaction.user
    perms = getattr(member, "guild_permissions", None)
    if not perms:
        return False
    return bool(getattr(perms, "administrator", False) or getattr(perms, "manage_guild", False))


def register(bot: "MangsangBot") -> None:
    @app_commands.command(name="curation_status", description="큐레이션 자동등록 상태와 최근 통계를 확인합니다.")
    async def curation_status(interaction: discord.Interaction) -> None:
        diag = bot.curation_service.diagnostics() if hasattr(bot, "curation_service") else None
        counts = bot.curation_service.counts() if hasattr(bot, "curation_service") else {}
        lines = [
            "큐레이션 상태",
            f"- enabled: `{diag.enabled if diag else False}`",
            f"- mode: `{diag.mode if diag else 'approve'}`",
            f"- intake_channel: `{diag.inbox_channel if diag else '-'}`",
            f"- dm_ingest: `{diag.dm_enabled if diag else False}`",
            f"- approver_policy: `{diag.approver_policy if diag else '-'}`",
            f"- pending: `{counts.get('pending', 0)}`",
            f"- approved: `{counts.get('approved', 0)}`",
            f"- rejected: `{counts.get('rejected', 0)}`",
            f"- merged: `{counts.get('merged', 0)}`",
            f"- total: `{counts.get('total', 0)}`",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="curation_config", description="큐레이션 모드/인박스 채널을 설정합니다. (운영자 전용)")
    @app_commands.describe(mode="approve 또는 auto", intake_channel="인박스 채널")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="approve", value="approve"),
            app_commands.Choice(name="auto", value="auto"),
        ]
    )
    async def curation_config(
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
        intake_channel: discord.TextChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("길드 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not _is_curation_admin(interaction):
            await interaction.response.send_message(
                "권한 부족: `Manage Guild` 또는 `Administrator` 권한이 필요합니다.",
                ephemeral=True,
            )
            return

        diag = bot.curation_service.update_config(
            mode=mode.value,
            intake_channel=intake_channel.name,
        )

        await bot.storage.append_ops_event(
            "curation_config_updated",
            {
                "guild_id": interaction.guild.id,
                "channel_id": interaction.channel.id if interaction.channel else None,
                "user_id": interaction.user.id if interaction.user else None,
                "command_name": "curation_config",
                "result": "ok",
                "mode": diag.mode,
                "inbox_channel": diag.inbox_channel,
            },
        )

        await interaction.response.send_message(
            "\n".join(
                [
                    "큐레이션 설정을 업데이트했습니다.",
                    f"- mode: `{diag.mode}`",
                    f"- intake_channel: `{diag.inbox_channel}`",
                    f"- dm_ingest: `{diag.dm_enabled}`",
                ]
            ),
            ephemeral=True,
        )

    @app_commands.command(name="curation_publish", description="승인 대기 submission을 즉시 게시합니다. (운영자 전용)")
    @app_commands.describe(
        submission_id="게시할 submission_id",
        target="대상 채널(선택)",
        create_thread="게시 후 토론 스레드 생성",
    )
    async def curation_publish(
        interaction: discord.Interaction,
        submission_id: str,
        target: discord.TextChannel | None = None,
        create_thread: bool = False,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("길드 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not _is_curation_admin(interaction):
            await interaction.response.send_message(
                "권한 부족: `Manage Guild` 또는 `Administrator` 권한이 필요합니다.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        submission = bot.curation_service.get_submission(submission_id)
        if not submission:
            await interaction.followup.send("submission_id를 찾을 수 없습니다.", ephemeral=True)
            return

        source_message = None
        source_channel_id = int(submission.get("source_channel_id", 0) or 0)
        source_message_id = int(submission.get("source_message_id", 0) or 0)
        source_channel = interaction.guild.get_channel(source_channel_id)
        if isinstance(source_channel, discord.TextChannel) and source_message_id:
            try:
                source_message = await source_channel.fetch_message(source_message_id)
            except Exception:
                source_message = None

        result = await bot.curation_service.publish_submission(
            bot=bot,
            guild=interaction.guild,
            submission_id=submission_id,
            reviewer_id=interaction.user.id,
            override_channel_name=target.name if target else str(submission.get("override_channel", "")).strip() or None,
            override_tags=list(submission.get("tags") or []),
            source_message=source_message,
            create_discussion_thread=create_thread,
        )

        if result.status == "approved":
            extra = f" / thread_id={result.thread_id}" if result.thread_id else ""
            await interaction.followup.send(
                f"게시 완료: <#{result.target_channel_id}> / message_id={result.target_message_id}{extra}",
                ephemeral=True,
            )
            return
        if result.status == "merged":
            await interaction.followup.send(
                f"중복 병합 완료: duplicate_of={result.merged_into_submission_id}",
                ephemeral=True,
            )
            return

        await interaction.followup.send(f"게시 실패: {result.status}", ephemeral=True)

    @app_commands.command(name="curation_reject", description="승인 대기 submission을 반려합니다. (운영자 전용)")
    @app_commands.describe(submission_id="반려할 submission_id", reason="반려 사유")
    async def curation_reject(interaction: discord.Interaction, submission_id: str, reason: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("길드 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not _is_curation_admin(interaction):
            await interaction.response.send_message(
                "권한 부족: `Manage Guild` 또는 `Administrator` 권한이 필요합니다.",
                ephemeral=True,
            )
            return

        ok = await bot.curation_service.reject_submission(
            guild=interaction.guild,
            submission_id=submission_id,
            reviewer_id=interaction.user.id,
            reason=reason,
        )
        if not ok:
            await interaction.response.send_message("submission_id를 찾을 수 없습니다.", ephemeral=True)
            return

        await interaction.response.send_message("반려 처리했습니다.", ephemeral=True)

    if bot.command_guild:
        bot.tree.add_command(curation_status, guild=bot.command_guild)
        bot.tree.add_command(curation_config, guild=bot.command_guild)
        bot.tree.add_command(curation_publish, guild=bot.command_guild)
        bot.tree.add_command(curation_reject, guild=bot.command_guild)
    else:
        bot.tree.add_command(curation_status)
        bot.tree.add_command(curation_config)
        bot.tree.add_command(curation_publish)
        bot.tree.add_command(curation_reject)
