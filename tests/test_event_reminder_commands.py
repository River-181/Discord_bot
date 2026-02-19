from __future__ import annotations

from types import SimpleNamespace

from bot.commands import event_reminder


class _DummyTree:
    def __init__(self) -> None:
        self.names: list[str] = []
        self.commands: list[object] = []

    def add_command(self, command, guild=None) -> None:  # noqa: ANN001, ARG002
        self.names.append(command.name)
        self.commands.append(command)


class _DummyService:
    def diagnostics(self) -> dict:
        return {
            "enabled": True,
            "reminder_minutes": 5,
            "scan_cron": "*/1 * * * *",
            "reminder_channel": "운영-브리핑",
            "mention_mode": "event_subscribers_plus_here",
            "send_dm": True,
            "max_mentions_per_message": 20,
            "last_scan": {},
        }

    def update_config(self, *, enabled: bool, reminder_minutes: int, send_dm: bool) -> dict:
        return {
            "enabled": enabled,
            "reminder_minutes": reminder_minutes,
            "send_dm": send_dm,
            "reminder_channel": "운영-브리핑",
        }


class _DummyBot:
    def __init__(self) -> None:
        self.tree = _DummyTree()
        self.command_guild = None
        self.event_reminder_service = _DummyService()
        self.storage = SimpleNamespace(append_ops_event=lambda *args, **kwargs: True)


def test_register_event_reminder_commands() -> None:
    bot = _DummyBot()
    event_reminder.register(bot)
    assert bot.tree.names == ["event_reminder_status", "event_reminder_config"]


def test_admin_permission_check() -> None:
    admin_interaction = SimpleNamespace(
        user=SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=True, manage_guild=False)
        )
    )
    manager_interaction = SimpleNamespace(
        user=SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=False, manage_guild=True)
        )
    )
    normal_interaction = SimpleNamespace(
        user=SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=False, manage_guild=False)
        )
    )
    assert event_reminder._is_event_reminder_admin(admin_interaction) is True
    assert event_reminder._is_event_reminder_admin(manager_interaction) is True
    assert event_reminder._is_event_reminder_admin(normal_interaction) is False

