from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import discord

from bot.utils import truncate_text

if TYPE_CHECKING:
    from bot.app import MangsangBot


@dataclass(frozen=True)
class DMCommand:
    intent: str
    raw: str
    is_actionable: bool
    value: str | int | None = None


def parse_dm_command(text: str) -> DMCommand:
    value = (text or "").strip()
    lower = value.lower()
    if lower in {"help", "도움", "도움말", "명령", "메뉴", "?"}:
        return DMCommand(intent="help", raw=value, is_actionable=False)
    if lower in {"상태", "status"}:
        return DMCommand(intent="status", raw=value, is_actionable=False)
    if lower in {"워룸", "warroom"}:
        return DMCommand(intent="warrooms", raw=value, is_actionable=False)
    news_match = re.match(r"^(?:뉴스|news)(?:\s+(\d{1,3}))?$", lower)
    if news_match:
        hours = int(news_match.group(1)) if news_match.group(1) else 12
        hours = max(1, min(hours, 168))
        return DMCommand(intent="news", raw=value, is_actionable=True, value=hours)
    if lower.startswith("요약 "):
        content = value[3:].strip()
        return DMCommand(intent="summarize", raw=value, is_actionable=False, value=content)
    if lower.startswith("summary "):
        content = value[8:].strip()
        return DMCommand(intent="summarize", raw=value, is_actionable=False, value=content)
    return DMCommand(intent="unknown", raw=value, is_actionable=False)


class DMAssistantService:
    def __init__(
        self,
        *,
        timezone: str,
        target_guild_id: int | None,
        config: dict | None = None,
    ) -> None:
        cfg = config or {}
        self.timezone = timezone
        self.target_guild_id = target_guild_id
        self.enabled = bool(cfg.get("enabled", True))
        self.mode = str(cfg.get("mode", "hybrid")).strip().lower() or "hybrid"
        if self.mode not in {"command", "hybrid"}:
            self.mode = "hybrid"
        self.allowlist_user_ids = {int(x) for x in cfg.get("allowlist_user_ids", []) if str(x).isdigit()}
        self.max_summary_chars = int(cfg.get("max_summary_chars", 4000) or 4000)
        self.log_message_content = bool(cfg.get("log_message_content", False))
        self._news_cooldown_seconds = int(cfg.get("news_run_cooldown_seconds", 600) or 600)
        self._last_news_run_by_user: dict[int, float] = {}

    def _help_text(self) -> str:
        return "\n".join(
            [
                "개인 메시지에서 가능한 기능",
                "- `도움말` : 사용 가능한 DM 명령 보기",
                "- `상태` : 봇 요약 상태 확인",
                "- `워룸` : 현재 활성 워룸 목록 보기",
                "- `뉴스` 또는 `뉴스 24` : 뉴스 다이제스트 즉시 실행 (기본 12시간)",
                "- `요약 <텍스트>` : 입력 텍스트를 핵심/결정/액션/리스크로 요약",
            ]
        )

    def is_user_allowlisted(self, user_id: int) -> bool:
        return user_id in self.allowlist_user_ids

    def news_cooldown_remaining(self, user_id: int) -> int:
        last = self._last_news_run_by_user.get(user_id, 0.0)
        now = time.time()
        return int(max(0, self._news_cooldown_seconds - (now - last)))

    def mark_news_run(self, user_id: int) -> None:
        self._last_news_run_by_user[user_id] = time.time()

    def classify_nlu(self, text: str) -> str:
        lower = text.lower().strip()
        action_hints = ["실행", "돌려", "켜", "만들", "생성", "open", "run", "trigger", "뉴스", "워룸"]
        if any(token in lower for token in action_hints):
            return "action_guide"
        qna_hints = ["뭐 할 수", "뭘 할 수", "기능", "사용법", "도움", "어떻게", "why", "what", "how"]
        if any(token in lower for token in qna_hints):
            return "qna"
        return "fallback_help"

    async def handle_dm(self, bot: "MangsangBot", message: discord.Message) -> dict[str, str]:
        if not self.enabled:
            await message.channel.send("DM 비서 기능이 비활성입니다.")
            return {"command_name": "disabled", "result": "disabled"}

        command = parse_dm_command(message.content or "")
        if command.intent == "help":
            await message.channel.send(self._help_text())
            return {"command_name": "help", "result": "ok"}
        if command.intent == "status":
            await self._send_status(bot, message)
            return {"command_name": "status", "result": "ok"}
        if command.intent == "warrooms":
            await self._send_warrooms(bot, message)
            return {"command_name": "warrooms", "result": "ok"}
        if command.intent == "news":
            result = await self._run_news(bot, message, int(command.value or 12))
            return {"command_name": "news", "result": result}
        if command.intent == "summarize":
            await self._summarize_text(bot, message, str(command.value or ""))
            return {"command_name": "summarize", "result": "ok"}

        if self.mode == "command":
            await message.channel.send(self._help_text())
            return {"command_name": "help", "result": "command_mode_fallback"}

        nlu_type = self.classify_nlu(command.raw)
        if nlu_type == "action_guide":
            await message.channel.send(
                "DM에서는 서버 변경 액션을 자연어로 실행하지 않습니다. "
                "`뉴스`, `뉴스 24`, `상태`, `워룸`, `요약 <텍스트>` 같은 명령을 사용해 주세요."
            )
            await bot.storage.append_ops_event(
                "dm_nlu_fallback",
                {
                    "user_id": message.author.id,
                    "channel_id": message.channel.id,
                    "command_name": "nlu_fallback",
                    "result": "action_guide",
                },
            )
            return {"command_name": "nlu_fallback", "result": "action_guide"}

        if nlu_type == "qna":
            await message.channel.send(
                "DM에서 할 수 있는 일: `도움말`, `상태`, `워룸`, `뉴스`, `뉴스 24`, `요약 <텍스트>`.\n"
                "서버 액션은 안전을 위해 명시 명령으로만 처리합니다."
            )
            await bot.storage.append_ops_event(
                "dm_nlu_fallback",
                {
                    "user_id": message.author.id,
                    "channel_id": message.channel.id,
                    "command_name": "nlu_fallback",
                    "result": "qna",
                },
            )
            return {"command_name": "nlu_fallback", "result": "qna"}

        await message.channel.send(self._help_text())
        await bot.storage.append_ops_event(
            "dm_nlu_fallback",
            {
                "user_id": message.author.id,
                "channel_id": message.channel.id,
                "command_name": "nlu_fallback",
                "result": "fallback_help",
            },
        )
        return {"command_name": "nlu_fallback", "result": "fallback_help"}

    async def _send_status(self, bot: "MangsangBot", message: discord.Message) -> None:
        active_rooms = len(bot.storage.active_warrooms())
        decisions = len(bot.storage.read_jsonl("decisions"))
        summaries = len(bot.storage.read_jsonl("summaries"))
        news_digests = len(bot.storage.read_jsonl("news_digests"))
        await message.channel.send(
            "\n".join(
                [
                    "봇 DM 상태",
                    f"- guild_id: {bot.settings.target_guild_id}",
                    f"- active_warrooms: {active_rooms}",
                    f"- decisions: {decisions}",
                    f"- summaries: {summaries}",
                    f"- news_digests: {news_digests}",
                    f"- dm_mode: {self.mode}",
                    f"- dm_allowlist_count: {len(self.allowlist_user_ids)}",
                ]
            )
        )

    async def _send_warrooms(self, bot: "MangsangBot", message: discord.Message) -> None:
        rooms = bot.warroom_service.list_warrooms("active")
        if not rooms:
            await message.channel.send("활성 워룸이 없습니다.")
            return
        lines = ["활성 워룸 목록 (최대 10개)"]
        for room in sorted(rooms, key=lambda x: str(x.get("created_at", "")), reverse=True)[:10]:
            lines.append(
                f"- {room.get('name')} | zone={room.get('zone')} | last={room.get('last_activity_at')}"
            )
        await message.channel.send("\n".join(lines))

    async def _run_news(self, bot: "MangsangBot", message: discord.Message, hours: int) -> str:
        if not bot.news_service or not bot.news_service.enabled():
            await message.channel.send("뉴스 레이다 기능이 비활성입니다.")
            return "news_disabled"
        if not self.target_guild_id:
            await message.channel.send("target_guild_id 설정이 없어 뉴스 실행이 불가능합니다.")
            return "missing_guild_id"

        user_id = message.author.id
        if not self.is_user_allowlisted(user_id):
            await bot.storage.append_ops_event(
                "dm_command_blocked",
                {
                    "user_id": user_id,
                    "channel_id": message.channel.id,
                    "command_name": "news",
                    "result": "blocked_not_allowlisted",
                },
            )
            await message.channel.send("DM 실행 권한이 없습니다. 운영자에게 allowlist 추가를 요청해 주세요.")
            return "blocked_not_allowlisted"

        remain = self.news_cooldown_remaining(user_id)
        if remain > 0:
            await message.channel.send(f"뉴스 실행은 너무 자주 요청할 수 없습니다. {remain}초 후 다시 시도해 주세요.")
            return "blocked_cooldown"
        self.mark_news_run(user_id)

        await message.channel.send(f"뉴스 다이제스트 실행 중입니다... (최근 {hours}시간)")
        result = await bot.news_service.run_digest(
            bot=bot,
            guild_id=int(self.target_guild_id),
            window_hours=hours,
            kind="dm",
        )
        await message.channel.send(
            "\n".join(
                [
                    "DM 요청 뉴스 실행 결과",
                    f"- digest_id: `{result.digest_id}`",
                    f"- jump_url: {result.jump_url or '(post failed)'}",
                    f"- items: `{result.items_count}`",
                    f"- skipped: `{result.skipped_count}`",
                    f"- errors: `{result.error_count}`",
                ]
            )
        )
        return "ok"

    async def _summarize_text(self, bot: "MangsangBot", message: discord.Message, content: str) -> None:
        if not content:
            await message.channel.send("요약할 텍스트를 같이 보내주세요. 예: `요약 오늘 회의에서 ...`")
            return
        content = content[: self.max_summary_chars]
        payload = [
            {
                "author": message.author.display_name,
                "content": content,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "message_id": message.id,
            }
        ]
        result = bot.summarizer.summarize(payload, scope_label="dm")
        body = [
            "DM 텍스트 요약",
            truncate_text(result.summary_text, 1200),
            "",
            "결정",
            "\n".join([f"- {x}" for x in result.decisions[:5]]) if result.decisions else "- 없음",
            "액션",
            "\n".join([f"- {x}" for x in result.actions[:5]]) if result.actions else "- 없음",
            "리스크",
            "\n".join([f"- {x}" for x in result.risks[:5]]) if result.risks else "- 없음",
            "",
            f"model={result.model} fallback={result.fallback_used}",
        ]
        await message.channel.send("\n".join(body))
