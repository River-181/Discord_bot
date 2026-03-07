from __future__ import annotations

import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from bot.services.ops_diagnostics import build_news_runtime

if TYPE_CHECKING:
    from bot.app import MangsangBot


_LAST_RUN_AT_BY_GUILD: dict[int, float] = {}
_COOLDOWN_SECONDS = 10 * 60


def _cooldown_ok(guild_id: int) -> tuple[bool, int]:
    last = _LAST_RUN_AT_BY_GUILD.get(guild_id, 0.0)
    now = time.time()
    remain = int(max(0, _COOLDOWN_SECONDS - (now - last)))
    return remain == 0, remain


def register(bot: "MangsangBot") -> None:
    @app_commands.command(name="news_run_now", description="최근 뉴스 다이제스트를 즉시 생성합니다.")
    @app_commands.describe(hours="최근 N시간 범위(기본 12)")
    async def news_run_now(interaction: discord.Interaction, hours: app_commands.Range[int, 1, 168] = 12) -> None:
        if interaction.guild is None or interaction.user is None:
            await interaction.response.send_message("길드 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        if not bot.news_service or not bot.news_service.enabled():
            await interaction.response.send_message("뉴스 레이다 기능이 비활성입니다.", ephemeral=True)
            return

        ok, remain = _cooldown_ok(interaction.guild.id)
        if not ok:
            await interaction.response.send_message(
                f"너무 자주 실행할 수 없습니다. {remain}초 후 다시 시도해 주세요.",
                ephemeral=True,
            )
            return

        _LAST_RUN_AT_BY_GUILD[interaction.guild.id] = time.time()
        await interaction.response.defer(thinking=True, ephemeral=True)
        result = await bot.news_service.run_digest(
            bot=bot,
            guild_id=interaction.guild.id,
            window_hours=int(hours),
            kind="manual",
        )
        await interaction.followup.send(
            "\n".join(
                [
                    "뉴스 다이제스트를 생성했습니다.",
                    f"- digest_id: `{result.digest_id}`",
                    f"- jump_url: {result.jump_url or '(post failed)' }",
                    f"- items: `{result.items_count}`",
                    f"- skipped(dedupe): `{result.skipped_count}`",
                    f"- errors: `{result.error_count}`",
                ]
            ),
            ephemeral=True,
        )

    @app_commands.command(name="news_config", description="뉴스 레이다 설정을 확인합니다.")
    async def news_config(interaction: discord.Interaction) -> None:
        news_cfg = bot.settings.raw.get("news", {}) if hasattr(bot.settings, "raw") else {}
        scheduler_cfg = bot.settings.scheduler
        enabled = bool(news_cfg.get("enabled", False))
        topics = news_cfg.get("topics") or []
        per_topic = int(news_cfg.get("per_topic_limit", 8) or 8)
        max_total = int(news_cfg.get("max_total_items", 40) or 40)
        window = int(news_cfg.get("window_hours", 12) or 12)
        dedupe = int(news_cfg.get("dedupe_days", 7) or 7)
        auto_create = bool(news_cfg.get("auto_create_digest_channel", True))
        default_channel_name = str(news_cfg.get("default_digest_channel_name", "🛰️-뉴스-레이다") or "🛰️-뉴스-레이다")

        digest_channel = bot.settings.channels.get("news_digest", "")
        log_channel = bot.settings.channels.get("news_log", "")
        morning_cron = str(scheduler_cfg.get("news_digest_morning_cron", "0 8 * * *"))
        evening_cron = str(scheduler_cfg.get("news_digest_evening_cron", "0 18 * * 1-5"))
        runtime = build_news_runtime(
            bot.storage.read_jsonl("news_digests"),
            bot.storage.read_jsonl("ops_events"),
            timezone_name=bot.settings.timezone,
            morning_cron=morning_cron,
            evening_cron=evening_cron,
        )

        lines = [
            "뉴스 레이다 설정",
            f"- enabled: {enabled}",
            f"- digest_channel: `{digest_channel}`",
            f"- log_channel: `{log_channel}`",
            f"- schedule(morning): `{morning_cron}`",
            f"- schedule(evening): `{evening_cron}`",
            f"- window_hours: `{window}`",
            f"- per_topic_limit: `{per_topic}`",
            f"- max_total_items: `{max_total}`",
            f"- dedupe_days: `{dedupe}`",
            f"- auto_create_digest_channel: `{auto_create}`",
            f"- default_digest_channel_name: `{default_channel_name}`",
            f"- topics: `{len(topics)}`",
            f"- last_run_at: `{runtime.get('last_run_at') or '-'}`",
            f"- last_result: `{runtime.get('last_result') or '-'}`",
            f"- next_run_at: `{runtime.get('next_run_at') or '-'}`",
            f"- last_items_count: `{runtime.get('last_items_count', 0)}`",
            f"- last_failure_at: `{runtime.get('last_failure_at') or '-'}`",
            f"- last_failure: `{runtime.get('last_failure') or '-'}`",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    if bot.command_guild:
        bot.tree.add_command(news_run_now, guild=bot.command_guild)
        bot.tree.add_command(news_config, guild=bot.command_guild)
    else:
        bot.tree.add_command(news_run_now)
        bot.tree.add_command(news_config)
