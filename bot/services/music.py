from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import discord

from bot.services.retry import retry_discord_call
from bot.services.storage import StorageService
from bot.utils import find_text_channel_by_name, truncate_text

LOGGER = logging.getLogger("mangsang-orbit-assistant")

YOUTUBE_HOST_PATTERN = re.compile(r"(youtube\.com|youtu\.be)$", re.IGNORECASE)
DEFAULT_OPUS_CANDIDATES = [
    "/opt/homebrew/opt/opus/lib/libopus.0.dylib",
    "/opt/homebrew/lib/libopus.0.dylib",
    "/usr/local/opt/opus/lib/libopus.0.dylib",
    "/usr/local/lib/libopus.0.dylib",
]


class MusicError(RuntimeError):
    pass


class PolicyError(MusicError):
    pass


@dataclass(frozen=True)
class Track:
    title: str
    stream_url: str
    web_url: str
    duration_sec: int | None
    requester_id: int
    source_type: str


@dataclass
class GuildMusicState:
    guild_id: int
    voice_channel_id: int | None = None
    queue: deque[Track] = field(default_factory=deque)
    current: Track | None = None
    last_activity_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    volume: float = 0.7
    text_channel_id: int | None = None
    control_message_id: int | None = None
    control_channel_id: int | None = None


ControlPresenter = Callable[[discord.Guild], Awaitable[None]]


@dataclass(frozen=True)
class EnqueueResult:
    track: Track
    queue_length: int
    started_now: bool


@dataclass(frozen=True)
class QueueSnapshot:
    current: Track | None
    items: list[Track]
    page: int
    total_pages: int
    total_items: int


class MusicService:
    def __init__(
        self,
        *,
        timezone: str,
        config: dict[str, Any] | None,
        storage: StorageService,
        loop_getter: Callable[[], asyncio.AbstractEventLoop],
        guild_getter: Callable[[int], discord.Guild | None],
    ) -> None:
        cfg = config or {}
        self.timezone = timezone
        self.tz = ZoneInfo(timezone)
        self.storage = storage
        self.loop_getter = loop_getter
        self.guild_getter = guild_getter

        self.enabled = bool(cfg.get("enabled", False))
        self.source_policy = str(cfg.get("source_policy", "hybrid")).strip().lower() or "hybrid"
        self.allowlist_user_ids = {int(x) for x in cfg.get("allowlist_user_ids", []) if str(x).isdigit()}
        self.default_voice_channel = str(cfg.get("default_voice_channel", "음악 라운지")).strip()
        self.idle_disconnect_minutes = int(cfg.get("idle_disconnect_minutes", 10) or 10)
        self.max_queue_size = int(cfg.get("max_queue_size", 30) or 30)
        self.max_track_minutes = int(cfg.get("max_track_minutes", 180) or 180)
        self.notice_policy = str(cfg.get("notice_policy", "low_noise")).strip().lower() or "low_noise"
        self.default_volume = max(0.0, min(2.0, float(cfg.get("default_volume", 70)) / 100.0))
        self.ffmpeg_path = os.getenv("FFMPEG_PATH") or str(cfg.get("ffmpeg_path", "ffmpeg"))
        self.opus_library_path = os.getenv("OPUS_LIBRARY_PATH") or str(cfg.get("opus_library_path", "")).strip()

        self.show_control_card = bool(cfg.get("show_control_card", True))
        self.default_control_channel = str(cfg.get("default_control_channel", "auto")).strip() or "auto"
        self.announce_now_playing = bool(cfg.get("announce_now_playing", True))
        self.panel_update_mode = str(cfg.get("panel_update_mode", "edit_last")).strip().lower() or "edit_last"
        self.music_panel_command_enabled = bool(cfg.get("music_panel_command_enabled", True))

        self._states: dict[int, GuildMusicState] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._nacl_available = importlib.util.find_spec("nacl") is not None
        self._ytdlp_available = importlib.util.find_spec("yt_dlp") is not None
        self._panel_presenter: ControlPresenter | None = None
        self._opus_attempted = False
        self._opus_loaded = discord.opus.is_loaded()
        if self._nacl_available and not self._opus_loaded:
            self._ensure_opus_loaded()

    def set_control_panel_presenter(self, presenter: ControlPresenter | None) -> None:
        self._panel_presenter = presenter

    def _should_show_control_panel(self) -> bool:
        return self.show_control_card

    async def refresh_control_panel(self, guild: discord.Guild, *, reason: str = "refresh") -> None:
        if not self._should_show_control_panel() or self._panel_presenter is None:
            return
        state = self._states.get(guild.id)
        if not state:
            return
        try:
            await self._panel_presenter(guild)
            await self._log(
                "music_now_playing_announced",
                {
                    "guild_id": guild.id,
                    "channel_id": state.text_channel_id,
                    "user_id": None,
                    "command_name": "music_panel",
                    "result": reason,
                },
            )
        except Exception as exc:  # pragma: no cover
            await self._log(
                "music_error",
                {
                    "guild_id": guild.id,
                    "channel_id": state.text_channel_id,
                    "user_id": None,
                    "command_name": "music_panel",
                    "result": f"refresh_control_panel:{type(exc).__name__}",
                },
            )

    def get_state(self, guild_id: int) -> GuildMusicState | None:
        return self._states.get(guild_id)

    def get_or_create_state(self, guild_id: int) -> GuildMusicState:
        return self._state(guild_id)

    def set_control_message(self, guild_id: int, *, channel_id: int | None, message_id: int | None) -> None:
        state = self._state(guild_id)
        if channel_id is not None:
            state.control_channel_id = channel_id
        state.control_message_id = message_id

    def clear_control_message(self, guild_id: int) -> None:
        state = self._state(guild_id)
        state.control_channel_id = None
        state.control_message_id = None

    def resolve_control_channel(self, guild: discord.Guild, *, fallback_channel_id: int | None = None) -> discord.TextChannel | None:
        if self.default_control_channel not in {"", "auto"}:
            channel = find_text_channel_by_name(guild, self.default_control_channel)
            if channel is not None:
                return channel

        if fallback_channel_id:
            candidate = guild.get_channel(fallback_channel_id)
            if isinstance(candidate, discord.TextChannel):
                return candidate

        if state := self._states.get(guild.id):
            text_channel = guild.get_channel(state.text_channel_id or 0)
            if isinstance(text_channel, discord.TextChannel):
                return text_channel

        return None

    def diagnostics(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "source_policy": self.source_policy,
            "allowlist_count": len(self.allowlist_user_ids),
            "notice_policy": self.notice_policy,
            "nacl_available": self._nacl_available,
            "opus_loaded": self._opus_loaded,
            "ytdlp_available": self._ytdlp_available,
            "active_sessions": sum(
                1
                for guild_id in self._states.keys()
                if ((guild := self.guild_getter(guild_id)) is not None)
                and (voice_client := getattr(guild, "voice_client", None))
                and voice_client.is_connected()
            ),
        }

    def active_sessions(self) -> int:
        return len(self._states)

    def is_user_allowlisted(self, user_id: int) -> bool:
        return user_id in self.allowlist_user_ids

    def voice_dependency_ok(self) -> bool:
        return self._nacl_available and self._ensure_opus_loaded()

    def ytdlp_ok(self) -> bool:
        return self._ytdlp_available

    def _ensure_opus_loaded(self) -> bool:
        if discord.opus.is_loaded():
            self._opus_loaded = True
            return True
        if self._opus_attempted:
            return self._opus_loaded

        self._opus_attempted = True
        candidates: list[str] = []
        if self.opus_library_path:
            candidates.append(self.opus_library_path)
        candidates.extend(DEFAULT_OPUS_CANDIDATES)
        candidates.append("libopus.0.dylib")

        seen: set[str] = set()
        for path in candidates:
            if not path or path in seen:
                continue
            seen.add(path)
            try:
                discord.opus.load_opus(path)
            except Exception:
                continue
            if discord.opus.is_loaded():
                self._opus_loaded = True
                LOGGER.info("loaded opus library: %s", path)
                return True

        self._opus_loaded = discord.opus.is_loaded()
        if not self._opus_loaded:
            LOGGER.warning(
                "Opus library is not loaded. Set OPUS_LIBRARY_PATH or install opus (brew install opus)."
            )
        return self._opus_loaded

    async def _log(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            await self.storage.append_ops_event(event_type, payload)
        except Exception as exc:  # pragma: no cover
            LOGGER.debug("music log append failed: %s", exc)

    def _lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._locks.get(guild_id)
        if not lock:
            lock = asyncio.Lock()
            self._locks[guild_id] = lock
        return lock

    def _state(self, guild_id: int) -> GuildMusicState:
        state = self._states.get(guild_id)
        if state is None:
            state = GuildMusicState(
                guild_id=guild_id,
                volume=self.default_volume,
                last_activity_at=datetime.now(UTC),
            )
            self._states[guild_id] = state
        return state

    @staticmethod
    def _is_url(value: str) -> bool:
        try:
            parsed = urlparse(value)
            return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except Exception:
            return False

    @staticmethod
    def _is_youtube_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            host = (parsed.netloc or "").lower()
            host = host.split(":")[0]
            host = host[4:] if host.startswith("www.") else host
            return bool(YOUTUBE_HOST_PATTERN.search(host))
        except Exception:
            return False

    @staticmethod
    def _looks_like_direct_media_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            path = (parsed.path or "").lower()
            if path.endswith(
                (
                    ".mp3",
                    ".m4a",
                    ".aac",
                    ".flac",
                    ".ogg",
                    ".opus",
                    ".wav",
                    ".m3u8",
                    ".mpd",
                )
            ):
                return True
            query = (parsed.query or "").lower()
            if "stream" in query or "audio" in query:
                return True
            return False
        except Exception:
            return False

    def _validate_source_policy(self, query_or_url: str, requester_id: int) -> tuple[str, str]:
        value = query_or_url.strip()
        if not value:
            raise PolicyError("재생할 URL 또는 검색어를 입력해 주세요.")

        is_url = self._is_url(value)
        if is_url and self._is_youtube_url(value):
            if self.is_user_allowlisted(requester_id):
                return ("youtube_url", value)
            raise PolicyError("YouTube 재생은 운영 allowlist 사용자만 허용됩니다.")

        if is_url:
            return ("direct_url", value)

        if self.is_user_allowlisted(requester_id):
            return ("youtube_search", value)
        raise PolicyError("검색어 재생은 운영 allowlist 사용자만 허용됩니다. 직접 URL을 입력해 주세요.")

    async def _resolve_with_ytdlp(self, query: str, *, requester_id: int, source_type: str) -> Track:
        if not self._ytdlp_available:
            raise MusicError("yt-dlp 의존성이 없어 해당 소스를 재생할 수 없습니다.")

        def _extract() -> dict[str, Any]:
            import yt_dlp  # type: ignore

            opts = {
                "format": "bestaudio/best",
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "default_search": "ytsearch1",
                "extract_flat": False,
                "source_address": "0.0.0.0",
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(query, download=False)

        last_error: Exception | None = None
        for _ in range(2):
            try:
                info = await asyncio.to_thread(_extract)
                break
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(0.4)
        else:
            raise MusicError(f"yt-dlp 추출 실패: {type(last_error).__name__}") from last_error

        data = info
        if isinstance(data, dict) and data.get("entries"):
            entries = data.get("entries") or []
            if entries:
                data = entries[0]
        if not isinstance(data, dict):
            raise MusicError("재생 가능한 미디어 정보를 찾지 못했습니다.")

        stream_url = str(data.get("url", "") or "").strip()
        web_url = str(data.get("webpage_url", "") or data.get("original_url", "") or query).strip()
        title = str(data.get("title", "") or "unknown").strip()
        duration_raw = data.get("duration")
        duration_sec = int(duration_raw) if isinstance(duration_raw, (int, float)) else None
        if duration_sec and duration_sec > self.max_track_minutes * 60:
            raise PolicyError(
                f"트랙 길이가 너무 깁니다. 최대 {self.max_track_minutes}분까지만 허용됩니다."
            )
        if not stream_url:
            raise MusicError("스트림 URL 추출에 실패했습니다.")

        return Track(
            title=title,
            stream_url=stream_url,
            web_url=web_url,
            duration_sec=duration_sec,
            requester_id=requester_id,
            source_type=source_type,
        )

    async def resolve_track(self, query_or_url: str, requester_id: int) -> Track:
        source_kind, value = self._validate_source_policy(query_or_url, requester_id)
        if source_kind == "direct_url":
            # Try yt-dlp first for platform page links (Bugs/SoundCloud/etc.) and fall back only for raw stream URLs.
            if self._ytdlp_available:
                try:
                    return await self._resolve_with_ytdlp(value, requester_id=requester_id, source_type="url")
                except PolicyError:
                    raise
                except Exception as exc:
                    LOGGER.info("direct url ytdlp resolve failed, fallback=%s url=%s", type(exc).__name__, value)
            if self._looks_like_direct_media_url(value):
                return Track(
                    title=truncate_text(value, 120),
                    stream_url=value,
                    web_url=value,
                    duration_sec=None,
                    requester_id=requester_id,
                    source_type="direct",
                )
            raise MusicError(
                "이 링크는 직접 재생 가능한 오디오 스트림이 아니거나 플랫폼 보호(DRM)로 차단되었습니다. "
                "지원 플랫폼 URL(yt-dlp 지원) 또는 직접 오디오 URL(mp3/m3u8 등)을 사용해 주세요."
            )
        if source_kind == "youtube_url":
            return await self._resolve_with_ytdlp(value, requester_id=requester_id, source_type="youtube")
        if source_kind == "youtube_search":
            query = value if value.startswith("ytsearch1:") else f"ytsearch1:{value}"
            return await self._resolve_with_ytdlp(query, requester_id=requester_id, source_type="search")
        raise MusicError("지원하지 않는 소스입니다.")

    async def join(
        self,
        *,
        guild: discord.Guild,
        channel: discord.VoiceChannel | discord.StageChannel,
        text_channel_id: int | None = None,
    ) -> discord.VoiceClient:
        if not self.enabled:
            raise MusicError("음악 기능이 비활성화되어 있습니다.")
        if not self.voice_dependency_ok():
            raise MusicError(
                "voice dependency missing: PyNaCl/Opus 확인 필요. "
                "brew install opus 후 OPUS_LIBRARY_PATH를 설정하고 봇을 재시작해 주세요."
            )

        lock = self._lock(guild.id)
        async with lock:
            voice_client = guild.voice_client
            try:
                if voice_client and voice_client.is_connected():
                    if voice_client.channel and voice_client.channel.id != channel.id:
                        await voice_client.move_to(channel)
                else:
                    voice_client = await channel.connect()
            except Exception as exc:
                await self._log(
                    "music_join_failed",
                    {
                        "guild_id": guild.id,
                        "channel_id": channel.id,
                        "user_id": None,
                        "command_name": "music_join",
                        "result": f"{type(exc).__name__}: {exc}",
                    },
                )
                raise MusicError(f"음성 채널 연결에 실패했습니다: {type(exc).__name__}") from exc

            state = self._state(guild.id)
            state.voice_channel_id = channel.id
            state.text_channel_id = text_channel_id
            state.last_activity_at = datetime.now(UTC)
            await self.refresh_control_panel(guild, reason="join")
            return voice_client

    async def leave(self, *, guild: discord.Guild, reason: str = "leave_command") -> bool:
        lock = self._lock(guild.id)
        async with lock:
            state = self._state(guild.id)
            voice_client = guild.voice_client
            if not voice_client or not voice_client.is_connected():
                state.current = None
                state.queue.clear()
                state.voice_channel_id = None
                state.last_activity_at = datetime.now(UTC)
                await self.refresh_control_panel(guild, reason="already_left")
                return False
            try:
                await voice_client.disconnect(force=False)
            except Exception as exc:
                raise MusicError(f"음성 채널 종료에 실패했습니다: {type(exc).__name__}") from exc
            state.current = None
            state.queue.clear()
            state.voice_channel_id = None
            state.last_activity_at = datetime.now(UTC)
            await self.refresh_control_panel(guild, reason=reason)
            await self._log(
                "music_track_finished",
                {
                    "guild_id": guild.id,
                    "channel_id": None,
                    "user_id": None,
                    "command_name": "music_leave",
                    "result": reason,
                },
            )
            return True

    def _create_audio_source(self, track: Track, *, volume: float) -> discord.AudioSource:
        source = discord.FFmpegPCMAudio(
            track.stream_url,
            executable=self.ffmpeg_path,
            before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            options="-vn",
        )
        return discord.PCMVolumeTransformer(source, volume=volume)

    def _should_announce_now_playing(self) -> bool:
        return self.announce_now_playing and self.notice_policy in {"low_noise", "standard"}

    def _resolve_announce_channel(self, guild: discord.Guild, text_channel_id: int | None):
        if not text_channel_id:
            return None
        channel = None
        get_channel_or_thread = getattr(guild, "get_channel_or_thread", None)
        if callable(get_channel_or_thread):
            channel = get_channel_or_thread(int(text_channel_id))
        if channel is None:
            channel = guild.get_channel(int(text_channel_id))
        if channel is None or not hasattr(channel, "send"):
            return None
        return channel

    async def _announce_now_playing(self, guild: discord.Guild, state: GuildMusicState, track: Track) -> None:
        if not self._should_announce_now_playing():
            return
        channel = self._resolve_announce_channel(guild, state.text_channel_id)
        if channel is None:
            return

        title = truncate_text(track.title, 120)
        lines = [
            f"🎵 지금 재생 중: **{title}**",
            f"요청자: <@{track.requester_id}> · 소스: `{track.source_type}`",
        ]
        if track.duration_sec:
            lines.append(f"길이: `{track.duration_sec // 60}분 {track.duration_sec % 60:02d}초`")
        if track.web_url:
            lines.append(track.web_url)

        try:
            await retry_discord_call(lambda: channel.send("\n".join(lines)))
        except Exception as exc:
            await self._log(
                "music_error",
                {
                    "guild_id": guild.id,
                    "channel_id": state.text_channel_id,
                    "user_id": track.requester_id,
                    "command_name": "music_announce",
                    "result": f"{type(exc).__name__}: {exc}",
                },
            )

    async def _start_next_locked(self, guild: discord.Guild) -> bool:
        state = self._state(guild.id)
        voice_client = guild.voice_client
        if not voice_client or not voice_client.is_connected():
            state.current = None
            await self.refresh_control_panel(guild, reason="connection_lost")
            return False
        if voice_client.is_playing() or voice_client.is_paused():
            return False
        if not state.queue:
            state.current = None
            await self.refresh_control_panel(guild, reason="queue_empty")
            return False

        next_track = state.queue.popleft()
        state.current = next_track
        state.last_activity_at = datetime.now(UTC)
        try:
            source = self._create_audio_source(next_track, volume=state.volume)
        except Exception as exc:
            state.current = None
            await self._log(
                "music_error",
                {
                    "guild_id": guild.id,
                    "channel_id": state.text_channel_id,
                    "user_id": next_track.requester_id,
                    "command_name": "music_play",
                    "result": f"ffmpeg_source_error:{type(exc).__name__}",
                },
            )
            raise MusicError(f"오디오 소스 생성 실패: {type(exc).__name__}") from exc

        def _after_play(err: Exception | None) -> None:
            loop = self.loop_getter()
            asyncio.run_coroutine_threadsafe(self._on_track_end(guild.id, err), loop)

        try:
            voice_client.play(source, after=_after_play)
        except Exception as exc:
            state.current = None
            await self._log(
                "music_error",
                {
                    "guild_id": guild.id,
                    "channel_id": state.text_channel_id,
                    "user_id": next_track.requester_id,
                    "command_name": "music_play",
                    "result": f"voice_play_error:{type(exc).__name__}",
                },
            )
            raise MusicError(f"트랙 재생 실패: {type(exc).__name__}") from exc

        await self._log(
            "music_track_started",
            {
                "guild_id": guild.id,
                "channel_id": state.text_channel_id,
                "user_id": next_track.requester_id,
                "command_name": "music_play",
                "result": "ok",
                "title": next_track.title,
                "source_type": next_track.source_type,
            },
        )
        await self._announce_now_playing(guild, state, next_track)
        await self.refresh_control_panel(guild, reason="track_started")
        return True

    def volume_percent(self, guild_id: int) -> int:
        state = self._states.get(guild_id)
        raw = state.volume if state else self.default_volume
        return int(round(raw * 100))

    async def set_volume(self, *, guild: discord.Guild, percent: int) -> tuple[int, bool]:
        normalized = max(0.0, min(2.0, float(percent) / 100.0))
        state = self._state(guild.id)
        state.volume = normalized
        state.last_activity_at = datetime.now(UTC)

        applied_now = False
        voice_client = guild.voice_client
        if voice_client and voice_client.is_connected():
            source = getattr(voice_client, "source", None)
            if source and hasattr(source, "volume"):
                try:
                    source.volume = normalized
                    applied_now = True
                except Exception:
                    applied_now = False

        applied_percent = int(round(normalized * 100))
        await self._log(
            "music_volume_changed",
            {
                "guild_id": guild.id,
                "channel_id": state.text_channel_id,
                "user_id": None,
                "command_name": "music_volume",
                "result": "ok",
                "percent": applied_percent,
                "applied_now": applied_now,
            },
        )
        await self.refresh_control_panel(guild, reason="volume_changed")
        return applied_percent, applied_now

    async def _on_track_end(self, guild_id: int, err: Exception | None) -> None:
        guild = self.guild_getter(guild_id)
        state = self._states.get(guild_id)
        if state is None:
            return
        current_track = state.current
        state.current = None
        state.last_activity_at = datetime.now(UTC)
        await self._log(
            "music_track_finished",
            {
                "guild_id": guild_id,
                "channel_id": state.text_channel_id,
                "user_id": current_track.requester_id if current_track else None,
                "command_name": "music_track_finished",
                "result": "error" if err else "ok",
                "title": current_track.title if current_track else None,
            },
        )
        if err:
            await self._log(
                "music_error",
                {
                    "guild_id": guild_id,
                    "channel_id": state.text_channel_id,
                    "user_id": None,
                    "command_name": "music_track_finished",
                    "result": f"after_callback:{type(err).__name__}",
                },
            )
        if guild:
            lock = self._lock(guild.id)
            async with lock:
                await self._start_next_locked(guild)
            await self.refresh_control_panel(guild, reason="track_end")

    async def enqueue_and_maybe_play(
        self,
        *,
        guild: discord.Guild,
        requester_id: int,
        text_channel_id: int,
        query_or_url: str,
    ) -> EnqueueResult:
        track = await self.resolve_track(query_or_url, requester_id)
        lock = self._lock(guild.id)
        async with lock:
            state = self._state(guild.id)
            if len(state.queue) >= self.max_queue_size:
                await self._log(
                    "music_enqueue_blocked",
                    {
                        "guild_id": guild.id,
                        "channel_id": text_channel_id,
                        "user_id": requester_id,
                        "command_name": "music_play",
                        "result": "queue_limit",
                    },
                )
                raise PolicyError(f"큐가 가득 찼습니다. 최대 {self.max_queue_size}곡까지 가능합니다.")

            state.queue.append(track)
            state.text_channel_id = text_channel_id
            state.last_activity_at = datetime.now(UTC)
            queue_after_enqueue = len(state.queue)
            started_now = False

            voice_client = guild.voice_client
            if voice_client and voice_client.is_connected() and not voice_client.is_playing() and not voice_client.is_paused():
                started_now = await self._start_next_locked(guild)
                queue_after_enqueue = len(self._state(guild.id).queue)

            await self.refresh_control_panel(guild, reason="enqueue")

        return EnqueueResult(
            track=track,
            queue_length=queue_after_enqueue,
            started_now=started_now,
        )

    async def pause(self, *, guild: discord.Guild) -> bool:
        voice_client = guild.voice_client
        if not voice_client or not voice_client.is_connected():
            raise MusicError("봇이 음성 채널에 연결되어 있지 않습니다.")
        if not voice_client.is_playing():
            return False
        voice_client.pause()
        state = self._state(guild.id)
        state.last_activity_at = datetime.now(UTC)
        await self.refresh_control_panel(guild, reason="pause")
        return True

    async def resume(self, *, guild: discord.Guild) -> bool:
        voice_client = guild.voice_client
        if not voice_client or not voice_client.is_connected():
            raise MusicError("봇이 음성 채널에 연결되어 있지 않습니다.")
        if not voice_client.is_paused():
            return False
        voice_client.resume()
        state = self._state(guild.id)
        state.last_activity_at = datetime.now(UTC)
        await self.refresh_control_panel(guild, reason="resume")
        return True

    async def skip(self, *, guild: discord.Guild) -> bool:
        voice_client = guild.voice_client
        if not voice_client or not voice_client.is_connected():
            raise MusicError("봇이 음성 채널에 연결되어 있지 않습니다.")
        if not (voice_client.is_playing() or voice_client.is_paused()):
            return False
        voice_client.stop()
        state = self._state(guild.id)
        state.last_activity_at = datetime.now(UTC)
        await self.refresh_control_panel(guild, reason="skip")
        return True

    async def stop(self, *, guild: discord.Guild) -> bool:
        voice_client = guild.voice_client
        if not voice_client or not voice_client.is_connected():
            raise MusicError("봇이 음성 채널에 연결되어 있지 않습니다.")
        lock = self._lock(guild.id)
        async with lock:
            state = self._state(guild.id)
            state.queue.clear()
            state.current = None
            state.last_activity_at = datetime.now(UTC)
            if voice_client.is_playing() or voice_client.is_paused():
                voice_client.stop()
                await self.refresh_control_panel(guild, reason="stop")
                return True
            await self.refresh_control_panel(guild, reason="stop_noop")
            return False

    def now(self, guild_id: int) -> Track | None:
        state = self._states.get(guild_id)
        if not state:
            return None
        return state.current

    def queue_page(self, guild_id: int, page: int, *, page_size: int = 10) -> QueueSnapshot:
        state = self._states.get(guild_id)
        if not state:
            return QueueSnapshot(current=None, items=[], page=1, total_pages=1, total_items=0)
        queue_items = list(state.queue)
        total = len(queue_items)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        start = (page - 1) * page_size
        end = start + page_size
        return QueueSnapshot(
            current=state.current,
            items=queue_items[start:end],
            page=page,
            total_pages=total_pages,
            total_items=total,
        )

    async def housekeeping(self) -> None:
        now = datetime.now(UTC)
        idle_cutoff = now - timedelta(minutes=self.idle_disconnect_minutes)
        guild_ids = list(self._states.keys())
        for guild_id in guild_ids:
            guild = self.guild_getter(guild_id)
            state = self._states.get(guild_id)
            if state is None:
                continue
            if guild is None:
                self._states.pop(guild_id, None)
                continue

            lock = self._lock(guild_id)
            async with lock:
                voice_client = guild.voice_client
                if not voice_client or not voice_client.is_connected():
                    self._states.pop(guild_id, None)
                    continue
                if state.queue and not voice_client.is_playing() and not voice_client.is_paused() and state.current is None:
                    try:
                        await self._start_next_locked(guild)
                    except Exception as exc:
                        await self._log(
                            "music_error",
                            {
                                "guild_id": guild_id,
                                "channel_id": state.text_channel_id,
                                "user_id": None,
                                "command_name": "music_housekeeping",
                                "result": f"start_next_failed:{type(exc).__name__}",
                            },
                        )
                        continue
                if voice_client.is_playing() or voice_client.is_paused():
                    continue
                if state.queue or state.current:
                    continue
                if state.last_activity_at > idle_cutoff:
                    continue

                try:
                    await voice_client.disconnect(force=False)
                except Exception as exc:
                    await self._log(
                        "music_error",
                        {
                            "guild_id": guild_id,
                            "channel_id": state.text_channel_id,
                            "user_id": None,
                            "command_name": "music_housekeeping",
                            "result": f"idle_disconnect_failed:{type(exc).__name__}",
                        },
                    )
                    continue
                self._states.pop(guild_id, None)
                self.clear_control_message(guild_id)
                await self._log(
                    "music_idle_disconnected",
                    {
                        "guild_id": guild_id,
                        "channel_id": state.text_channel_id,
                        "user_id": None,
                        "command_name": "music_housekeeping",
                        "result": "ok",
                    },
                )

    async def shutdown(self) -> None:
        for guild_id in list(self._states.keys()):
            guild = self.guild_getter(guild_id)
            if not guild:
                continue
            try:
                await self.leave(guild=guild, reason="shutdown")
            except Exception:
                continue
