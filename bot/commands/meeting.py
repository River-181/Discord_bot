from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from bot.services.summarizer import SummaryResult
from bot.services.retry import retry_discord_call
from bot.utils import (
    build_channel_message_link,
    find_text_channel_by_name,
    now_tz,
    truncate_text,
)

LOGGER = logging.getLogger("mangsang-orbit-assistant")
MIGRATION_START_DATE = date(2026, 2, 18)
MIGRATION_END_DATE = date(2026, 2, 25)

if TYPE_CHECKING:
    from bot.app import MangsangBot


def _bullet_lines(items: list[str], max_items: int = 6) -> str:
    if not items:
        return "없음"
    lines = [f"• {item}" for item in items[:max_items]]
    remaining = len(items) - max_items
    if remaining > 0:
        lines.append(f"• ··· 외 {remaining}건")
    return "\n".join(lines)


def _build_source_links(channel: discord.abc.MessageableChannel, messages: list[dict[str, object]]) -> str:
    if not messages:
        return "없음"
    if not channel.guild or not isinstance(channel, discord.abc.GuildChannel):
        return "없음"
    first_id = int(messages[0]["message_id"])
    last_id = int(messages[-1]["message_id"])
    start = build_channel_message_link(
        guild_id=channel.guild.id,
        channel_id=channel.id,
        message_id=first_id,
    )
    if first_id == last_id:
        return f"[메시지]({start})"
    end = build_channel_message_link(
        guild_id=channel.guild.id,
        channel_id=channel.id,
        message_id=last_id,
    )
    return f"[시작]({start}) · [끝]({end})"


def _build_summary_embed(
    bot: "MangsangBot",
    *,
    result: SummaryResult,
    scope: str,
    window_minutes: int,
    source_channel: discord.abc.MessageableChannel,
    messages: list[dict[str, object]],
) -> tuple[discord.Embed, str]:
    embed = discord.Embed(
        title="🧠 회의 요약",
        description=truncate_text(result.summary_text, 1400),
        color=discord.Colour.orange() if result.fallback_used else discord.Colour.green(),
        timestamp=now_tz(bot.settings.timezone).replace(microsecond=0),
    )
    embed.add_field(name="범위", value=scope, inline=True)
    embed.add_field(name="기간", value=f"최근 {window_minutes}분", inline=True)
    embed.add_field(name="메시지 수", value=str(len(messages)), inline=True)
    embed.add_field(name="모델", value=f"`{result.model}`", inline=True)
    embed.add_field(name="Fallback", value="예" if result.fallback_used else "아니오", inline=True)
    embed.add_field(name="채널", value=f"{getattr(source_channel, 'name', 'unknown')}", inline=True)

    source_links = _build_source_links(source_channel, messages)
    embed.add_field(name="원문 링크", value=source_links, inline=False)
    embed.add_field(name="결정", value=truncate_text(_bullet_lines(result.decisions, max_items=5), 1024), inline=False)
    embed.add_field(name="액션", value=truncate_text(_bullet_lines(result.actions, max_items=5), 1024), inline=False)
    embed.add_field(name="리스크", value=truncate_text(_bullet_lines(result.risks, max_items=5), 1024), inline=False)
    embed.set_footer(text=f"요약ID: {result.summary_id}")

    return embed, source_links


def _build_decision_embed(
    bot: "MangsangBot",
    *,
    source_channel: discord.abc.MessageableChannel,
    decisions: list[str],
    source_links: str,
) -> discord.Embed:
    embed = discord.Embed(
        title="✅ 자동 추출 결정 항목",
        description=truncate_text(_bullet_lines(decisions, max_items=12), 3000),
        color=discord.Colour.blue(),
        timestamp=now_tz(bot.settings.timezone).replace(microsecond=0),
    )
    embed.add_field(name="원문", value=source_links or "없음", inline=False)
    embed.add_field(name="출처 채널", value=f"<#{source_channel.id}>", inline=False)
    embed.set_footer(text=f"결정 수: {len(decisions)}")
    return embed


def _build_archive_embed(
    bot: "MangsangBot",
    *,
    source_channel: discord.abc.MessageableChannel,
    summary_message: discord.Message,
    source_links: str,
) -> discord.Embed:
    embed = discord.Embed(
        title="🧭 회의 요약 아카이브",
        color=discord.Colour.dark_blue(),
        description="요약 결과를 운영 채널에 보관했습니다.",
        timestamp=now_tz(bot.settings.timezone).replace(microsecond=0),
    )
    embed.add_field(name="요약 메시지", value=summary_message.jump_url, inline=False)
    embed.add_field(name="원문", value=source_links or "없음", inline=False)
    embed.add_field(name="채널", value=f"<#{source_channel.id}>", inline=True)
    return embed


def _build_no_messages_embed(
    bot: "MangsangBot",
    *,
    scope: str,
    window_minutes: int,
    channel_label: str,
    inspected_count: int,
    valid_count: int,
    bot_count: int,
    empty_count: int,
    likely_message_content_issue: bool = False,
) -> discord.Embed:
    embed = discord.Embed(
        title="🧠 회의 요약",
        description="요약할 메시지가 없습니다.",
        color=discord.Colour.red(),
        timestamp=now_tz(bot.settings.timezone).replace(microsecond=0),
    )
    embed.add_field(name="조회 설정", value=f"scope: `{scope}` / window: `{window_minutes}분`", inline=True)
    embed.add_field(name="대상 채널", value=channel_label, inline=True)
    embed.add_field(name="검출 결과", value=f"전체: `{inspected_count}` / 유효: `{valid_count}`", inline=True)
    embed.add_field(name="제외 사유", value=f"봇 메시지: `{bot_count}` / 텍스트 없음: `{empty_count}`", inline=True)
    embed.add_field(
        name="확인 체크",
        value="\n".join(
            [
                "- 채널이 바뀌었는지(임시 회의 채널) 확인",
                "- `window_minutes`를 늘려서 재시도 (`240` 권장)",
                "- 스레드에서 실행할 땐 `scope: thread` 사용",
                "- 채널에서 실행할 땐 `source_channel` 지정 가능",
                "- 순수 텍스트 메시지가 있는지 확인(이미지/첨부만 있으면 무시)",
            ]
        ),
        inline=False,
    )
    if likely_message_content_issue:
        embed.add_field(
            name="의심 원인",
            value="디스코드 개발자 포털에서 `Message Content Intent`가 비활성일 수 있습니다. "
            "봇이 메시지 내용을 읽지 못해 요약 대상이 비어 있습니다.",
            inline=False,
        )
    return embed


def _extract_message_text(message: discord.Message) -> str:
    content = (message.clean_content or message.content or "").strip()
    if content:
        return content
    if message.embeds:
        return ""
    if message.attachments:
        return ""
    return ""


def _is_migration_window(bot: "MangsangBot") -> bool:
    today_local = now_tz(bot.settings.timezone).date()
    return MIGRATION_START_DATE <= today_local < MIGRATION_END_DATE


async def _collect_messages(
    source_channel: discord.abc.MessageableChannel,
    *,
    since: object,
    tzinfo: object,
) -> tuple[list[dict[str, object]], int, int, int]:
    messages: list[dict[str, object]] = []
    inspected_count = 0
    bot_message_count = 0
    empty_content_count = 0

    history = source_channel.history(limit=500, oldest_first=False)
    async for msg in history:
        created_local = msg.created_at.astimezone(tzinfo)
        if created_local < since:
            break
        inspected_count += 1
        if msg.author.bot:
            bot_message_count += 1
            continue
        content = _extract_message_text(msg)
        if not content:
            empty_content_count += 1
            continue
        messages.append(
            {
                "author": msg.author.display_name,
                "content": content,
                "created_at": created_local,
                "message_id": msg.id,
            }
        )
    messages.reverse()
    return messages, inspected_count, bot_message_count, empty_content_count


def register(bot: "MangsangBot") -> None:
    async def _run_meeting_summary(
        interaction: discord.Interaction,
        *,
        scope: app_commands.Choice[str],
        window_minutes: int,
        publish_to_decision_log: bool,
        source_channel: discord.TextChannel | None,
        command_name: str,
    ) -> None:
        LOGGER.info(
            "[%s] invoked scope=%s window_minutes=%s publish_to_decision_log=%s guild=%s channel=%s user=%s",
            command_name,
            scope.value,
            window_minutes,
            publish_to_decision_log,
            interaction.guild.id if interaction.guild else None,
            interaction.channel_id,
            interaction.user.id if interaction.user else None,
        )

        if interaction.guild is None or interaction.channel is None:
            await interaction.followup.send("길드 채널에서만 사용할 수 있습니다.")
            return

        if scope.value == "thread":
            if source_channel is not None:
                await interaction.followup.send("scope=thread에서는 source_channel을 지정할 수 없습니다.")
                return
            if not isinstance(interaction.channel, discord.Thread):
                await interaction.followup.send("scope=thread는 스레드 안에서만 실행할 수 있습니다.")
                return
            source_channel = interaction.channel
        else:
            source_channel = source_channel or interaction.channel
        await bot.storage.append_ops_event(
            "meeting_summary_invoked",
            {
                "guild_id": interaction.guild.id,
                "channel_id": source_channel.id,
                "user_id": interaction.user.id,
                "command_name": command_name,
                "scope": scope.value,
                "window_minutes": window_minutes,
                "publish_to_decision_log": publish_to_decision_log,
            },
        )

        since = now_tz(bot.settings.timezone) - timedelta(minutes=window_minutes)
        messages, inspected_count, bot_message_count, empty_content_count = await _collect_messages(
            source_channel,
            since=since,
            tzinfo=bot.tzinfo,
        )

        # Fallback: if command was run outside meeting channel and current channel has no valid messages,
        # try the configured meeting source channel automatically.
        if (
            not messages
            and scope.value == "channel"
            and isinstance(source_channel, discord.TextChannel)
        ):
            meeting_source_name = bot.settings.channels.get("meeting_source", "").strip()
            if meeting_source_name and source_channel.name != meeting_source_name:
                configured_meeting_channel = find_text_channel_by_name(interaction.guild, meeting_source_name)
                if configured_meeting_channel and configured_meeting_channel.id != source_channel.id:
                    fallback_messages, fallback_inspected, fallback_bot_count, fallback_empty_count = await _collect_messages(
                        configured_meeting_channel,
                        since=since,
                        tzinfo=bot.tzinfo,
                    )
                    if fallback_messages:
                        await bot.storage.append_ops_event(
                            "meeting_summary_fallback_to_meeting_source",
                            {
                                "guild_id": interaction.guild.id,
                                "channel_id": source_channel.id,
                                "user_id": interaction.user.id,
                                "command_name": command_name,
                                "fallback_channel_id": configured_meeting_channel.id,
                                "scope": scope.value,
                                "window_minutes": window_minutes,
                            },
                        )
                        source_channel = configured_meeting_channel
                        messages = fallback_messages
                        inspected_count = fallback_inspected
                        bot_message_count = fallback_bot_count
                        empty_content_count = fallback_empty_count

        if not messages:
            likely_message_intent_issue = (
                inspected_count > 0
                and bot_message_count == 0
                and empty_content_count == inspected_count
            )
            if likely_message_intent_issue:
                LOGGER.warning(
                    "[meeting_summary] only messages without content found in channel=%s; possible Message Content intent issue",
                    interaction.channel_id,
                )
            no_messages_embed = _build_no_messages_embed(
                bot,
                scope=scope.value,
                window_minutes=window_minutes,
                channel_label=f"<#{source_channel.id}>",
                inspected_count=inspected_count,
                valid_count=0,
                bot_count=bot_message_count,
                empty_count=empty_content_count,
                likely_message_content_issue=likely_message_intent_issue,
            )
            if command_name == "meeting_summary_v2":
                no_messages_embed.set_footer(text="임시 명령입니다. 2026-02-25 이후 /meeting_summary 사용")
            elif _is_migration_window(bot):
                no_messages_embed.add_field(
                    name="안내",
                    value="캐시 오류 시 /meeting_summary_v2 사용",
                    inline=False,
                )
            await bot.storage.append_ops_event(
                "meeting_summary_no_messages",
                {
                    "guild_id": interaction.guild.id,
                    "channel_id": source_channel.id,
                    "user_id": interaction.user.id,
                    "command_name": command_name,
                    "scope": scope.value,
                    "window_minutes": window_minutes,
                    "inspected_count": inspected_count,
                    "bot_count": bot_message_count,
                    "empty_count": empty_content_count,
                },
            )
            await retry_discord_call(lambda: interaction.followup.send(embed=no_messages_embed))
            return

        result = bot.summarizer.summarize(messages, scope_label=scope.value)

        summary_embed, source_links = _build_summary_embed(
            bot,
            result=result,
            scope=scope.value,
            window_minutes=window_minutes,
            source_channel=source_channel,
            messages=messages,
        )
        if result.fallback_used:
            summary_embed.description = "[품질 저하: fallback]\n" + summary_embed.description
        if command_name == "meeting_summary_v2":
            base_footer = summary_embed.footer.text or ""
            summary_embed.set_footer(
                text=(base_footer + " | 임시 명령입니다. 2026-02-25 이후 /meeting_summary 사용").strip(" |")
            )
        elif _is_migration_window(bot):
            summary_embed.add_field(
                name="안내",
                value="캐시 오류 시 /meeting_summary_v2 사용",
                inline=False,
            )

        sent = await retry_discord_call(lambda: interaction.followup.send(embed=summary_embed))

        await bot.storage.append_summary(
            {
                "summary_id": result.summary_id,
                "scope": scope.value,
                "source_ids": [int(m["message_id"]) for m in messages],
                "model": result.model,
                "fallback_used": result.fallback_used,
                "output_message_id": sent.id,
                "source_channel_id": source_channel.id,
                "source_thread_id": source_channel.id if isinstance(source_channel, discord.Thread) else None,
                "source_message_link": source_links,
            }
        )

        assistant_output = bot.settings.channels.get("assistant_output", "").strip()
        if assistant_output:
            assistant_channel = find_text_channel_by_name(interaction.guild, assistant_output)
            if assistant_channel and assistant_channel.id != interaction.channel.id:
                archive_embed = _build_archive_embed(
                    bot,
                    source_channel=source_channel,
                    summary_message=sent,
                    source_links=source_links,
                )
                await retry_discord_call(lambda: assistant_channel.send(embed=archive_embed))

        if publish_to_decision_log and result.decisions:
            decision_channel_name = bot.settings.channels.get("decision_log", "결정-log")
            decision_channel = find_text_channel_by_name(interaction.guild, decision_channel_name)
            if decision_channel:
                decision_embed = _build_decision_embed(
                    bot,
                    source_channel=source_channel,
                    decisions=result.decisions,
                    source_links=source_links,
                )
                await retry_discord_call(lambda: decision_channel.send(embed=decision_embed))

            for decision in result.decisions:
                await bot.storage.append_decision(
                    {
                        "decision_id": str(uuid.uuid4()),
                        "guild_id": interaction.guild.id,
                        "source_channel_id": source_channel.id,
                        "source_thread_id": source_channel.id if isinstance(source_channel, discord.Thread) else None,
                        "summary": decision,
                        "owner": "unassigned",
                        "due_date": None,
                        "status": "open",
                    }
                )

    @app_commands.command(name="meeting_summary", description="회의 메시지를 요약하고 결정/액션/리스크를 추출합니다.")
    @app_commands.describe(
        scope="thread 또는 channel",
        window_minutes="최근 몇 분 메시지를 요약할지",
        publish_to_decision_log="결정 항목을 결정-log에 게시할지",
        source_channel="요약 대상 텍스트 채널(비우면 현재 채널)",
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="thread", value="thread"),
            app_commands.Choice(name="channel", value="channel"),
        ]
    )
    async def meeting_summary(
        interaction: discord.Interaction,
        scope: app_commands.Choice[str],
        window_minutes: app_commands.Range[int, 5, 720] = 60,
        publish_to_decision_log: bool = False,
        source_channel: discord.TextChannel | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        await _run_meeting_summary(
            interaction,
            scope=scope,
            window_minutes=window_minutes,
            publish_to_decision_log=publish_to_decision_log,
            source_channel=source_channel,
            command_name="meeting_summary",
        )

    @app_commands.command(name="meeting_summary_v2", description="회의 요약 v2 (캐시 문제 우회용)")
    @app_commands.describe(
        scope="thread 또는 channel",
        window_minutes="최근 몇 분 메시지를 요약할지",
        publish_to_decision_log="결정 항목을 결정-log에 게시할지",
        source_channel="요약 대상 텍스트 채널(비우면 현재 채널)",
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="thread", value="thread"),
            app_commands.Choice(name="channel", value="channel"),
        ]
    )
    async def meeting_summary_v2(
        interaction: discord.Interaction,
        scope: app_commands.Choice[str],
        window_minutes: app_commands.Range[int, 5, 720] = 60,
        publish_to_decision_log: bool = False,
        source_channel: discord.TextChannel | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        await _run_meeting_summary(
            interaction,
            scope=scope,
            window_minutes=window_minutes,
            publish_to_decision_log=publish_to_decision_log,
            source_channel=source_channel,
            command_name="meeting_summary_v2",
        )

    @meeting_summary.error
    async def meeting_summary_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        forbidden = isinstance(error, discord.Forbidden) or (
            isinstance(error, app_commands.CommandInvokeError)
            and isinstance(error.original, discord.Forbidden)
        )
        if forbidden:
            msg = "권한 부족: `Send Messages`, `Read Message History`, `Create Public Threads` 권한을 확인하세요."
            if interaction.response.is_done():
                await interaction.followup.send(msg)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        if interaction.response.is_done():
            await interaction.followup.send(f"meeting_summary 오류: {error}")
        else:
            await interaction.response.send_message(f"meeting_summary 오류: {error}", ephemeral=True)

    @meeting_summary_v2.error
    async def meeting_summary_v2_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        await meeting_summary_error(interaction, error)

    @app_commands.command(name="decision_add", description="결정 로그에 항목을 수동 등록합니다.")
    @app_commands.describe(
        title="결정 제목",
        owner="담당자",
        due_date="마감일 (예: 2026-02-20)",
        context_url="참조 링크",
    )
    async def decision_add(
        interaction: discord.Interaction,
        title: str,
        owner: str,
        due_date: str,
        context_url: str = "",
    ) -> None:
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("길드에서만 사용할 수 있습니다.", ephemeral=True)
            return

        channel_name = bot.settings.channels.get("decision_log", "결정-log")
        decision_channel = find_text_channel_by_name(interaction.guild, channel_name)

        await bot.storage.append_decision(
            {
                "decision_id": str(uuid.uuid4()),
                "guild_id": interaction.guild.id,
                "source_channel_id": interaction.channel_id,
                "source_thread_id": interaction.channel_id if isinstance(interaction.channel, discord.Thread) else None,
                "summary": title,
                "owner": owner,
                "due_date": due_date,
                "status": "open",
                "context_url": context_url or None,
            }
        )

        body = "\n".join(
            [f"제목: {title}", f"담당: {owner}", f"마감: {due_date}"]
            + ([f"링크: {context_url}"] if context_url else [])
        )
        body_embed = discord.Embed(
            title="📝 수동 결정 등록",
            description=body,
            color=discord.Colour.teal(),
            timestamp=now_tz(bot.settings.timezone).replace(microsecond=0),
        )
        body_embed.set_footer(text=f"채널: <#{interaction.channel_id}>")

        if decision_channel:
            await retry_discord_call(lambda: decision_channel.send(embed=body_embed))

        await interaction.response.send_message("결정 항목을 기록했습니다.", ephemeral=True)

    if bot.command_guild:
        bot.tree.add_command(meeting_summary, guild=bot.command_guild)
        bot.tree.add_command(meeting_summary_v2, guild=bot.command_guild)
        bot.tree.add_command(decision_add, guild=bot.command_guild)
    else:
        bot.tree.add_command(meeting_summary)
        bot.tree.add_command(meeting_summary_v2)
        bot.tree.add_command(decision_add)
