from __future__ import annotations

import asyncio
from collections import deque
from types import SimpleNamespace

from bot.views.music_controls import MusicControlsView


class _FakeVoiceClient:
    def __init__(self, *, connected: bool, playing: bool, paused: bool) -> None:
        self._connected = connected
        self._playing = playing
        self._paused = paused
        self.channel = SimpleNamespace(id=123)

    def is_connected(self) -> bool:
        return self._connected

    def is_playing(self) -> bool:
        return self._playing

    def is_paused(self) -> bool:
        return self._paused


class _FakeGuild:
    def __init__(self, voice_client: _FakeVoiceClient | None) -> None:
        self.voice_client = voice_client


class _FakeMusicService:
    def __init__(self, state: object | None) -> None:
        self._state = state

    def get_state(self, guild_id: int):  # noqa: ANN001
        _ = guild_id
        return self._state


class _FakeBot:
    def __init__(self, guild: _FakeGuild | None, state: object | None) -> None:
        self._guild = guild
        self.music_service = _FakeMusicService(state)

    def get_guild(self, guild_id: int):  # noqa: ANN001
        _ = guild_id
        return self._guild


def _build_view(guild: _FakeGuild | None, state: object | None) -> MusicControlsView:
    async def _make() -> MusicControlsView:
        return MusicControlsView(bot=_FakeBot(guild, state), guild_id=1)

    return asyncio.run(_make())


def test_view_buttons_when_playing() -> None:
    state = SimpleNamespace(
        current=SimpleNamespace(title="now"),
        queue=deque([SimpleNamespace(title="next song")]),
    )
    guild = _FakeGuild(_FakeVoiceClient(connected=True, playing=True, paused=False))
    view = _build_view(guild, state)

    assert view.pause_resume.label == "일시정지"
    assert str(view.pause_resume.emoji) == "⏸️"
    assert view.pause_resume.disabled is False
    assert view.skip.disabled is False
    assert view.leave.disabled is False
    assert view.vol_up.disabled is False


def test_view_buttons_when_paused() -> None:
    state = SimpleNamespace(
        current=SimpleNamespace(title="paused"),
        queue=deque([]),
    )
    guild = _FakeGuild(_FakeVoiceClient(connected=True, playing=False, paused=True))
    view = _build_view(guild, state)

    assert view.pause_resume.label == "재개"
    assert str(view.pause_resume.emoji) == "▶️"
    assert view.pause_resume.disabled is False
    assert view.skip.disabled is False


def test_view_buttons_when_disconnected_and_empty() -> None:
    state = SimpleNamespace(current=None, queue=deque([]))
    guild = _FakeGuild(None)
    view = _build_view(guild, state)

    assert view.pause_resume.disabled is True
    assert view.skip.disabled is True
    assert view.stop.disabled is True
    assert view.leave.disabled is True
    assert view.vol_down.disabled is True
    assert view.vol_up.disabled is True


def test_queue_preview_multiline_and_tail() -> None:
    state = SimpleNamespace(
        current=None,
        queue=deque(
            [
                SimpleNamespace(title="a" * 120),
                SimpleNamespace(title="song-b"),
                SimpleNamespace(title="song-c"),
            ]
        ),
    )
    guild = _FakeGuild(None)
    view = _build_view(guild, state)

    preview = view._queue_preview(1, max_items=2)
    lines = preview.splitlines()
    assert lines[0].startswith("1. ")
    assert lines[1].startswith("2. ")
    assert "... 외 1곡" in preview
