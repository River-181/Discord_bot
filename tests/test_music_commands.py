from __future__ import annotations

from types import SimpleNamespace

from bot.commands import music


class _DummyTree:
    def __init__(self) -> None:
        self.names: list[str] = []
        self.commands: list[object] = []

    def add_command(self, command, guild=None) -> None:  # noqa: ANN001, ARG002
        self.names.append(command.name)
        self.commands.append(command)


class _DummyBot:
    def __init__(self) -> None:
        self.tree = _DummyTree()
        self.command_guild = None
        self.music_service = SimpleNamespace(enabled=True, voice_dependency_ok=lambda: True)
        self.storage = SimpleNamespace(append_ops_event=lambda *args, **kwargs: True)


def test_register_music_commands_count() -> None:
    bot = _DummyBot()
    music.register(bot)
    assert bot.tree.names == ["music"]
    group = bot.tree.commands[0]
    subcommands = {cmd.name for cmd in group.commands}
    assert subcommands == {
        "diagnose",
        "join",
        "play",
        "pause",
        "resume",
        "skip",
        "queue",
        "volume",
        "panel",
        "now",
        "stop",
        "leave",
    }


def test_same_voice_channel_rule() -> None:
    channel_a = SimpleNamespace(id=10)
    channel_b = SimpleNamespace(id=20)
    assert music._is_same_voice_channel(channel_a, channel_a) is True
    assert music._is_same_voice_channel(channel_a, channel_b) is False
    assert music._is_same_voice_channel(channel_a, None) is False


def test_extract_member_voice_channel() -> None:
    voice_channel = SimpleNamespace(id=99)
    interaction = SimpleNamespace(
        user=SimpleNamespace(voice=SimpleNamespace(channel=voice_channel)),
    )
    extracted = music._get_member_voice_channel(interaction)
    assert extracted is voice_channel
