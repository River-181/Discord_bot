from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from bot.app import MangsangBot


class _ChannelModal(discord.ui.Modal, title="게시 채널 변경"):
    channel_name = discord.ui.TextInput(
        label="채널 이름",
        placeholder="예: 🔗-큐레이션-링크",
        max_length=120,
    )

    def __init__(self, bot: "MangsangBot", submission_id: str, parent_view: "CurationReviewView") -> None:
        super().__init__()
        self.bot = bot
        self.submission_id = submission_id
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("길드에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not self.bot.curation_service.can_manage(interaction):
            await interaction.response.send_message("권한 부족: Manage Guild 권한이 필요합니다.", ephemeral=True)
            return

        updated = await self.bot.curation_service.update_submission_overrides(
            submission_id=self.submission_id,
            reviewer_id=interaction.user.id,
            channel_name=str(self.channel_name.value),
        )
        if not updated:
            await interaction.response.send_message("submission을 찾을 수 없습니다.", ephemeral=True)
            return

        await self.parent_view.refresh_message(interaction, updated)
        await interaction.response.send_message("게시 채널을 업데이트했습니다.", ephemeral=True)


class _TagsModal(discord.ui.Modal, title="태그 수정"):
    tags = discord.ui.TextInput(
        label="태그 (공백 또는 콤마 구분)",
        placeholder="#ai #agent #startup",
        max_length=300,
    )

    def __init__(self, bot: "MangsangBot", submission_id: str, parent_view: "CurationReviewView") -> None:
        super().__init__()
        self.bot = bot
        self.submission_id = submission_id
        self.parent_view = parent_view

    @staticmethod
    def _parse_tags(raw: str) -> list[str]:
        parts = [x.strip() for x in raw.replace(",", " ").split() if x.strip()]
        tags: list[str] = []
        for item in parts:
            tag = item if item.startswith("#") else f"#{item}"
            if tag not in tags:
                tags.append(tag)
        return tags[:12]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("길드에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not self.bot.curation_service.can_manage(interaction):
            await interaction.response.send_message("권한 부족: Manage Guild 권한이 필요합니다.", ephemeral=True)
            return

        tags = self._parse_tags(str(self.tags.value))
        updated = await self.bot.curation_service.update_submission_overrides(
            submission_id=self.submission_id,
            reviewer_id=interaction.user.id,
            tags=tags,
        )
        if not updated:
            await interaction.response.send_message("submission을 찾을 수 없습니다.", ephemeral=True)
            return

        await self.parent_view.refresh_message(interaction, updated)
        await interaction.response.send_message("태그를 업데이트했습니다.", ephemeral=True)


class CurationReviewView(discord.ui.View):
    def __init__(self, *, bot: "MangsangBot", submission_id: str) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.submission_id = submission_id

    async def _check_permission(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message("길드에서만 사용할 수 있습니다.", ephemeral=True)
            return False
        if not self.bot.curation_service.can_manage(interaction):
            await interaction.response.send_message("권한 부족: Manage Guild 권한이 필요합니다.", ephemeral=True)
            return False
        return True

    async def refresh_message(self, interaction: discord.Interaction, submission: dict) -> None:
        if interaction.guild is None:
            return
        embed = self.bot.curation_service.build_review_embed(submission, interaction.guild)
        target_message = interaction.message
        if target_message is None and interaction.channel is not None:
            review_message_id = int(submission.get("review_message_id", 0) or 0)
            if review_message_id and isinstance(interaction.channel, discord.TextChannel):
                try:
                    target_message = await interaction.channel.fetch_message(review_message_id)
                except Exception:
                    target_message = None
        if target_message is not None:
            await target_message.edit(embed=embed, view=self)

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success, row=0)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # noqa: ARG002
        if not await self._check_permission(interaction):
            return
        assert interaction.guild is not None

        await interaction.response.defer(ephemeral=True, thinking=True)

        source_message = None
        submission = self.bot.curation_service.get_submission(self.submission_id)
        if submission:
            source_channel_id = int(submission.get("source_channel_id", 0) or 0)
            source_message_id = int(submission.get("source_message_id", 0) or 0)
            channel = interaction.guild.get_channel(source_channel_id)
            if isinstance(channel, discord.TextChannel) and source_message_id:
                try:
                    source_message = await channel.fetch_message(source_message_id)
                except Exception:
                    source_message = None

        result = await self.bot.curation_service.publish_submission(
            bot=self.bot,
            guild=interaction.guild,
            submission_id=self.submission_id,
            reviewer_id=interaction.user.id,
            override_channel_name=str(submission.get("override_channel", "")).strip() if submission else None,
            override_tags=list(submission.get("tags") or []) if submission else None,
            source_message=source_message,
        )

        updated = self.bot.curation_service.get_submission(self.submission_id)
        if updated:
            await self.refresh_message(interaction, updated)

        if result.status == "approved":
            await interaction.followup.send(
                f"승인 완료: <#{result.target_channel_id}> 에 게시했습니다. message_id={result.target_message_id}",
                ephemeral=True,
            )
            return
        if result.status == "merged":
            await interaction.followup.send(
                f"중복 병합 완료: duplicate_of={result.merged_into_submission_id}",
                ephemeral=True,
            )
            return

        await interaction.followup.send(f"승인 실패: {result.status}", ephemeral=True)

    @discord.ui.button(label="반려", style=discord.ButtonStyle.danger, row=0)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # noqa: ARG002
        if not await self._check_permission(interaction):
            return
        assert interaction.guild is not None

        ok = await self.bot.curation_service.reject_submission(
            guild=interaction.guild,
            submission_id=self.submission_id,
            reviewer_id=interaction.user.id,
            reason="manual_reject",
        )
        if not ok:
            await interaction.response.send_message("submission을 찾을 수 없습니다.", ephemeral=True)
            return

        updated = self.bot.curation_service.get_submission(self.submission_id)
        if updated:
            await self.refresh_message(interaction, updated)
        await interaction.response.send_message("반려 처리했습니다.", ephemeral=True)

    @discord.ui.button(label="채널변경", style=discord.ButtonStyle.secondary, row=1)
    async def change_channel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # noqa: ARG002
        if not await self._check_permission(interaction):
            return
        await interaction.response.send_modal(_ChannelModal(self.bot, self.submission_id, self))

    @discord.ui.button(label="태그수정", style=discord.ButtonStyle.secondary, row=1)
    async def edit_tags(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # noqa: ARG002
        if not await self._check_permission(interaction):
            return
        await interaction.response.send_modal(_TagsModal(self.bot, self.submission_id, self))
