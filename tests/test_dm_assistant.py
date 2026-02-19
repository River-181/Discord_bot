from __future__ import annotations

import asyncio

from bot.services.dm_assistant import DMAssistantService, parse_dm_command


def test_parse_news_hours() -> None:
    c1 = parse_dm_command("뉴스 24")
    assert c1.intent == "news"
    assert c1.is_actionable is True
    assert c1.value == 24

    c2 = parse_dm_command("news 72")
    assert c2.intent == "news"
    assert c2.value == 72


def test_parse_summarize() -> None:
    c = parse_dm_command("요약 오늘은 결정을 세 개 했다")
    assert c.intent == "summarize"
    assert c.is_actionable is False
    assert str(c.value).startswith("오늘은")


def test_parse_unknown_and_nlu_classification() -> None:
    c = parse_dm_command("뉴스 돌려줘")
    assert c.intent == "unknown"

    service = DMAssistantService(
        timezone="Asia/Seoul",
        target_guild_id=1401492009486651452,
        config={"mode": "hybrid"},
    )
    assert service.classify_nlu("뉴스 돌려줘") == "action_guide"
    assert service.classify_nlu("이 비서가 뭘 할 수 있어?") == "qna"
    assert service.classify_nlu("아무말") == "fallback_help"


def test_allowlist_and_cooldown() -> None:
    service = DMAssistantService(
        timezone="Asia/Seoul",
        target_guild_id=1401492009486651452,
        config={
            "allowlist_user_ids": [111, 222],
            "news_run_cooldown_seconds": 600,
        },
    )

    assert service.is_user_allowlisted(111) is True
    assert service.is_user_allowlisted(333) is False

    assert service.news_cooldown_remaining(111) == 0
    service.mark_news_run(111)
    assert service.news_cooldown_remaining(111) > 0


class _DummyChannel:
    def __init__(self) -> None:
        self.id = 999
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)


class _DummyAuthor:
    def __init__(self, user_id: int) -> None:
        self.id = user_id
        self.display_name = "tester"
        self.bot = False


class _DummyMessage:
    def __init__(self, content: str, user_id: int = 333) -> None:
        self.content = content
        self.author = _DummyAuthor(user_id)
        self.channel = _DummyChannel()
        self.id = 12345


class _DummyStorage:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def append_ops_event(self, event_type: str, payload: dict, idempotency_key: str | None = None) -> bool:
        self.events.append((event_type, payload))
        return True

    def read_jsonl(self, kind: str) -> list[dict]:
        return []

    def active_warrooms(self) -> list[dict]:
        return []


class _DummyWarroom:
    def list_warrooms(self, status: str) -> list[dict]:
        return []


class _DummyNews:
    def enabled(self) -> bool:
        return True

    async def run_digest(self, bot, guild_id: int, window_hours: int, kind: str):
        class _Result:
            digest_id = "d-1"
            jump_url = "https://discord.com/channels/x/y/z"
            items_count = 1
            skipped_count = 0
            error_count = 0

        return _Result()


class _DummySummarizer:
    def summarize(self, messages, scope_label: str):
        class _Result:
            summary_text = "요약"
            decisions = []
            actions = []
            risks = []
            model = "rule-fallback"
            fallback_used = True

        return _Result()


class _DummySettings:
    target_guild_id = 1401492009486651452


class _DummyBot:
    def __init__(self) -> None:
        self.storage = _DummyStorage()
        self.warroom_service = _DummyWarroom()
        self.news_service = _DummyNews()
        self.summarizer = _DummySummarizer()
        self.settings = _DummySettings()


def test_handle_dm_blocked_news_logs_metadata_only() -> None:
    service = DMAssistantService(
        timezone="Asia/Seoul",
        target_guild_id=1401492009486651452,
        config={"allowlist_user_ids": [111], "log_message_content": False},
    )
    bot = _DummyBot()
    msg = _DummyMessage("뉴스 24", user_id=333)
    result = asyncio.run(service.handle_dm(bot, msg))

    assert result["result"] == "blocked_not_allowlisted"
    assert any("권한" in line for line in msg.channel.sent)
    assert bot.storage.events
    event_type, payload = bot.storage.events[0]
    assert event_type == "dm_command_blocked"
    assert "content" not in payload


def test_handle_dm_qna_fallback() -> None:
    service = DMAssistantService(
        timezone="Asia/Seoul",
        target_guild_id=1401492009486651452,
        config={"mode": "hybrid"},
    )
    bot = _DummyBot()
    msg = _DummyMessage("이 비서가 뭘 할 수 있어?", user_id=333)
    result = asyncio.run(service.handle_dm(bot, msg))

    assert result["command_name"] == "nlu_fallback"
    assert result["result"] == "qna"
    assert msg.channel.sent
