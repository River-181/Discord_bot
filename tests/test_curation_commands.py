from __future__ import annotations

from bot.commands import curation


class _DummyTree:
    def __init__(self) -> None:
        self.names: list[str] = []

    def add_command(self, command, guild=None) -> None:  # noqa: ANN001, ARG002
        self.names.append(command.name)


class _DummyService:
    def diagnostics(self):
        class _Diag:
            enabled = True
            mode = "approve"
            inbox_channel = "📥-큐레이션-인박스"
            dm_enabled = True
            approver_policy = "manage_guild"

        return _Diag()

    def counts(self):
        return {"pending": 0, "approved": 0, "rejected": 0, "merged": 0, "total": 0}


class _DummyBot:
    def __init__(self) -> None:
        self.tree = _DummyTree()
        self.command_guild = None
        self.curation_service = _DummyService()
        self.storage = None


def test_register_curation_commands() -> None:
    bot = _DummyBot()
    curation.register(bot)
    assert bot.tree.names == [
        "curation_status",
        "curation_config",
        "curation_publish",
        "curation_reject",
    ]
