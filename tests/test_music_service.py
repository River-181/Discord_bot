from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from bot.services.music import MusicError, MusicService, PolicyError, Track
from bot.services.storage import DataFiles, StorageService


def _make_storage(tmp_path) -> StorageService:
    files = DataFiles(
        decisions="decisions.jsonl",
        warrooms="warrooms.jsonl",
        summaries="summaries.jsonl",
        ops_events="ops_events.ndjson",
        news_items="news_items.jsonl",
        news_digests="news_digests.jsonl",
        snapshots_dir="snapshots",
    )
    return StorageService(base_dir=tmp_path, files=files)


def _make_service(tmp_path, *, config: dict[str, Any] | None = None) -> MusicService:
    guild_store: dict[int, Any] = {}
    loop = asyncio.new_event_loop()
    service = MusicService(
        timezone="Asia/Seoul",
        config=config or {"enabled": True, "allowlist_user_ids": [1]},
        storage=_make_storage(tmp_path),
        loop_getter=lambda: loop,
        guild_getter=lambda gid: guild_store.get(gid),
    )
    # avoid depending on external libs for unit tests.
    service._nacl_available = True  # type: ignore[attr-defined]
    return service


class _FakeVoiceClient:
    def __init__(self) -> None:
        self.channel = SimpleNamespace(id=100)
        self._connected = True
        self._playing = False
        self._paused = False
        self.last_after = None
        self.source = None

    def is_connected(self) -> bool:
        return self._connected

    def is_playing(self) -> bool:
        return self._playing

    def is_paused(self) -> bool:
        return self._paused

    def play(self, source, after) -> None:  # noqa: ANN001
        self._playing = True
        self._paused = False
        self.last_after = after

    def pause(self) -> None:
        self._playing = False
        self._paused = True

    def resume(self) -> None:
        self._playing = True
        self._paused = False

    def stop(self) -> None:
        self._playing = False
        self._paused = False
        if self.last_after:
            cb = self.last_after
            self.last_after = None
            cb(None)

    async def disconnect(self, force: bool = False) -> None:  # noqa: ARG002
        self._connected = False


class _FakeGuild:
    def __init__(self, guild_id: int = 77) -> None:
        self.id = guild_id
        self.voice_client = _FakeVoiceClient()


def test_source_policy_blocks_youtube_for_non_allowlist(tmp_path) -> None:
    service = _make_service(tmp_path, config={"enabled": True, "allowlist_user_ids": [1]})
    with asyncio.Runner() as runner:
        try:
            runner.run(service.resolve_track("https://www.youtube.com/watch?v=abc", requester_id=2))
        except PolicyError:
            pass
        else:
            raise AssertionError("non-allowlist youtube should be blocked")


def test_source_policy_allows_direct_url(tmp_path) -> None:
    service = _make_service(tmp_path, config={"enabled": True, "allowlist_user_ids": []})
    with asyncio.Runner() as runner:
        track = runner.run(service.resolve_track("https://example.com/audio.mp3", requester_id=9))
    assert track.source_type == "direct"
    assert track.stream_url.startswith("https://example.com/")


def test_source_policy_allowlist_search_without_ytdlp(tmp_path) -> None:
    service = _make_service(tmp_path, config={"enabled": True, "allowlist_user_ids": [1]})
    service._ytdlp_available = False  # type: ignore[attr-defined]
    with asyncio.Runner() as runner:
        try:
            runner.run(service.resolve_track("lofi hiphop", requester_id=1))
        except MusicError:
            pass
        else:
            raise AssertionError("allowlist search without yt-dlp should raise MusicError")


def test_queue_page_and_now(tmp_path) -> None:
    service = _make_service(tmp_path)
    state = service._state(10)  # type: ignore[attr-defined]
    state.current = Track("A", "u1", "w1", None, 1, "direct")
    state.queue.append(Track("B", "u2", "w2", None, 1, "direct"))
    state.queue.append(Track("C", "u3", "w3", None, 1, "direct"))

    snap = service.queue_page(10, 1, page_size=1)
    assert snap.current is not None
    assert snap.total_items == 2
    assert len(snap.items) == 1
    assert snap.items[0].title == "B"
    assert service.now(10).title == "A"


def test_stop_clears_queue(tmp_path) -> None:
    service = _make_service(tmp_path)
    guild = _FakeGuild()
    state = service._state(guild.id)  # type: ignore[attr-defined]
    state.current = Track("A", "u1", "w1", None, 1, "direct")
    state.queue.append(Track("B", "u2", "w2", None, 1, "direct"))
    guild.voice_client._playing = True  # type: ignore[attr-defined]

    with asyncio.Runner() as runner:
        stopped = runner.run(service.stop(guild=guild))
    assert stopped is True
    assert len(state.queue) == 0
    assert state.current is None


def test_housekeeping_disconnects_idle(tmp_path) -> None:
    guild = _FakeGuild(55)
    guild_map = {55: guild}
    loop = asyncio.new_event_loop()
    service = MusicService(
        timezone="Asia/Seoul",
        config={"enabled": True, "idle_disconnect_minutes": 10},
        storage=_make_storage(tmp_path),
        loop_getter=lambda: loop,
        guild_getter=lambda gid: guild_map.get(gid),
    )
    service._nacl_available = True  # type: ignore[attr-defined]
    state = service._state(55)  # type: ignore[attr-defined]
    state.last_activity_at = datetime.now(UTC) - timedelta(minutes=30)

    with asyncio.Runner() as runner:
        runner.run(service.housekeeping())

    assert guild.voice_client.is_connected() is False


def test_should_announce_now_playing_policy(tmp_path) -> None:
    s1 = _make_service(tmp_path, config={"enabled": True, "notice_policy": "low_noise"})
    s2 = _make_service(tmp_path, config={"enabled": True, "notice_policy": "standard"})
    s3 = _make_service(tmp_path, config={"enabled": True, "notice_policy": "silent"})
    s4 = _make_service(tmp_path, config={"enabled": True, "announce_now_playing": False})
    assert s1._should_announce_now_playing() is True
    assert s2._should_announce_now_playing() is True
    assert s3._should_announce_now_playing() is False
    assert s4._should_announce_now_playing() is False


def test_volume_percent_default_and_set(tmp_path) -> None:
    service = _make_service(tmp_path, config={"enabled": True, "default_volume": 70})
    guild = _FakeGuild(90)
    assert service.volume_percent(guild.id) == 70

    with asyncio.Runner() as runner:
        applied, applied_now = runner.run(service.set_volume(guild=guild, percent=55))

    assert applied == 55
    assert applied_now is False
    assert service.volume_percent(guild.id) == 55


def test_set_volume_applies_to_current_source(tmp_path) -> None:
    service = _make_service(tmp_path, config={"enabled": True, "default_volume": 70})
    guild = _FakeGuild(91)
    guild.voice_client.source = SimpleNamespace(volume=0.7)

    with asyncio.Runner() as runner:
        applied, applied_now = runner.run(service.set_volume(guild=guild, percent=30))

    assert applied == 30
    assert applied_now is True
    assert abs(guild.voice_client.source.volume - 0.3) < 1e-9
