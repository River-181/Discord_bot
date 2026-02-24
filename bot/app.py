from __future__ import annotations

import asyncio
import logging
import os
import ssl
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
import certifi
import discord
from discord import app_commands
from dotenv import load_dotenv

from bot.commands import register_all
from bot.config import load_settings
from bot.services.retry import retry_discord_call
from bot.scheduler import BotScheduler
from bot.services.storage import DataFiles, StorageService
from bot.services.summarizer import SummarizerService
from bot.services.news import NewsService
from bot.services.music import MusicService
from bot.services.dm_assistant import DMAssistantService, parse_dm_command
from bot.services.curation import CurationService
from bot.services.event_reminder import EventReminderService
from bot.services.warroom import WarroomService
from bot.triggers.deep_work import DeepWorkGuard
from bot.triggers.thread_hygiene import ThreadHygieneEngine
from bot.utils import find_text_channel_by_name
from bot.views.music_controls import MusicControlsView

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("mangsang-orbit-assistant")


class MangsangBot(discord.Client):
    def __init__(self, root_dir: Path) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.messages = True

        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        super().__init__(intents=intents, connector=connector)
        self.tree = app_commands.CommandTree(self)

        self.root_dir = root_dir
        self.settings = load_settings(root_dir)
        self.tzinfo = ZoneInfo(self.settings.timezone)

        self.command_guild = (
            discord.Object(id=self.settings.target_guild_id)
            if self.settings.target_guild_id
            else None
        )

        files = DataFiles(
            decisions=str(self.settings.data.get("decisions_file", "decisions.jsonl")),
            warrooms=str(self.settings.data.get("warrooms_file", "warrooms.jsonl")),
            summaries=str(self.settings.data.get("summaries_file", "summaries.jsonl")),
            ops_events=str(self.settings.data.get("ops_events_file", "ops_events.ndjson")),
            news_items=str(self.settings.data.get("news_items_file", "news_items.jsonl")),
            news_digests=str(self.settings.data.get("news_digests_file", "news_digests.jsonl")),
            snapshots_dir=str(self.settings.data.get("snapshots_dir", "snapshots")),
            curation_submissions=str(
                self.settings.data.get("curation_submissions_file", "curation_submissions.jsonl")
            ),
            curation_posts=str(self.settings.data.get("curation_posts_file", "curation_posts.jsonl")),
        )
        self.storage = StorageService(self.settings.data_dir, files)

        self.summarizer = SummarizerService(
            model=str(self.settings.gemini.get("model", "gemini-1.5-flash")),
            timeout_seconds=int(self.settings.gemini.get("timeout_seconds", 25)),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
        )

        self.news_service = NewsService(
            timezone=self.settings.timezone,
            channels_config=self.settings.channels,
            news_config=self.settings.raw.get("news", {}),
            storage=self.storage,
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            gemini_model=str(self.settings.gemini.get("model", "gemini-1.5-flash")),
            gemini_timeout_seconds=int(self.settings.gemini.get("timeout_seconds", 25)),
        )
        self.music_service = MusicService(
            timezone=self.settings.timezone,
            config=self.settings.music,
            storage=self.storage,
            loop_getter=lambda: self.loop,
            guild_getter=lambda guild_id: self.get_guild(guild_id),
        )
        self.music_service.set_control_panel_presenter(self._render_music_control_panel)
        self.curation_service = CurationService(
            timezone=self.settings.timezone,
            config=self.settings.curation,
            channels_config=self.settings.channels,
            storage=self.storage,
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            gemini_model=str(self.settings.gemini.get("model", "gemini-1.5-flash")),
            gemini_timeout_seconds=int(self.settings.gemini.get("timeout_seconds", 25)),
        )

        self.warroom_service = WarroomService(
            timezone=self.settings.timezone,
            config=self.settings.warroom,
            channels_config=self.settings.channels,
            storage=self.storage,
            summarizer=self.summarizer,
        )
        self.dm_assistant = DMAssistantService(
            timezone=self.settings.timezone,
            target_guild_id=self.settings.target_guild_id,
            config=self.settings.dm_assistant,
        )
        self.event_reminder_service = EventReminderService(
            timezone=self.settings.timezone,
            config=self.settings.event_reminder,
            channels_config=self.settings.channels,
            storage=self.storage,
        )

        self.thread_hygiene = ThreadHygieneEngine(
            timezone=self.settings.timezone,
            config=self.settings.thread_hygiene,
        )
        self.deep_work_guard = DeepWorkGuard(
            timezone=self.settings.timezone,
            config=self.settings.deep_work,
        )
        self.bot_scheduler = BotScheduler(timezone=self.settings.timezone)

    def _command_option_names(self, commands: list[app_commands.AppCommand], name: str) -> list[str]:
        for command in commands:
            if command.name == name:
                return sorted(option.name for option in command.options)
        return []

    async def _verify_and_record_command_sync(
        self,
        synced_count: int,
        scope_mode: str,
    ) -> None:
        payload: dict[str, object] = {
            "guild_id": self.settings.target_guild_id,
            "channel_id": None,
            "user_id": None,
            "command_name": "sync",
            "scope_mode": scope_mode,
            "synced_count": synced_count,
            "target_guild_id": self.settings.target_guild_id,
        }
        try:
            guild_commands: list[app_commands.AppCommand] = []
            if self.command_guild:
                guild_commands = await self.tree.fetch_commands(guild=self.command_guild)
            global_commands = await self.tree.fetch_commands()

            guild_names = sorted(command.name for command in guild_commands)
            global_names = sorted(command.name for command in global_commands)
            has_meeting = "meeting_summary" in guild_names
            has_meeting_v2 = "meeting_summary_v2" in guild_names
            opts_v1 = self._command_option_names(guild_commands, "meeting_summary")
            opts_v2 = self._command_option_names(guild_commands, "meeting_summary_v2")
            options_equal = bool(opts_v1 and opts_v2 and opts_v1 == opts_v2)

            payload.update(
                {
                    "guild_command_count": len(guild_commands),
                    "global_command_count": len(global_commands),
                    "guild_command_names": guild_names,
                    "global_command_names": global_names,
                    "has_meeting_summary": has_meeting,
                    "has_meeting_summary_v2": has_meeting_v2,
                    "meeting_option_names": opts_v1,
                    "meeting_v2_option_names": opts_v2,
                    "meeting_options_equal": options_equal,
                }
            )
            logger.info(
                "command sync verified: guild=%d global=%d has_meeting=%s has_meeting_v2=%s options_equal=%s",
                len(guild_commands),
                len(global_commands),
                has_meeting,
                has_meeting_v2,
                options_equal,
            )
            if self.command_guild and global_commands:
                logger.warning("global commands should be empty in guild scope mode: %s", global_names)
        except Exception as exc:
            payload["verify_error"] = f"{type(exc).__name__}: {exc}"
            logger.warning("command sync verification failed: %s", exc)

        await self.storage.append_ops_event("command_sync_completed", payload)

    async def setup_hook(self) -> None:
        register_all(self)
        self.tree.on_error = self._on_app_command_error
        if self.command_guild:
            synced = await self.tree.sync(guild=self.command_guild)
            logger.info("synced %d guild commands", len(synced))
            await self._verify_and_record_command_sync(len(synced), scope_mode="guild")
        else:
            synced = await self.tree.sync()
            logger.info("synced %d global commands", len(synced))
            await self._verify_and_record_command_sync(len(synced), scope_mode="global")

    async def _on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        logger.exception("app command error: %s", error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"명령 실행 중 오류가 발생했습니다: {type(error).__name__}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"명령 실행 중 오류가 발생했습니다: {type(error).__name__}",
                    ephemeral=True,
                )
        except Exception as send_exc:
            logger.warning("failed to send app command error response: %s", send_exc)

    async def _post_ops_log(self, guild: discord.Guild, text: str) -> None:
        channel_name = self.settings.channels.get("automation_log", "")
        if not channel_name:
            return
        ops_channel = find_text_channel_by_name(guild, channel_name)
        if not ops_channel:
            return

        for i in range(0, len(text), 1800):
            chunk = text[i : i + 1800]
            await retry_discord_call(
                lambda chunk_text=chunk: ops_channel.send(f"🧠 망상궤도 비서 로그: {chunk_text}")
            )

    async def _render_music_control_panel(self, guild: discord.Guild) -> None:
        if not self.music_service.enabled:
            return
        state = self.music_service.get_state(guild.id)
        if state is None:
            return

        channel = self.music_service.resolve_control_channel(guild, fallback_channel_id=state.text_channel_id)
        if channel is None:
            return

        current_track = state.current
        lines: list[str] = []
        if current_track:
            lines.append(f"🎵 지금 재생: **{current_track.title}**")
            lines.append(f"요청자: <@{current_track.requester_id}>")
            lines.append(f"출처: `{current_track.source_type}`")
            if current_track.duration_sec:
                lines.append(f"길이: `{current_track.duration_sec // 60}분 {current_track.duration_sec % 60:02d}초`")
        else:
            lines.append("🎵 현재 재생 중인 트랙이 없습니다.")

        queue_items = list(state.queue)
        if queue_items:
            queue_preview = ", ".join(track.title for track in queue_items[:4])
            if len(queue_items) > 4:
                queue_preview = f"{queue_preview} +{len(queue_items) - 4}"
            lines.append(f"다음 큐: {queue_preview}")
        else:
            lines.append("다음 큐: 비어 있음")

        lines.append(f"음량: `{self.music_service.volume_percent(guild.id)}%`")
        lines.append(f"상태: {'재생중' if (guild.voice_client and guild.voice_client.is_playing()) else '대기'}")

        embed = discord.Embed(
            title="🎵 음악 컨트롤",
            description="\n".join(lines),
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"guild_id={guild.id}")

        view = MusicControlsView(bot=self, guild_id=guild.id)

        edit_last = str(self.music_service.panel_update_mode) == "edit_last"
        should_edit = (
            state.control_message_id is not None
            and state.control_channel_id == channel.id
        )

        if edit_last and should_edit:
            try:
                control_message = await channel.fetch_message(int(state.control_message_id))
                await control_message.edit(embed=embed, view=view)
                return
            except discord.NotFound:
                self.music_service.clear_control_message(guild.id)
            except Exception as exc:  # pragma: no cover
                LOGGER = logging.getLogger("mangsang-orbit-assistant")
                LOGGER.debug("music panel edit failed: %s", exc)
                state.control_channel_id = channel.id

        sent = await channel.send(embed=embed, view=view)
        self.music_service.set_control_message(
            guild.id,
            channel_id=channel.id,
            message_id=sent.id,
        )

    async def on_ready(self) -> None:
        logger.info("connected as %s (%s)", self.user, self.user.id if self.user else "-")
        logger.info("target_guild_id=%s", self.settings.target_guild_id)
        if self.settings.target_guild_id and self.curation_service.enabled():
            guild = self.get_guild(int(self.settings.target_guild_id))
            if guild:
                try:
                    await self.curation_service.ensure_infrastructure(guild)
                except Exception as infra_exc:
                    logger.warning("curation infra ensure failed: %s", infra_exc)

        if not self.bot_scheduler.started:
            inactivity_cron = str(self.settings.scheduler.get("inactivity_check_cron", "0 * * * *"))
            backup_cron = str(self.settings.scheduler.get("backup_cron", "30 0 * * *"))
            self.bot_scheduler.add_cron_job("inactivity_scan", inactivity_cron, self._scheduled_inactivity_scan)
            self.bot_scheduler.add_cron_job("daily_backup", backup_cron, self._scheduled_backup)

            news_cfg = self.settings.raw.get("news", {}) if hasattr(self.settings, "raw") else {}
            news_enabled = bool(news_cfg.get("enabled", False))
            if news_enabled:
                morning_cron = str(self.settings.scheduler.get("news_digest_morning_cron", "0 9 * * 1-5"))
                evening_cron = str(self.settings.scheduler.get("news_digest_evening_cron", "0 18 * * 1-5"))
                self.bot_scheduler.add_cron_job(
                    "news_digest_morning",
                    morning_cron,
                    lambda: self._scheduled_news_digest(kind="morning"),
                )
                self.bot_scheduler.add_cron_job(
                    "news_digest_evening",
                    evening_cron,
                    lambda: self._scheduled_news_digest(kind="evening"),
                )
            music_cfg = self.settings.music if hasattr(self.settings, "music") else {}
            if bool(music_cfg.get("enabled", False)):
                music_housekeeping_cron = str(self.settings.scheduler.get("music_housekeeping_cron", "*/5 * * * *"))
                self.bot_scheduler.add_cron_job(
                    "music_housekeeping",
                    music_housekeeping_cron,
                    self._scheduled_music_housekeeping,
                )
            event_reminder_cfg = self.settings.event_reminder if hasattr(self.settings, "event_reminder") else {}
            event_reminder_cron = str(event_reminder_cfg.get("scan_cron", "*/1 * * * *"))
            self.bot_scheduler.add_cron_job(
                "event_reminder_scan",
                event_reminder_cron,
                self._scheduled_event_reminder_scan,
            )
            self.bot_scheduler.start()
            logger.info("scheduler started")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not message.guild:
            try:
                dm_cmd = parse_dm_command(message.content or "")
                if (
                    self.curation_service.enabled()
                    and self.curation_service.is_dm_ingest_enabled()
                    and dm_cmd.intent == "unknown"
                    and self.curation_service.is_curation_candidate(message)
                ):
                    submission_id = await self.curation_service.ingest_message(
                        bot=self,
                        message=message,
                        source="dm",
                    )
                    if submission_id:
                        await message.channel.send(
                            "큐레이션 접수 완료. 운영자 승인 후 전용 채널에 게시됩니다.\n"
                            f"- submission_id: `{submission_id}`"
                        )
                    else:
                        await message.channel.send("큐레이션 접수 실패: 대상 길드 또는 인박스 채널을 찾지 못했습니다.")
                    await self.storage.append_ops_event(
                        "dm_assistant_invoked",
                        {
                            "user_id": message.author.id,
                            "channel_id": message.channel.id,
                            "command_name": "curation_ingest",
                            "result": "ok",
                        },
                    )
                    return
                dm_result = await self.dm_assistant.handle_dm(self, message)
                await self.storage.append_ops_event(
                    "dm_assistant_invoked",
                    {
                        "user_id": message.author.id,
                        "channel_id": message.channel.id,
                        "command_name": dm_result.get("command_name"),
                        "result": dm_result.get("result"),
                    },
                )
            except Exception as exc:
                logger.exception("dm handler error: %s", exc)
                await self.storage.append_ops_event(
                    "dm_assistant_error",
                    {
                        "user_id": message.author.id,
                        "channel_id": message.channel.id,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
            return
        try:
            if self.curation_service.should_ingest_channel_message(message):
                submission_id = await self.curation_service.ingest_message(
                    bot=self,
                    message=message,
                    source="channel",
                    target_guild_id=message.guild.id,
                )
                await retry_discord_call(
                    lambda: message.add_reaction("📥")
                )
                if submission_id:
                    await retry_discord_call(
                        lambda: message.reply(
                            f"큐레이션 접수됨: `{submission_id}` (승인 대기)",
                            mention_author=False,
                            delete_after=15,
                        )
                    )
                return
            await self.warroom_service.touch_activity_from_message(message)
            await self.thread_hygiene.handle_message(message)
            await self.deep_work_guard.handle_message(message)
        except Exception as exc:
            logger.exception("on_message handler error: %s", exc)
            if message.guild:
                try:
                    await self._post_ops_log(
                        message.guild,
                        f"`on_message` 예외: {type(exc).__name__}: {exc}",
                    )
                except Exception as log_error:
                    logger.debug("ops log post failed in on_message: %s", log_error)
            await self.storage.append_ops_event(
                "on_message_error",
                {
                    "error": str(exc),
                    "channel_id": message.channel.id,
                    "guild_id": message.guild.id,
                },
            )

    async def _scheduled_inactivity_scan(self) -> None:
        try:
            warnings, archived = await self.warroom_service.run_inactivity_scan(
                bot=self,
                guild_id=self.settings.target_guild_id,
            )
            await self.storage.append_ops_event(
                "scheduled_inactivity_scan",
                {"warnings": warnings, "archived": archived},
            )
            if self.command_guild:
                guild = self.get_guild(self.command_guild.id)
                if guild:
                    post_mode = str(self.settings.scheduler.get("inactivity_scan_post_mode", "only_when_action"))
                    if post_mode != "never":
                        should_post = post_mode == "always" or warnings > 0 or archived > 0
                        if should_post:
                            await self._post_ops_log(
                                guild,
                                f"워크룸 비활성 스캔 완료. warnings={warnings}, archived={archived}",
                            )
        except Exception as exc:
            logger.exception("scheduled_inactivity_scan failed: %s", exc)
            if self.command_guild:
                guild = self.get_guild(self.command_guild.id)
                if guild:
                    await self._post_ops_log(
                        guild,
                        f"워크룸 비활성 스캔 실패: {type(exc).__name__}: {exc}",
                    )

    async def _scheduled_backup(self) -> None:
        try:
            snapshot_dir = await self.storage.create_daily_snapshot()
            await self.storage.append_ops_event(
                "scheduled_backup",
                {"snapshot_dir": str(snapshot_dir)},
                idempotency_key=f"backup:{snapshot_dir.name}",
            )
            if self.command_guild:
                guild = self.get_guild(self.command_guild.id)
                if guild:
                    await self._post_ops_log(guild, f"백업 완료: {snapshot_dir}")
        except Exception as exc:
            logger.exception("scheduled_backup failed: %s", exc)
            if self.command_guild:
                guild = self.get_guild(self.command_guild.id)
                if guild:
                    await self._post_ops_log(
                        guild,
                        f"백업 실패: {type(exc).__name__}: {exc}",
                    )

    async def _scheduled_news_digest(self, kind: str) -> None:
        try:
            if not self.news_service or not self.news_service.enabled():
                return
            guild_id = self.settings.target_guild_id
            if not guild_id:
                return
            await self.news_service.run_digest(
                bot=self,
                guild_id=int(guild_id),
                window_hours=int(self.settings.raw.get("news", {}).get("window_hours", 12) or 12),
                kind=kind,
            )
        except Exception as exc:
            logger.exception("scheduled_news_digest failed: %s", exc)
            await self.storage.append_ops_event(
                "news_post_error",
                {"kind": kind, "error": f"{type(exc).__name__}: {exc}"},
            )

    async def _scheduled_music_housekeeping(self) -> None:
        if not self.music_service.enabled:
            return
        try:
            await self.music_service.housekeeping()
        except Exception as exc:
            logger.exception("scheduled_music_housekeeping failed: %s", exc)
            await self.storage.append_ops_event(
                "music_error",
                {
                    "guild_id": self.settings.target_guild_id,
                    "channel_id": None,
                    "user_id": None,
                    "command_name": "music_housekeeping",
                    "result": f"{type(exc).__name__}: {exc}",
                },
            )

    async def _scheduled_event_reminder_scan(self) -> None:
        try:
            await self.event_reminder_service.scan_and_send(
                bot=self,
                guild_id=self.settings.target_guild_id,
            )
        except Exception as exc:
            logger.exception("scheduled_event_reminder_scan failed: %s", exc)
            await self.storage.append_ops_event(
                "event_reminder_error",
                {
                    "guild_id": self.settings.target_guild_id,
                    "channel_id": None,
                    "user_id": None,
                    "command_name": "event_reminder_scan",
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )

    async def close(self) -> None:
        try:
            await self.music_service.shutdown()
        except Exception as exc:  # pragma: no cover - shutdown safety
            logger.debug("music shutdown error: %s", exc)
        self.bot_scheduler.shutdown()
        await super().close()


async def _run() -> None:
    root_dir = Path(__file__).resolve().parent.parent
    load_dotenv(root_dir / ".env")
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())

    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is required")

    bot = MangsangBot(root_dir=root_dir)
    try:
        await bot.start(token)
    finally:
        await bot.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
