from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from bot.app import MangsangBot


class _MusicControlCallbackMixin:
    @staticmethod
    def _bot_voice_channel(guild: discord.Guild) -> discord.VoiceChannel | discord.StageChannel | None:
        voice_client = guild.voice_client
        if not voice_client or not voice_client.is_connected():
            return None
        channel = voice_client.channel
        if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            return channel
        if getattr(channel, "id", None):
            return channel
        return None

    @staticmethod
    def _member_voice_channel(interaction: discord.Interaction) -> discord.VoiceChannel | discord.StageChannel | None:
        user = interaction.user
        voice_state = getattr(user, "voice", None)
        if not voice_state:
            return None
        channel = voice_state.channel
        if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            return channel
        if getattr(channel, "id", None):
            return channel
        return None

    @staticmethod
    def _same_voice_channel(
        user_channel: discord.VoiceChannel | discord.StageChannel | None,
        bot_channel: discord.VoiceChannel | discord.StageChannel | None,
    ) -> bool:
        if not user_channel or not bot_channel:
            return False
        return user_channel.id == bot_channel.id

    @staticmethod
    def _is_admin_or_manage(interaction: discord.Interaction) -> bool:
        perms = getattr(interaction.user, "guild_permissions", None)
        if not perms:
            return False
        return bool(getattr(perms, "manage_guild", False) or getattr(perms, "administrator", False))

    async def _reply(self, interaction: discord.Interaction, message: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def _require_context(
        self,
        interaction: discord.Interaction,
        command_name: str,
        *,
        allow_admin_without_same_channel: bool = False,
    ) -> tuple[discord.Guild, discord.VoiceChannel | discord.StageChannel, bool] | None:
        if interaction.guild is None:
            await self._reply(interaction, "길드 채널에서만 사용할 수 있습니다.")
            await self._send_log(interaction, command_name, "not_guild")
            return None

        guild = interaction.guild
        bot_channel = self._bot_voice_channel(guild)
        if bot_channel is None:
            await self._reply(interaction, "봇이 음성 채널에 연결되어 있지 않습니다.")
            await self._send_log(interaction, command_name, "bot_not_connected")
            return None

        user_channel = self._member_voice_channel(interaction)
        if user_channel is None:
            await self._reply(interaction, "버튼 조작은 음성 채널에 먼저 입장해야 합니다.")
            await self._send_log(interaction, command_name, "user_not_in_voice")
            return None

        same_channel = self._same_voice_channel(user_channel, bot_channel)
        if same_channel:
            return guild, bot_channel, same_channel

        if allow_admin_without_same_channel and self._is_admin_or_manage(interaction):
            return guild, bot_channel, same_channel

        await self._reply(interaction, "버튼 조작은 봇과 같은 음성 채널에서만 가능합니다.")
        await self._send_log(interaction, command_name, "not_same_voice")
        return None

    async def _send_log(self, interaction: discord.Interaction, command_name: str, result: str) -> None:
        await self.bot.storage.append_ops_event(
            "music_control_invoked",
            {
                "guild_id": interaction.guild.id if interaction.guild else None,
                "channel_id": interaction.channel.id if interaction.channel else None,
                "user_id": interaction.user.id if interaction.user else None,
                "command_name": command_name,
                "result": result,
            },
        )


class MusicControlsView(discord.ui.View, _MusicControlCallbackMixin):
    def __init__(self, bot: "MangsangBot", guild_id: int) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id

    def _format_volume_line(self, guild_id: int) -> str:
        percent = self.bot.music_service.volume_percent(guild_id)
        return f"음량: `{percent}%`"

    def _queue_preview(self, guild_id: int, *, max_items: int = 5) -> str:
        state = self.bot.music_service.get_state(guild_id)
        if not state:
            return "없음"
        if not state.queue:
            return "비어 있음"
        titles = [q.title for q in list(state.queue)[:max_items]]
        tail = f" (+{len(state.queue) - max_items})" if len(state.queue) > max_items else ""
        return ", ".join(titles) + tail

    async def _notify(self, interaction: discord.Interaction, command_name: str, result: str, message: str) -> None:
        await self._reply(interaction, message)
        await self._send_log(interaction, command_name, result)

    @discord.ui.button(label="⏸️/▶️", style=discord.ButtonStyle.primary, custom_id="music:pause_resume", row=0)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button  # signature compatibility
        ctx = await self._require_context(interaction, "music_pause_resume")
        if not ctx:
            return
        guild, bot_channel, _same_channel = ctx
        _ = bot_channel

        try:
            state = self.bot.music_service.get_state(guild.id)
            if state and guild.voice_client and guild.voice_client.is_playing():
                paused = await self.bot.music_service.pause(guild=guild)
                await self._notify(interaction, "music_pause_resume", f"paused:{paused}", "일시정지했습니다." if paused else "현재 재생 중인 트랙이 없습니다.")
                return

            resumed = await self.bot.music_service.resume(guild=guild)
            await self._notify(
                interaction,
                "music_pause_resume",
                f"resumed:{resumed}",
                "재생을 재개했습니다." if resumed else "현재 일시정지 상태가 아닙니다.",
            )
        except Exception as exc:
            await self._notify(interaction, "music_pause_resume", f"error:{type(exc).__name__}", f"작업 실패: {type(exc).__name__}")

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.secondary, custom_id="music:skip", row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        ctx = await self._require_context(interaction, "music_skip")
        if not ctx:
            return
        guild, _bot_channel, _same_channel = ctx

        try:
            skipped = await self.bot.music_service.skip(guild=guild)
            await self._notify(
                interaction,
                "music_skip",
                f"ok:{skipped}",
                "다음 곡으로 넘어갔습니다." if skipped else "건너뛸 곡이 없습니다.",
            )
        except Exception as exc:
            await self._notify(interaction, "music_skip", f"error:{type(exc).__name__}", f"스킵 실패: {type(exc).__name__}")

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.danger, custom_id="music:stop", row=0)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        ctx = await self._require_context(interaction, "music_stop")
        if not ctx:
            return
        guild, _bot_channel, _same_channel = ctx

        try:
            stopped = await self.bot.music_service.stop(guild=guild)
            await self._notify(
                interaction,
                "music_stop",
                f"ok:{stopped}",
                "재생 중단 및 큐 초기화." if stopped else "현재 재생 중인 트랙이 없습니다.",
            )
        except Exception as exc:
            await self._notify(interaction, "music_stop", f"error:{type(exc).__name__}", f"중지 실패: {type(exc).__name__}")

    @discord.ui.button(label="🚪", style=discord.ButtonStyle.secondary, custom_id="music:leave", row=1)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        ctx = await self._require_context(interaction, "music_leave")
        if not ctx:
            return
        guild, _bot_channel, _same_channel = ctx

        try:
            left = await self.bot.music_service.leave(guild=guild, reason="leave_button")
            await self._notify(
                interaction,
                "music_leave",
                f"ok:{left}",
                "음성 채널에서 나갔습니다." if left else "이미 음성 채널에 연결되어 있지 않습니다.",
            )
        except Exception as exc:
            await self._notify(interaction, "music_leave", f"error:{type(exc).__name__}", f"나가기 실패: {type(exc).__name__}")

    @discord.ui.button(label="-10", style=discord.ButtonStyle.secondary, custom_id="music:vol_down", row=1)
    async def vol_down(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        ctx = await self._require_context(interaction, "music_volume", allow_admin_without_same_channel=True)
        if not ctx:
            return
        guild, _bot_channel, same_channel = ctx
        if not same_channel and not self._is_admin_or_manage(interaction):
            await self._reply(interaction, "볼륨 조절은 운영자 권한이 필요합니다.")
            await self._send_log(interaction, "music_volume", "admin_required")
            return

        current = self.bot.music_service.volume_percent(guild.id)
        target = max(0, current - 10)
        try:
            new_percent, _ = await self.bot.music_service.set_volume(guild=guild, percent=target)
            await self._notify(
                interaction,
                "music_volume",
                f"decrease:{new_percent}",
                f"음량: `{new_percent}%`",
            )
        except Exception as exc:
            await self._notify(interaction, "music_volume", f"error:{type(exc).__name__}", f"음량 조절 실패: {type(exc).__name__}")

    @discord.ui.button(label="+10", style=discord.ButtonStyle.secondary, custom_id="music:vol_up", row=1)
    async def vol_up(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        ctx = await self._require_context(interaction, "music_volume", allow_admin_without_same_channel=True)
        if not ctx:
            return
        guild, _bot_channel, same_channel = ctx
        if not same_channel and not self._is_admin_or_manage(interaction):
            await self._reply(interaction, "볼륨 조절은 운영자 권한이 필요합니다.")
            await self._send_log(interaction, "music_volume", "admin_required")
            return

        current = self.bot.music_service.volume_percent(guild.id)
        target = min(200, current + 10)
        try:
            new_percent, _ = await self.bot.music_service.set_volume(guild=guild, percent=target)
            await self._notify(
                interaction,
                "music_volume",
                f"increase:{new_percent}",
                f"음량: `{new_percent}%`",
            )
        except Exception as exc:
            await self._notify(interaction, "music_volume", f"error:{type(exc).__name__}", f"음량 조절 실패: {type(exc).__name__}")

    @discord.ui.button(label="🔢큐", style=discord.ButtonStyle.secondary, custom_id="music:queue_refresh", row=2)
    async def queue_refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.guild is None:
            await self._reply(interaction, "길드 채널에서만 사용할 수 있습니다.")
            return
        preview = self._queue_preview(interaction.guild.id)
        await self._notify(interaction, "music_queue", "ok", f"현재 큐: {preview}")

    @discord.ui.button(label="🔁패널", style=discord.ButtonStyle.success, custom_id="music:panel", row=2)
    async def panel_refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.guild is None:
            await self._reply(interaction, "길드 채널에서만 사용할 수 있습니다.")
            return
        if not self._is_admin_or_manage(interaction):
            await self._reply(interaction, "패널 새로고침은 운영 권한이 필요합니다.")
            await self._send_log(interaction, "music_panel", "denied")
            return

        await self.bot.music_service.refresh_control_panel(interaction.guild, reason="button_panel_refresh")
        await self._notify(interaction, "music_panel", "ok", "패널을 갱신했습니다.")
