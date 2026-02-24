from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import discord

from bot.services.retry import retry_discord_call
from bot.services.storage import StorageService
from bot.utils import find_category_by_name, find_text_channel_by_name, truncate_text

try:
    from google import genai
    from google.genai import types as genai_types
except Exception:  # pragma: no cover
    genai = None  # type: ignore
    genai_types = None  # type: ignore

if TYPE_CHECKING:
    from bot.app import MangsangBot


_ALLOWED_TYPES = {"link", "idea", "music", "youtube", "photo"}
_URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
_YOUTUBE_PATTERNS = [
    "youtube.com",
    "youtu.be",
    "music.youtube.com",
]
_MUSIC_PATTERNS = [
    "spotify.com",
    "music.youtube.com",
    "soundcloud.com",
    "bugs.co.kr",
    "melon.com",
    "genie.co.kr",
    "vibe.naver.com",
    "apple.com/music",
]
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".heic"}
_SOCIAL_PATTERNS = [
    "instagram.com",
    "x.com",
    "twitter.com",
    "threads.net",
    "facebook.com",
    "tiktok.com",
    "pinterest.",
    "dribbble.com",
    "behance.net",
]
_UXUI_HINTS = {
    "ux",
    "ui",
    "uxui",
    "ux/ui",
    "design",
    "designer",
    "prototype",
    "figma",
    "디자인",
    "인터페이스",
    "프로토타입",
}
_IDEA_HINTS = {
    "아이디어",
    "idea",
    "제안",
    "기획",
    "개선",
    "전략",
    "실험",
    "문제",
    "해결",
    "ux",
    "ui",
    "uxui",
    "design",
    "디자인",
    "인터페이스",
}
_PHOTO_HINTS = {
    "사진",
    "photo",
    "image",
    "pic",
    "screenshot",
    "스크린샷",
    "캡처",
    "짤",
    "밈",
}
_MUSIC_HINTS = {
    "음악",
    "노래",
    "곡",
    "뮤직",
    "music",
    "playlist",
    "bgm",
    "track",
}
_YOUTUBE_HINTS = {
    "유튜브",
    "youtube",
    "영상",
    "video",
}
_EXPLICIT_TYPE_TOKENS: dict[str, str] = {
    "[link]": "link",
    "[idea]": "idea",
    "[music]": "music",
    "[youtube]": "youtube",
    "[photo]": "photo",
    "링크:": "link",
    "아이디어:": "idea",
    "제안:": "idea",
    "음악:": "music",
    "유튜브:": "youtube",
    "사진:": "photo",
}


@dataclass(frozen=True)
class ClassificationResult:
    curation_type: str
    confidence: float
    title: str
    summary: str
    tags: list[str]


@dataclass(frozen=True)
class CurationDiagnostics:
    enabled: bool
    mode: str
    inbox_channel: str
    dm_enabled: bool
    approver_policy: str


@dataclass(frozen=True)
class PublishResult:
    status: str
    submission_id: str
    target_channel_id: int | None
    target_message_id: int | None
    merged_into_submission_id: str | None


class CurationService:
    def __init__(
        self,
        *,
        timezone: str,
        config: dict[str, Any] | None,
        channels_config: dict[str, str],
        storage: StorageService,
        gemini_api_key: str | None,
        gemini_model: str,
        gemini_timeout_seconds: int,
    ) -> None:
        self.timezone = timezone
        self.config = config or {}
        self.channels_config = channels_config
        self.storage = storage
        self.gemini_model = gemini_model
        self.gemini_timeout_seconds = gemini_timeout_seconds
        self._infra_ready_guild_ids: set[int] = set()

        self._client = None
        if gemini_api_key and genai:
            self._client = genai.Client(api_key=gemini_api_key)

    def diagnostics(self) -> CurationDiagnostics:
        cfg = self._current_config()
        return CurationDiagnostics(
            enabled=cfg["enabled"],
            mode=cfg["mode"],
            inbox_channel=cfg["ingest"]["inbox_channel"],
            dm_enabled=cfg["ingest"]["dm_enabled"],
            approver_policy=cfg["approver_policy"],
        )

    def enabled(self) -> bool:
        return self._current_config()["enabled"]

    def _current_config(self) -> dict[str, Any]:
        ingest_raw = self.config.get("ingest", {}) if isinstance(self.config.get("ingest", {}), dict) else {}
        routing_raw = self.config.get("routing", {}) if isinstance(self.config.get("routing", {}), dict) else {}
        mentions_raw = self.config.get("mentions", {}) if isinstance(self.config.get("mentions", {}), dict) else {}

        routing = {
            "link": str(routing_raw.get("link", "🔗-큐레이션-링크")),
            "idea": str(routing_raw.get("idea", "💡-큐레이션-아이디어")),
            "music": str(routing_raw.get("music", "🎵-큐레이션-뮤직")),
            "youtube": str(routing_raw.get("youtube", "📺-큐레이션-유튜브")),
            "photo": str(routing_raw.get("photo", "🖼️-큐레이션-사진")),
        }
        mentions = {
            "link": str(mentions_raw.get("link", "knowledge")),
            "idea": str(mentions_raw.get("idea", "product")),
            "music": str(mentions_raw.get("music", "growth")),
            "youtube": str(mentions_raw.get("youtube", "knowledge")),
            "photo": str(mentions_raw.get("photo", "growth")),
        }
        return {
            "enabled": bool(self.config.get("enabled", False)),
            "mode": str(self.config.get("mode", "approve")).strip().lower() or "approve",
            "ingest": {
                "dm_enabled": bool(ingest_raw.get("dm_enabled", True)),
                "inbox_channel": str(ingest_raw.get("inbox_channel", "📥-큐레이션-인박스")).strip(),
            },
            "routing": routing,
            "mentions": mentions,
            "approver_policy": str(self.config.get("approver_policy", "manage_guild")).strip().lower(),
            "dedupe_days": max(1, int(self.config.get("dedupe_days", 30) or 30)),
            "attachment_reupload": bool(self.config.get("attachment_reupload", True)),
            "fallback_link_only_when_upload_fails": bool(self.config.get("fallback_link_only_when_upload_fails", True)),
            "category_name": str(self.config.get("category_name", "------🗂️-07-큐레이션-----")).strip(),
        }

    def update_config(
        self,
        *,
        mode: str | None = None,
        intake_channel: str | None = None,
    ) -> CurationDiagnostics:
        if mode is not None:
            mode_value = mode.strip().lower()
            if mode_value not in {"approve", "auto"}:
                raise ValueError("mode는 approve 또는 auto만 허용됩니다.")
            self.config["mode"] = mode_value

        if intake_channel is not None:
            ingest = self.config.get("ingest")
            if not isinstance(ingest, dict):
                ingest = {}
                self.config["ingest"] = ingest
            ingest["inbox_channel"] = intake_channel.strip()

        return self.diagnostics()

    def is_dm_ingest_enabled(self) -> bool:
        return self._current_config()["ingest"]["dm_enabled"]

    def intake_channel_name(self) -> str:
        return self._current_config()["ingest"]["inbox_channel"]

    def should_ingest_channel_message(self, message: discord.Message) -> bool:
        cfg = self._current_config()
        if not cfg["enabled"] or message.guild is None:
            return False
        if not isinstance(message.channel, discord.TextChannel):
            return False
        return message.channel.name == cfg["ingest"]["inbox_channel"]

    def is_curation_candidate(self, message: discord.Message) -> bool:
        text = (message.content or "").strip()
        urls = self._extract_urls(text)
        if urls or message.attachments:
            return True
        lower = text.lower()
        return lower.startswith("아이디어") or lower.startswith("idea") or lower.startswith("제안")

    def _extract_urls(self, text: str) -> list[str]:
        if not text:
            return []
        found = _URL_PATTERN.findall(text)
        normalized: list[str] = []
        seen: set[str] = set()
        for item in found:
            cleaned = item.strip().rstrip(".,)")
            if cleaned and cleaned not in seen:
                normalized.append(cleaned)
                seen.add(cleaned)
        return normalized

    @staticmethod
    def _url_hash(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    def _is_youtube_url(self, value: str) -> bool:
        lower = value.lower()
        return any(pattern in lower for pattern in _YOUTUBE_PATTERNS)

    def _is_music_url(self, value: str) -> bool:
        lower = value.lower()
        return any(pattern in lower for pattern in _MUSIC_PATTERNS)

    def _is_image_url(self, value: str) -> bool:
        parsed = urlparse(value)
        path = parsed.path.lower()
        return any(path.endswith(ext) for ext in _IMAGE_EXTENSIONS)

    def _is_social_url(self, value: str) -> bool:
        lower = value.lower()
        return any(pattern in lower for pattern in _SOCIAL_PATTERNS)

    def _attachment_is_image(self, attachment: discord.Attachment) -> bool:
        content_type = str(attachment.content_type or "").lower()
        if content_type.startswith("image/"):
            return True
        return any(str(attachment.filename or "").lower().endswith(ext) for ext in _IMAGE_EXTENSIONS)

    def _has_any_hint(self, text: str, hints: set[str]) -> bool:
        lower = text.lower().strip()
        return any(token in lower for token in hints)

    def _explicit_type_from_text(self, text: str) -> str | None:
        lower = text.lower().strip()
        for token, mapped in _EXPLICIT_TYPE_TOKENS.items():
            if lower.startswith(token):
                return mapped
        return None

    def _rule_classify(self, text: str, urls: list[str], attachments: list[dict[str, Any]]) -> tuple[str, float]:
        has_uxui_hint = self._has_any_hint(text, _UXUI_HINTS)
        has_idea_hint = self._has_any_hint(text, _IDEA_HINTS)
        has_photo_hint = self._has_any_hint(text, _PHOTO_HINTS)
        has_music_hint = self._has_any_hint(text, _MUSIC_HINTS)
        has_youtube_hint = self._has_any_hint(text, _YOUTUBE_HINTS)
        explicit_type = self._explicit_type_from_text(text)

        if explicit_type in _ALLOWED_TYPES:
            return (explicit_type, 0.99)

        if urls:
            if has_uxui_hint or has_idea_hint:
                return ("idea", 0.96)
            # music.youtube.com 또는 유튜브 링크+음악 문맥은 music으로 라우팅.
            if any("music.youtube.com" in url.lower() for url in urls):
                return ("music", 0.97)
            if any(self._is_youtube_url(url) for url in urls):
                if has_music_hint:
                    return ("music", 0.94)
                return ("youtube", 0.95)
            if any(self._is_music_url(url) for url in urls):
                return ("music", 0.9)
            if any(self._is_image_url(url) for url in urls):
                if has_uxui_hint or has_idea_hint:
                    return ("idea", 0.9)
                if has_photo_hint:
                    return ("photo", 0.96)
                return ("photo", 0.85)
            if any(self._is_social_url(url) for url in urls):
                if has_photo_hint:
                    return ("photo", 0.82)
                return ("link", 0.93)
            if has_youtube_hint:
                return ("youtube", 0.8)
            if has_music_hint:
                return ("music", 0.8)
            # 일반 웹 링크는 link 기본값.
            return ("link", 0.92)

        if attachments:
            image_count = len([x for x in attachments if bool(x.get("is_image"))])
            if image_count >= max(1, len(attachments) // 2):
                if has_uxui_hint or has_idea_hint:
                    return ("idea", 0.86)
                return ("photo", 0.85)

        if has_music_hint:
            return ("music", 0.72)
        if has_youtube_hint:
            return ("youtube", 0.72)
        return ("idea", 0.7)

    def _simple_tags(self, text: str, curation_type: str, urls: list[str]) -> list[str]:
        tags = {"#curation", f"#{curation_type}"}
        lower = text.lower()
        if "ai" in lower or "인공지능" in lower:
            tags.add("#ai")
        if "agent" in lower or "에이전트" in lower:
            tags.add("#agent")
        if any(token in lower for token in _UXUI_HINTS):
            tags.add("#uxui")
            tags.add("#design")
        if "스타트업" in lower:
            tags.add("#startup")
        if "지원" in lower or "정책" in lower:
            tags.add("#policy")
        if "해커톤" in lower or "공모전" in lower:
            tags.add("#hackathon")
        for url in urls[:2]:
            host = urlparse(url).netloc.lower().replace("www.", "")
            if host:
                tags.add(f"#{host.split('.')[0][:20]}")
        return sorted(tags)

    def _build_title(self, curation_type: str, text: str, urls: list[str], attachments: list[dict[str, Any]]) -> str:
        type_upper = curation_type.upper()
        base = text.strip()
        if not base and urls:
            base = urls[0]
        if not base and attachments:
            base = str(attachments[0].get("filename") or "첨부 파일")
        if not base:
            base = "새 제보"
        base = base.replace("\n", " ").strip()
        return f"[{type_upper}] {truncate_text(base, 72, suffix='') }".strip()

    def _build_summary(self, text: str, urls: list[str], attachments: list[dict[str, Any]]) -> str:
        chunks: list[str] = []
        if text:
            chunks.append(truncate_text(text.replace("\n", " "), 280, suffix=" ..."))
        if urls:
            chunks.append(f"링크 {len(urls)}건")
        if attachments:
            chunks.append(f"첨부 {len(attachments)}건")
        return " / ".join(chunks) if chunks else "내용 요약 없음"

    def _ai_enrich(
        self,
        *,
        text: str,
        urls: list[str],
        attachments: list[dict[str, Any]],
        fallback_type: str,
    ) -> ClassificationResult | None:
        if not self._client:
            return None
        prompt = {
            "instruction": "다음 제보를 link/idea/music/youtube/photo 중 하나로 분류하고 JSON으로 반환하세요.",
            "schema": {
                "type": "one of [link, idea, music, youtube, photo]",
                "title": "[TYPE] 핵심제목",
                "summary": "1-2문장",
                "tags": ["#tag1", "#tag2"],
            },
            "fallback_type": fallback_type,
            "text": text,
            "urls": urls,
            "attachments": attachments,
        }
        try:
            response = self._client.models.generate_content(
                model=self.gemini_model,
                contents=json.dumps(prompt, ensure_ascii=False),
                config=genai_types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=400,
                    response_mime_type="application/json",
                ),
            )
            output = str(getattr(response, "text", "") or "")
            parsed = json.loads(output)
            curation_type = str(parsed.get("type", fallback_type)).strip().lower()
            if curation_type not in _ALLOWED_TYPES:
                curation_type = fallback_type
            title = str(parsed.get("title") or "").strip()
            summary = str(parsed.get("summary") or "").strip()
            tags_raw = parsed.get("tags") if isinstance(parsed.get("tags"), list) else []
            tags = [str(x).strip() for x in tags_raw if str(x).strip().startswith("#")][:8]
            if not title:
                title = self._build_title(curation_type, text, urls, attachments)
            if not summary:
                summary = self._build_summary(text, urls, attachments)
            if not tags:
                tags = self._simple_tags(text, curation_type, urls)
            return ClassificationResult(
                curation_type=curation_type,
                confidence=0.8,
                title=title,
                summary=summary,
                tags=tags,
            )
        except Exception:
            return None

    def classify_message(self, message: discord.Message) -> ClassificationResult:
        text = (message.content or "").strip()
        urls = self._extract_urls(text)
        attachments = self._collect_attachment_meta(message)

        curation_type, confidence = self._rule_classify(text, urls, attachments)
        ai_result: ClassificationResult | None = None
        if confidence < 0.8:
            ai_result = self._ai_enrich(
                text=text,
                urls=urls,
                attachments=attachments,
                fallback_type=curation_type,
            )

        has_hard_photo_signal = bool(
            any(self._is_image_url(url) for url in urls)
            or any(bool(x.get("is_image")) for x in attachments)
            or self._has_any_hint(text, _PHOTO_HINTS)
        )
        if ai_result:
            # AI가 과하게 photo로 분류하는 오탐을 방지한다.
            if ai_result.curation_type == "photo" and not has_hard_photo_signal:
                ai_result = None

        if ai_result:
            return ai_result

        return ClassificationResult(
            curation_type=curation_type,
            confidence=confidence,
            title=self._build_title(curation_type, text, urls, attachments),
            summary=self._build_summary(text, urls, attachments),
            tags=self._simple_tags(text, curation_type, urls),
        )

    def _collect_attachment_meta(self, message: discord.Message) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for attachment in message.attachments:
            items.append(
                {
                    "id": attachment.id,
                    "filename": attachment.filename,
                    "url": attachment.url,
                    "proxy_url": attachment.proxy_url,
                    "size": attachment.size,
                    "content_type": attachment.content_type,
                    "is_image": self._attachment_is_image(attachment),
                }
            )
        return items

    def _resolve_target_guild(self, bot: "MangsangBot", target_guild_id: int | None) -> discord.Guild | None:
        guild_id = target_guild_id or bot.settings.target_guild_id
        if not guild_id:
            return None
        return bot.get_guild(int(guild_id))

    def _routing_channel_name(self, curation_type: str) -> str:
        cfg = self._current_config()
        return str(cfg["routing"].get(curation_type, cfg["routing"]["idea"]))

    def _mention_role_name(self, curation_type: str) -> str:
        cfg = self._current_config()
        return str(cfg["mentions"].get(curation_type, "")).strip()

    @staticmethod
    def _find_role_by_name(guild: discord.Guild, name: str) -> discord.Role | None:
        lowered = name.strip().lower()
        if not lowered:
            return None
        for role in guild.roles:
            if role.name.lower() == lowered:
                return role
        return None

    async def ensure_infrastructure(self, guild: discord.Guild) -> None:
        if guild.id in self._infra_ready_guild_ids:
            return

        cfg = self._current_config()
        category_name = cfg["category_name"]
        category = find_category_by_name(guild, category_name)
        if not category:
            category = await retry_discord_call(
                lambda: guild.create_category(name=category_name, reason="curation infra auto-create")
            )

        intake_name = cfg["ingest"]["inbox_channel"]
        needed_channels = [intake_name, *cfg["routing"].values()]
        for channel_name in needed_channels:
            channel = find_text_channel_by_name(guild, channel_name)
            if channel:
                continue
            await retry_discord_call(
                lambda channel_name=channel_name: guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    reason="curation channel auto-create",
                )
            )

        for role_name in {x for x in cfg["mentions"].values() if x.strip()}:
            if self._find_role_by_name(guild, role_name):
                continue
            await retry_discord_call(
                lambda role_name=role_name: guild.create_role(
                    name=role_name,
                    mentionable=True,
                    reason="curation mention role auto-create",
                )
            )

        self._infra_ready_guild_ids.add(guild.id)

    def _build_submission_payload(
        self,
        *,
        guild_id: int,
        message: discord.Message,
        source: str,
        classification: ClassificationResult,
    ) -> dict[str, Any]:
        urls = self._extract_urls((message.content or "").strip())
        attachments = self._collect_attachment_meta(message)
        now_iso = self._now_iso()

        submission_id = str(uuid.uuid4())
        payload = {
            "submission_id": submission_id,
            "source": source,
            "source_guild_id": guild_id,
            "source_channel_id": message.channel.id,
            "source_message_id": message.id,
            "source_message_link": getattr(message, "jump_url", ""),
            "author_id": message.author.id,
            "author_name": message.author.display_name,
            "raw_text": (message.content or "").strip(),
            "urls": urls,
            "url_hashes": [self._url_hash(url) for url in urls],
            "attachments": attachments,
            "classified_type": classification.curation_type,
            "classification_confidence": classification.confidence,
            "tags": classification.tags,
            "normalized_title": classification.title,
            "normalized_summary": classification.summary,
            "status": "pending",
            "duplicate_of": None,
            "created_at": now_iso,
            "reviewed_at": None,
            "reviewer_id": None,
            "review_message_id": None,
        }
        return payload

    def _latest_submissions(self) -> dict[str, dict[str, Any]]:
        return self.storage.latest_by_key("curation_submissions", "submission_id")

    def _latest_posts_by_submission(self) -> dict[str, dict[str, Any]]:
        return self.storage.latest_by_key("curation_posts", "submission_id")

    def get_submission(self, submission_id: str) -> dict[str, Any] | None:
        return self._latest_submissions().get(submission_id)

    async def ingest_message(
        self,
        *,
        bot: "MangsangBot",
        message: discord.Message,
        source: str,
        target_guild_id: int | None = None,
    ) -> str | None:
        if not self.enabled():
            return None

        guild = self._resolve_target_guild(bot, target_guild_id)
        if guild is None:
            return None

        await self.ensure_infrastructure(guild)

        classification = self.classify_message(message)
        payload = self._build_submission_payload(
            guild_id=guild.id,
            message=message,
            source=source,
            classification=classification,
        )
        submission_id = str(payload["submission_id"])
        await self.storage.append_curation_submission(payload)

        cfg = self._current_config()
        inbox_channel = find_text_channel_by_name(guild, cfg["ingest"]["inbox_channel"])
        if not inbox_channel:
            await self.storage.append_ops_event(
                "curation_publish_failed",
                {
                    "guild_id": guild.id,
                    "channel_id": None,
                    "user_id": message.author.id,
                    "command_name": "curation_ingest",
                    "submission_id": submission_id,
                    "reason": "inbox_channel_missing",
                },
            )
            return submission_id

        from bot.views.curation_review_view import CurationReviewView

        review_embed = self.build_review_embed(payload, guild)
        review_msg = await retry_discord_call(
            lambda: inbox_channel.send(
                embed=review_embed,
                view=CurationReviewView(bot=bot, submission_id=submission_id),
            )
        )

        update_payload = dict(payload)
        update_payload["review_message_id"] = review_msg.id
        await self.storage.append_curation_submission(update_payload)

        await self.storage.append_ops_event(
            "curation_ingested",
            {
                "guild_id": guild.id,
                "channel_id": inbox_channel.id,
                "user_id": message.author.id,
                "command_name": "curation_ingest",
                "submission_id": submission_id,
                "source": source,
                "classified_type": classification.curation_type,
                "mode": cfg["mode"],
            },
            idempotency_key=f"curation_ingested:{submission_id}",
        )
        await self.storage.append_ops_event(
            "curation_classified",
            {
                "guild_id": guild.id,
                "channel_id": inbox_channel.id,
                "user_id": message.author.id,
                "command_name": "curation_ingest",
                "submission_id": submission_id,
                "classified_type": classification.curation_type,
                "confidence": classification.confidence,
                "tags": classification.tags,
            },
            idempotency_key=f"curation_classified:{submission_id}",
        )

        if cfg["mode"] == "auto":
            await self.publish_submission(
                bot=bot,
                guild=guild,
                submission_id=submission_id,
                reviewer_id=message.author.id,
            )

        return submission_id

    def build_review_embed(self, submission: dict[str, Any], guild: discord.Guild | None = None) -> discord.Embed:
        curation_type = str(submission.get("classified_type", "idea"))
        title = str(submission.get("normalized_title") or f"[{curation_type.upper()}] 새 제보")
        summary = str(submission.get("normalized_summary") or "")
        tags = submission.get("tags") if isinstance(submission.get("tags"), list) else []
        urls = submission.get("urls") if isinstance(submission.get("urls"), list) else []
        attachments = submission.get("attachments") if isinstance(submission.get("attachments"), list) else []
        source_message_link = str(submission.get("source_message_link", "")).strip()

        embed = discord.Embed(
            title="🗂️ 큐레이션 승인 대기",
            description=truncate_text(title, 256),
            color=discord.Colour.orange(),
        )
        embed.add_field(name="분류", value=curation_type, inline=True)
        embed.add_field(name="상태", value=str(submission.get("status", "pending")), inline=True)
        embed.add_field(name="작성자", value=f"<@{submission.get('author_id')}>", inline=True)
        if summary:
            embed.add_field(name="요약", value=truncate_text(summary, 1024), inline=False)
        if tags:
            embed.add_field(name="태그", value=" ".join(str(x) for x in tags[:12]), inline=False)
        if urls:
            preview = "\n".join(f"- {u}" for u in urls[:6])
            embed.add_field(name="링크", value=truncate_text(preview, 1024), inline=False)
        if attachments:
            preview = "\n".join(f"- {a.get('filename')}" for a in attachments[:6])
            embed.add_field(name="첨부", value=truncate_text(preview, 1024), inline=False)
        if source_message_link:
            embed.add_field(name="원문", value=source_message_link, inline=False)

        target_name = self._routing_channel_name(curation_type)
        embed.add_field(name="예상 게시 채널", value=target_name, inline=True)
        mention_role_name = self._mention_role_name(curation_type)
        mention_display = mention_role_name
        if guild and mention_role_name:
            role = self._find_role_by_name(guild, mention_role_name)
            if role:
                mention_display = role.mention
        embed.add_field(name="멘션", value=mention_display or "없음", inline=True)

        embed.set_footer(text=f"submission_id={submission.get('submission_id')}")
        return embed

    def _is_approver(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        perms = getattr(member, "guild_permissions", None)
        if not perms:
            return False
        return bool(getattr(perms, "manage_guild", False) or getattr(perms, "administrator", False))

    async def reject_submission(
        self,
        *,
        guild: discord.Guild,
        submission_id: str,
        reviewer_id: int,
        reason: str,
    ) -> bool:
        submission = self.get_submission(submission_id)
        if not submission:
            return False

        updated = dict(submission)
        updated["status"] = "rejected"
        updated["reviewer_id"] = reviewer_id
        updated["reviewed_at"] = self._now_iso()
        updated["reject_reason"] = reason
        await self.storage.append_curation_submission(updated)
        await self.storage.append_ops_event(
            "curation_rejected",
            {
                "guild_id": guild.id,
                "channel_id": updated.get("source_channel_id"),
                "user_id": reviewer_id,
                "command_name": "curation_reject",
                "submission_id": submission_id,
                "reason": reason,
            },
            idempotency_key=f"curation_rejected:{submission_id}:{reviewer_id}:{reason}",
        )
        return True

    def _candidate_duplicates(self, submission: dict[str, Any]) -> list[dict[str, Any]]:
        dedupe_days = int(self._current_config()["dedupe_days"])
        now = datetime.now(UTC)
        hashes = set(str(x) for x in (submission.get("url_hashes") or []) if str(x))
        if not hashes:
            return []

        rows = self._latest_submissions().values()
        result: list[dict[str, Any]] = []
        for row in rows:
            if row.get("submission_id") == submission.get("submission_id"):
                continue
            if str(row.get("status", "")).lower() not in {"approved", "merged"}:
                continue
            created = row.get("created_at")
            try:
                created_dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            except Exception:
                continue
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=UTC)
            if created_dt < now - timedelta(days=dedupe_days):
                continue

            row_hashes = set(str(x) for x in (row.get("url_hashes") or []) if str(x))
            if hashes.intersection(row_hashes):
                result.append(row)
        return result

    async def _merge_into_existing(
        self,
        *,
        guild: discord.Guild,
        submission: dict[str, Any],
        duplicate_target: dict[str, Any],
        reviewer_id: int,
    ) -> PublishResult:
        posts = self._latest_posts_by_submission()
        target_post = posts.get(str(duplicate_target.get("submission_id")))
        channel_id = int(target_post.get("target_channel_id", 0)) if target_post else 0
        message_id = int(target_post.get("target_message_id", 0)) if target_post else 0
        thread_id = int(target_post.get("thread_id", 0)) if target_post else 0

        target_channel = guild.get_channel(channel_id) if channel_id else None
        if isinstance(target_channel, discord.TextChannel) and message_id:
            text = "\n".join(
                [
                    "🔁 기존 항목과 중복 제보가 추가되었습니다.",
                    f"제보자: <@{submission.get('author_id')}>",
                    f"submission_id: `{submission.get('submission_id')}`",
                    f"원문: {submission.get('source_message_link') or '-'}",
                ]
            )

            thread: discord.Thread | None = None
            if thread_id:
                fetched = guild.get_thread(thread_id)
                if isinstance(fetched, discord.Thread):
                    thread = fetched

            if thread is None:
                try:
                    origin_message = await retry_discord_call(lambda: target_channel.fetch_message(message_id))
                    thread = await retry_discord_call(
                        lambda: origin_message.create_thread(
                            name=f"dup-{str(duplicate_target.get('submission_id'))[:8]}",
                            auto_archive_duration=1440,
                        )
                    )
                    thread_id = thread.id
                except Exception:
                    thread = None

            if thread:
                await retry_discord_call(lambda: thread.send(text))
            else:
                await retry_discord_call(lambda: target_channel.send(text))

        updated = dict(submission)
        updated["status"] = "merged"
        updated["duplicate_of"] = duplicate_target.get("submission_id")
        updated["reviewer_id"] = reviewer_id
        updated["reviewed_at"] = self._now_iso()
        await self.storage.append_curation_submission(updated)
        await self.storage.append_ops_event(
            "curation_merged_duplicate",
            {
                "guild_id": guild.id,
                "channel_id": channel_id or submission.get("source_channel_id"),
                "user_id": reviewer_id,
                "command_name": "curation_publish",
                "submission_id": submission.get("submission_id"),
                "duplicate_of": duplicate_target.get("submission_id"),
                "target_message_id": message_id,
                "thread_id": thread_id or None,
            },
            idempotency_key=f"curation_merged:{submission.get('submission_id')}:{duplicate_target.get('submission_id')}",
        )

        return PublishResult(
            status="merged",
            submission_id=str(submission.get("submission_id")),
            target_channel_id=channel_id or None,
            target_message_id=message_id or None,
            merged_into_submission_id=str(duplicate_target.get("submission_id")),
        )

    async def publish_submission(
        self,
        *,
        bot: "MangsangBot",
        guild: discord.Guild,
        submission_id: str,
        reviewer_id: int,
        override_channel_name: str | None = None,
        override_tags: list[str] | None = None,
        source_message: discord.Message | None = None,
    ) -> PublishResult:
        submission = self.get_submission(submission_id)
        if not submission:
            return PublishResult("missing", submission_id, None, None, None)

        if str(submission.get("status", "pending")).lower() not in {"pending"}:
            return PublishResult("already_handled", submission_id, None, None, None)

        duplicates = self._candidate_duplicates(submission)
        if duplicates:
            return await self._merge_into_existing(
                guild=guild,
                submission=submission,
                duplicate_target=duplicates[0],
                reviewer_id=reviewer_id,
            )

        curation_type = str(submission.get("classified_type", "idea")).lower()
        if curation_type not in _ALLOWED_TYPES:
            curation_type = "idea"

        target_name = (override_channel_name or self._routing_channel_name(curation_type)).strip()
        target_channel = find_text_channel_by_name(guild, target_name)
        if not target_channel:
            await self.storage.append_ops_event(
                "curation_publish_failed",
                {
                    "guild_id": guild.id,
                    "channel_id": None,
                    "user_id": reviewer_id,
                    "command_name": "curation_publish",
                    "submission_id": submission_id,
                    "reason": f"target_channel_missing:{target_name}",
                },
            )
            return PublishResult("target_channel_missing", submission_id, None, None, None)

        mention_role_name = self._mention_role_name(curation_type)
        mention_role = self._find_role_by_name(guild, mention_role_name)
        mention_text = mention_role.mention if mention_role else ""

        tags = override_tags if override_tags is not None else list(submission.get("tags") or [])
        tags_text = " ".join(str(x) for x in tags[:12]) if tags else "#curation"
        urls = [str(x) for x in (submission.get("urls") or []) if str(x)]
        links_text = "\n".join(f"- {u}" for u in urls[:10]) if urls else "- 없음"

        lines = [
            str(submission.get("normalized_title") or "[IDEA] 새 제보"),
            str(submission.get("normalized_summary") or ""),
            "",
            "링크",
            links_text,
            "",
            f"태그: {tags_text}",
            f"작성자: <@{submission.get('author_id')}>",
            f"원문: {submission.get('source_message_link') or '-'}",
        ]
        if mention_text:
            lines.append(f"멘션: {mention_text}")
        content = "\n".join(line for line in lines if line is not None)

        files: list[discord.File] = []
        attachment_urls: list[str] = [str(x.get("url")) for x in (submission.get("attachments") or []) if x.get("url")]
        if source_message and self._current_config()["attachment_reupload"]:
            for attachment in source_message.attachments[:8]:
                try:
                    files.append(await attachment.to_file())
                except Exception:
                    continue

        if not files and attachment_urls and self._current_config()["fallback_link_only_when_upload_fails"]:
            content += "\n\n첨부 링크\n" + "\n".join(f"- {u}" for u in attachment_urls[:8])

        allowed_mentions = discord.AllowedMentions(users=True, roles=True, everyone=False)
        posted_message = await retry_discord_call(
            lambda: target_channel.send(
                content=truncate_text(content, 1900, suffix=" ..."),
                files=files if files else None,
                allowed_mentions=allowed_mentions,
            )
        )

        thread_id: int | None = None
        try:
            thread = await retry_discord_call(
                lambda: posted_message.create_thread(
                    name=f"discussion-{submission_id[:8]}",
                    auto_archive_duration=1440,
                )
            )
            thread_id = thread.id
        except Exception:
            thread_id = None

        post_payload = {
            "post_id": str(uuid.uuid4()),
            "submission_id": submission_id,
            "target_channel_id": target_channel.id,
            "target_message_id": posted_message.id,
            "thread_id": thread_id,
            "mention_role_id": mention_role.id if mention_role else None,
            "published_at": self._now_iso(),
        }
        await self.storage.append_curation_post(post_payload)

        updated = dict(submission)
        updated["status"] = "approved"
        updated["reviewer_id"] = reviewer_id
        updated["reviewed_at"] = self._now_iso()
        if override_channel_name:
            updated["override_channel"] = override_channel_name
        if override_tags is not None:
            updated["tags"] = override_tags
        await self.storage.append_curation_submission(updated)

        await self.storage.append_ops_event(
            "curation_approved",
            {
                "guild_id": guild.id,
                "channel_id": target_channel.id,
                "user_id": reviewer_id,
                "command_name": "curation_publish",
                "submission_id": submission_id,
                "target_message_id": posted_message.id,
                "thread_id": thread_id,
                "curation_type": curation_type,
            },
            idempotency_key=f"curation_approved:{submission_id}",
        )

        return PublishResult(
            status="approved",
            submission_id=submission_id,
            target_channel_id=target_channel.id,
            target_message_id=posted_message.id,
            merged_into_submission_id=None,
        )

    async def update_submission_overrides(
        self,
        *,
        submission_id: str,
        reviewer_id: int,
        channel_name: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any] | None:
        submission = self.get_submission(submission_id)
        if not submission:
            return None
        updated = dict(submission)
        if channel_name is not None:
            updated["override_channel"] = channel_name.strip()
        if tags is not None:
            updated["tags"] = tags
        updated["reviewer_id"] = reviewer_id
        updated["reviewed_at"] = self._now_iso()
        await self.storage.append_curation_submission(updated)
        return updated

    def counts(self) -> dict[str, int]:
        latest = self._latest_submissions().values()
        out = {"pending": 0, "approved": 0, "rejected": 0, "merged": 0, "total": 0}
        for row in latest:
            out["total"] += 1
            status = str(row.get("status", "pending")).lower()
            if status in out:
                out[status] += 1
        return out

    def recent_submissions(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = list(self._latest_submissions().values())

        def _key(row: dict[str, Any]) -> tuple[float, str]:
            raw = row.get("created_at")
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return (dt.timestamp(), str(raw))
            except Exception:
                return (0.0, str(raw or ""))

        rows.sort(key=_key, reverse=True)
        return rows[:limit]

    def can_manage(self, interaction: discord.Interaction) -> bool:
        return self._is_approver(interaction)
