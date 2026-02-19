from __future__ import annotations

from datetime import datetime

import discord


class ThreadRecommendationView(discord.ui.View):
    def __init__(self, target_message_id: int) -> None:
        super().__init__(timeout=60 * 60)
        self.target_message_id = target_message_id

    @discord.ui.button(label="스레드 만들기", style=discord.ButtonStyle.primary)
    async def create_thread(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("이 채널에서는 스레드를 만들 수 없습니다.", ephemeral=True)
            return
        try:
            target_message = await interaction.channel.fetch_message(self.target_message_id)
            title = f"토론-{datetime.now().strftime('%m%d-%H%M')}"
            thread = await target_message.create_thread(name=title, auto_archive_duration=1440)
            await interaction.response.send_message(
                f"스레드를 생성했습니다: {thread.mention}\n기준 메시지: {target_message.jump_url}",
                ephemeral=True,
            )
            button.disabled = True
            await interaction.message.edit(view=self)
        except discord.Forbidden:
            await interaction.response.send_message("스레드 생성 권한이 없습니다.", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("스레드 생성 중 오류가 발생했습니다.", ephemeral=True)
