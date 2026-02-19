from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

if TYPE_CHECKING:
    from bot.app import MangsangBot


def register(bot: "MangsangBot") -> None:
    @app_commands.command(name="warroom_open", description="프로젝트 워룸(텍스트+음성)을 생성합니다.")
    @app_commands.describe(
        name="워룸 이름",
        zone="생성 영역",
        ttl_days="기본 보관 기한(일)",
    )
    @app_commands.choices(
        zone=[
            app_commands.Choice(name="core", value="core"),
            app_commands.Choice(name="product", value="product"),
            app_commands.Choice(name="growth", value="growth"),
        ]
    )
    async def warroom_open(
        interaction: discord.Interaction,
        name: str,
        zone: app_commands.Choice[str],
        ttl_days: app_commands.Range[int, 7, 120] = 30,
    ) -> None:
        if interaction.guild is None or interaction.user is None:
            await interaction.response.send_message("길드 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            record = await bot.warroom_service.open_warroom(
                guild=interaction.guild,
                name=name,
                zone=zone.value,
                ttl_days=ttl_days,
                created_by=interaction.user,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "권한 부족: `Manage Channels`, `View Channels`, `Send Messages` 권한을 확인하세요."
            )
            return
        await interaction.followup.send(
            "\n".join(
                [
                    "워룸을 생성했습니다.",
                    f"- name: `{record['name']}`",
                    f"- text: `<#{record['text_channel_id']}>`",
                    f"- voice: `<#{record['voice_channel_id']}>`",
                    f"- ttl_days: `{record['ttl_days']}`",
                ]
            )
        )

    @app_commands.command(name="warroom_close", description="워룸을 종료하고 아카이브합니다.")
    @app_commands.describe(name="워룸 이름 또는 slug", reason="종료 사유")
    async def warroom_close(interaction: discord.Interaction, name: str, reason: str) -> None:
        if interaction.guild is None or interaction.user is None:
            await interaction.response.send_message("길드 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            archived = await bot.warroom_service.close_warroom(
                guild=interaction.guild,
                name=name,
                reason=reason,
                closed_by=interaction.user,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "권한 부족: `Manage Channels`, `View Channels`, `Send Messages` 권한을 확인하세요."
            )
            return
        if not archived:
            await interaction.followup.send("활성 워룸을 찾지 못했습니다.")
            return

        await interaction.followup.send(
            "\n".join(
                [
                    "워룸을 종료했습니다.",
                    f"- name: `{archived['name']}`",
                    f"- archived_at: `{archived['archived_at']}`",
                    f"- state: `{archived['state']}`",
                ]
            )
        )

    @app_commands.command(name="warroom_list", description="워룸 상태를 조회합니다.")
    @app_commands.describe(status="active, archived, all")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="active", value="active"),
            app_commands.Choice(name="archived", value="archived"),
            app_commands.Choice(name="all", value="all"),
        ]
    )
    async def warroom_list(interaction: discord.Interaction, status: app_commands.Choice[str]) -> None:
        rooms = bot.warroom_service.list_warrooms(status.value)
        if not rooms:
            await interaction.response.send_message("해당 상태의 워룸이 없습니다.", ephemeral=True)
            return

        lines = [f"워룸 목록 (`{status.value}`)"]
        for room in sorted(rooms, key=lambda x: str(x.get("created_at", "")), reverse=True)[:20]:
            lines.append(
                " | ".join(
                    [
                        f"name={room.get('name')}",
                        f"zone={room.get('zone')}",
                        f"state={room.get('state')}",
                        f"last={room.get('last_activity_at')}",
                    ]
                )
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    if bot.command_guild:
        bot.tree.add_command(warroom_open, guild=bot.command_guild)
        bot.tree.add_command(warroom_close, guild=bot.command_guild)
        bot.tree.add_command(warroom_list, guild=bot.command_guild)
    else:
        bot.tree.add_command(warroom_open)
        bot.tree.add_command(warroom_close)
        bot.tree.add_command(warroom_list)
