from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from bot.services.music import MusicError, PolicyError
from bot.utils import truncate_text

if TYPE_CHECKING:
    from bot.app import MangsangBot

LOGGER = logging.getLogger("mangsang-orbit-assistant")


def _get_member_voice_channel(interaction: discord.Interaction) -> discord.VoiceChannel | discord.StageChannel | None:
    user = interaction.user
    voice_state = getattr(user, "voice", None)
    if not voice_state or not getattr(voice_state, "channel", None):
        return None
    channel = voice_state.channel
    if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
        return channel
    if getattr(channel, "id", None):
        return channel
    return None


def _get_bot_voice_channel(guild: discord.Guild) -> discord.VoiceChannel | discord.StageChannel | None:
    voice_client = guild.voice_client
    if not voice_client or not voice_client.is_connected():
        return None
    channel = voice_client.channel
    if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
        return channel
    if getattr(channel, "id", None):
        return channel
    return None


def _is_same_voice_channel(
    user_channel: discord.VoiceChannel | discord.StageChannel | None,
    bot_channel: discord.VoiceChannel | discord.StageChannel | None,
) -> bool:
    if not user_channel or not bot_channel:
        return False
    return user_channel.id == bot_channel.id


async def _log_command(
    bot: "MangsangBot",
    interaction: discord.Interaction,
    command_name: str,
    result: str,
) -> None:
    guild_id = interaction.guild.id if interaction.guild else None
    channel_id = interaction.channel.id if interaction.channel else None
    user_id = interaction.user.id if interaction.user else None
    await bot.storage.append_ops_event(
        "music_command_invoked",
        {
            "guild_id": guild_id,
            "channel_id": channel_id,
            "user_id": user_id,
            "command_name": command_name,
            "result": result,
        },
    )


def register(bot: "MangsangBot") -> None:
    music_group = app_commands.Group(name="music", description="음악 재생/제어 명령")

    @music_group.command(name="join", description="음성 채널에 망상궤도 비서를 연결합니다.")
    @app_commands.describe(channel="대상 음성 채널(생략 시 내 음성 채널)")
    async def music_join(
        interaction: discord.Interaction,
        channel: discord.VoiceChannel | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("길드 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not bot.music_service.enabled:
            await interaction.response.send_message("음악 기능이 비활성화되어 있습니다.", ephemeral=True)
            await _log_command(bot, interaction, "music_join", "disabled")
            return
        if not bot.music_service.voice_dependency_ok():
            await interaction.response.send_message(
                "voice dependency missing: PyNaCl/Opus 확인 필요. "
                "`brew install opus` 후 `OPUS_LIBRARY_PATH` 설정 뒤 봇을 재시작해 주세요.",
                ephemeral=True,
            )
            await _log_command(bot, interaction, "music_join", "missing_nacl")
            return

        user_channel = _get_member_voice_channel(interaction)
        if not user_channel:
            await interaction.response.send_message(
                "먼저 음성 채널에 입장해 주세요. (`음악 라운지` 권장)",
                ephemeral=True,
            )
            await _log_command(bot, interaction, "music_join", "user_not_in_voice")
            return

        target_channel = channel or user_channel
        if channel and channel.id != user_channel.id:
            await interaction.response.send_message(
                "요청자와 같은 음성 채널만 지정할 수 있습니다.",
                ephemeral=True,
            )
            await _log_command(bot, interaction, "music_join", "channel_mismatch")
            return

        bot_channel = _get_bot_voice_channel(interaction.guild)
        if bot_channel and not _is_same_voice_channel(user_channel, bot_channel):
            await interaction.response.send_message(
                "제어 권한: 봇과 같은 음성 채널에 있는 사용자만 명령할 수 있습니다.",
                ephemeral=True,
            )
            await _log_command(bot, interaction, "music_join", "not_same_voice")
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            voice_client = await bot.music_service.join(
                guild=interaction.guild,
                channel=target_channel,
                text_channel_id=interaction.channel.id if interaction.channel else None,
            )
            await interaction.followup.send(
                f"음성 채널에 연결했습니다: <#{voice_client.channel.id}>",
                ephemeral=True,
            )
            await _log_command(bot, interaction, "music_join", "ok")
        except MusicError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            await _log_command(bot, interaction, "music_join", f"error:{type(exc).__name__}")

    @music_group.command(name="play", description="음악을 재생합니다. (URL 또는 검색어)")
    @app_commands.describe(query_or_url="직접 URL 또는 검색어(검색은 allowlist만)")
    async def music_play(interaction: discord.Interaction, query_or_url: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("길드 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not bot.music_service.enabled:
            await interaction.response.send_message("음악 기능이 비활성화되어 있습니다.", ephemeral=True)
            await _log_command(bot, interaction, "music_play", "disabled")
            return
        if not bot.music_service.voice_dependency_ok():
            await interaction.response.send_message(
                "voice dependency missing: PyNaCl/Opus 확인 필요. "
                "`brew install opus` 후 `OPUS_LIBRARY_PATH` 설정 뒤 봇을 재시작해 주세요.",
                ephemeral=True,
            )
            await _log_command(bot, interaction, "music_play", "missing_nacl")
            return

        user_channel = _get_member_voice_channel(interaction)
        if not user_channel:
            await interaction.response.send_message("먼저 음성 채널에 입장해 주세요.", ephemeral=True)
            await _log_command(bot, interaction, "music_play", "user_not_in_voice")
            return

        bot_channel = _get_bot_voice_channel(interaction.guild)
        if bot_channel and not _is_same_voice_channel(user_channel, bot_channel):
            await interaction.response.send_message(
                "제어 권한: 봇과 같은 음성 채널에 있는 사용자만 명령할 수 있습니다.",
                ephemeral=True,
            )
            await _log_command(bot, interaction, "music_play", "not_same_voice")
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await bot.music_service.join(
                guild=interaction.guild,
                channel=user_channel,
                text_channel_id=interaction.channel.id if interaction.channel else None,
            )
            result = await bot.music_service.enqueue_and_maybe_play(
                guild=interaction.guild,
                requester_id=interaction.user.id if interaction.user else 0,
                text_channel_id=interaction.channel.id if interaction.channel else 0,
                query_or_url=query_or_url,
            )
            lines = [
                "음악 큐에 추가했습니다.",
                f"- title: {truncate_text(result.track.title, 120)}",
                f"- source: `{result.track.source_type}`",
                f"- started_now: `{result.started_now}`",
                f"- queue_length: `{result.queue_length}`",
            ]
            if result.track.web_url:
                lines.append(f"- link: {result.track.web_url}")
            await interaction.followup.send("\n".join(lines), ephemeral=True)
            await _log_command(bot, interaction, "music_play", "ok")
        except (PolicyError, MusicError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            await _log_command(bot, interaction, "music_play", f"blocked:{type(exc).__name__}")
        except Exception as exc:  # pragma: no cover
            LOGGER.exception("music_play failed: %s", exc)
            await interaction.followup.send(
                f"재생 처리 중 오류가 발생했습니다: {type(exc).__name__}",
                ephemeral=True,
            )
            await _log_command(bot, interaction, "music_play", f"error:{type(exc).__name__}")

    async def _require_control_context(
        interaction: discord.Interaction,
        command_name: str,
    ) -> tuple[discord.Guild, discord.VoiceChannel | discord.StageChannel] | None:
        if interaction.guild is None:
            if not interaction.response.is_done():
                await interaction.response.send_message("길드 채널에서만 사용할 수 있습니다.", ephemeral=True)
            await _log_command(bot, interaction, command_name, "not_guild")
            return None
        bot_channel = _get_bot_voice_channel(interaction.guild)
        if not bot_channel:
            if not interaction.response.is_done():
                await interaction.response.send_message("봇이 음성 채널에 연결되어 있지 않습니다.", ephemeral=True)
            await _log_command(bot, interaction, command_name, "bot_not_connected")
            return None
        user_channel = _get_member_voice_channel(interaction)
        if not user_channel:
            if not interaction.response.is_done():
                await interaction.response.send_message("먼저 같은 음성 채널에 입장해 주세요.", ephemeral=True)
            await _log_command(bot, interaction, command_name, "user_not_in_voice")
            return None
        if not _is_same_voice_channel(user_channel, bot_channel):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "제어 권한: 봇과 같은 음성 채널에 있는 사용자만 명령할 수 있습니다.",
                    ephemeral=True,
                )
            await _log_command(bot, interaction, command_name, "not_same_voice")
            return None
        return interaction.guild, bot_channel

    @music_group.command(name="pause", description="현재 재생을 일시정지합니다.")
    async def music_pause(interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)
        ctx = await _require_control_context(interaction, "music_pause")
        if not ctx:
            return
        guild, _ = ctx
        try:
            paused = await bot.music_service.pause(guild=guild)
            await interaction.followup.send("일시정지했습니다." if paused else "현재 재생 중인 트랙이 없습니다.", ephemeral=True)
            await _log_command(bot, interaction, "music_pause", "ok" if paused else "no_playing")
        except MusicError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            await _log_command(bot, interaction, "music_pause", f"error:{type(exc).__name__}")

    @music_group.command(name="resume", description="일시정지된 재생을 이어갑니다.")
    async def music_resume(interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)
        ctx = await _require_control_context(interaction, "music_resume")
        if not ctx:
            return
        guild, _ = ctx
        try:
            resumed = await bot.music_service.resume(guild=guild)
            await interaction.followup.send("재생을 재개했습니다." if resumed else "현재 일시정지 상태가 아닙니다.", ephemeral=True)
            await _log_command(bot, interaction, "music_resume", "ok" if resumed else "not_paused")
        except MusicError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            await _log_command(bot, interaction, "music_resume", f"error:{type(exc).__name__}")

    @music_group.command(name="skip", description="현재 트랙을 건너뜁니다.")
    async def music_skip(interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)
        ctx = await _require_control_context(interaction, "music_skip")
        if not ctx:
            return
        guild, _ = ctx
        try:
            skipped = await bot.music_service.skip(guild=guild)
            await interaction.followup.send("다음 트랙으로 넘어갑니다." if skipped else "건너뛸 트랙이 없습니다.", ephemeral=True)
            await _log_command(bot, interaction, "music_skip", "ok" if skipped else "no_playing")
        except MusicError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            await _log_command(bot, interaction, "music_skip", f"error:{type(exc).__name__}")

    @music_group.command(name="stop", description="재생을 중지하고 큐를 비웁니다.")
    async def music_stop(interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)
        ctx = await _require_control_context(interaction, "music_stop")
        if not ctx:
            return
        guild, _ = ctx
        try:
            stopped = await bot.music_service.stop(guild=guild)
            await interaction.followup.send("재생을 중지하고 큐를 비웠습니다." if stopped else "이미 정지 상태입니다.", ephemeral=True)
            await _log_command(bot, interaction, "music_stop", "ok" if stopped else "already_stopped")
        except MusicError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            await _log_command(bot, interaction, "music_stop", f"error:{type(exc).__name__}")

    @music_group.command(name="leave", description="음성 채널에서 나갑니다.")
    async def music_leave(interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)
        ctx = await _require_control_context(interaction, "music_leave")
        if not ctx:
            return
        guild, _ = ctx
        try:
            left = await bot.music_service.leave(guild=guild, reason="leave_command")
            await interaction.followup.send("음성 채널 연결을 종료했습니다." if left else "이미 음성 채널에 연결되어 있지 않습니다.", ephemeral=True)
            await _log_command(bot, interaction, "music_leave", "ok" if left else "already_left")
        except MusicError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            await _log_command(bot, interaction, "music_leave", f"error:{type(exc).__name__}")

    @music_group.command(name="now", description="현재 재생 중인 트랙을 표시합니다.")
    async def music_now(interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("길드 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        track = bot.music_service.now(interaction.guild.id)
        if not track:
            await interaction.response.send_message("현재 재생 중인 트랙이 없습니다.", ephemeral=True)
            await _log_command(bot, interaction, "music_now", "empty")
            return
        lines = [
            "현재 재생 중",
            f"- title: {truncate_text(track.title, 120)}",
            f"- source: `{track.source_type}`",
        ]
        if track.duration_sec:
            lines.append(f"- duration_sec: `{track.duration_sec}`")
        if track.web_url:
            lines.append(f"- link: {track.web_url}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)
        await _log_command(bot, interaction, "music_now", "ok")

    @music_group.command(name="queue", description="현재 음악 큐를 조회합니다.")
    @app_commands.describe(page="조회 페이지")
    async def music_queue(
        interaction: discord.Interaction,
        page: app_commands.Range[int, 1, 50] = 1,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("길드 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        snapshot = bot.music_service.queue_page(interaction.guild.id, int(page))
        lines = [
            f"음악 큐 (page {snapshot.page}/{snapshot.total_pages})",
            f"- total_items: `{snapshot.total_items}`",
        ]
        if snapshot.current:
            lines.append(f"- now: {truncate_text(snapshot.current.title, 100)}")
        else:
            lines.append("- now: 없음")
        if snapshot.items:
            for idx, item in enumerate(snapshot.items, start=1 + (snapshot.page - 1) * 10):
                lines.append(f"{idx}. {truncate_text(item.title, 100)}")
        else:
            lines.append("대기 큐가 비어 있습니다.")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)
        await _log_command(bot, interaction, "music_queue", "ok")

    @music_group.command(name="volume", description="음량을 조회/설정합니다. (0~200%)")
    @app_commands.describe(percent="설정할 음량 퍼센트(생략 시 현재값 조회)")
    async def music_volume(
        interaction: discord.Interaction,
        percent: app_commands.Range[int, 0, 200] | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("길드 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        if percent is None:
            current = bot.music_service.volume_percent(interaction.guild.id)
            await interaction.response.send_message(
                f"현재 음량: `{current}%`",
                ephemeral=True,
            )
            await _log_command(bot, interaction, "music_volume", "read")
            return

        guild = interaction.guild
        bot_channel = _get_bot_voice_channel(guild)
        if bot_channel is not None:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True, thinking=False)
            ctx = await _require_control_context(interaction, "music_volume")
            if not ctx:
                return
            guild, _ = ctx
        else:
            await interaction.response.defer(ephemeral=True, thinking=False)

        try:
            applied_percent, applied_now = await bot.music_service.set_volume(
                guild=guild,
                percent=int(percent),
            )
            lines = [
                f"음량을 `{applied_percent}%`로 설정했습니다.",
                f"- 현재 트랙 즉시 반영: `{applied_now}`",
            ]
            await interaction.followup.send("\n".join(lines), ephemeral=True)
            await _log_command(bot, interaction, "music_volume", f"set:{applied_percent}")
        except MusicError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            await _log_command(bot, interaction, "music_volume", f"error:{type(exc).__name__}")

    if bot.command_guild:
        bot.tree.add_command(music_group, guild=bot.command_guild)
    else:
        bot.tree.add_command(music_group)
