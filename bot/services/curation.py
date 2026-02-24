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
_SOCIAL_DOMAINS_TO_LINK = {
    "instagram.com": "instagram",
    "www.instagram.com": "instagram",
    "x.com": "x",
    "twitter.com": "x",
    "threads.net": "threads",
    "facebook.com": "facebook",
    "tiktok.com": "tiktok",
    "pinterest.": "pinterest",
    "dribbble.com": "dribbble",
    "behance.net": "behance",
    "linktr.ee": "linktr",
}
_NOISE_LINE_PATTERNS = [
    re.compile(r"^\s*likes?\b.*", re.IGNORECASE),
    re.compile(r"^\s*댓글\b.*", re.IGNORECASE),
    re.compile(r"^\s*저장\b.*", re.IGNORECASE),
    re.compile(r"^\s*팔로워\b.*", re.IGNORECASE),
    re.compile(r"^\s*공유\b.*", re.IGNORECASE),
    re.compile(r"^\s*조회수?\b.*", re.IGNORECASE),
]
_NOISE_INLINE_PATTERNS = [
    re.compile(r"^\s*\d+\s*개?의?\s*좋아요.*", re.IGNORECASE),
    re.compile(r"^\s*likes\b.*", re.IGNORECASE),
    re.compile(r"^\s*views?\b.*", re.IGNORECASE),
    re.compile(r"^\s*팔로워\s*\d+.*", re.IGNORECASE),
]
_NOISE_SNIPPET_PATTERNS = [
    re.compile(r"\b좋아요\s*\d+\b", re.IGNORECASE),
    re.compile(r"\blikes\s*\d+\b", re.IGNORECASE),
    re.compile(r"\b댓글\b", re.IGNORECASE),
    re.compile(r"\b공유\b", re.IGNORECASE),
    re.compile(r"\b팔로워\b", re.IGNORECASE),
]
_TRACKING_PARAM_PATTERNS = [
    re.compile(r"^utm_[^=]+"),
    re.compile(r"^igsh$", re.IGNORECASE),
]
_URL_SPLIT_PATTERN = re.compile(r"(https?://[^\s<>()]+)")
_SENTENCE_END_PATTERN = re.compile(r"(?<=[.!?])\s+")
_TRACKING_PREFIXES = ("instagram.com", "x.com", "twitter.com", "fb.com", "shorturl.at")
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
_NORMALIZATION_PROFILE = "compact_v2"
_LINK_HINTS = {"링크", "자료", "유용", "참고", "유익", "공유"}


_TYPE_INTRO = {
    "link": "⚡ 한 번 들어볼 만한 링크가 왔어요. 핵심만 깔끔하게 골라보겠습니다.",
    "idea": "🚀 아이디어 제보가 왔어요. 바로 적용 가능한 포인트가 보여요.",
    "music": "🎧 음악 콘텐츠 제보가 왔어요. 기획/운영에서 바로 쓸 수 있는 후보예요.",
    "youtube": "🎬 유튜브 제보가 왔어요. 핵심 내용을 우선 정리해드릴게요.",
    "photo": "🖼️ 비주얼 제보가 왔어요. 톤과 메시지 기준으로 빠르게 검토하면 좋아요.",
}


def _compact_url_for_title(value: str) -> str:
    try:
        parsed = urlparse(value)
        host = (parsed.netloc or "").replace("www.", "")
        if not host:
            return value
        path = parsed.path.strip("/")
        if not path:
            return host
        seg = path.split("/")[0]
        if seg:
            return f"{host}/{seg}"
        return host
    except Exception:
        return value


def _strip_urls_for_title(text: str) -> str:
    return _URL_SPLIT_PATTERN.sub("", text or "").strip()


def _short_url_display(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").replace("www.", "")
        path = (parsed.path or "").strip("/")
        if path:
            return f"{host}/{path}"
        return host or url
    except Exception:
        return url


def _normalize_display_summary(text: str) -> str:
    if not text:
        return ""
    cleaned = _URL_SPLIT_PATTERN.sub("", str(text))
    cleaned = re.sub(r"\s*/\s*링크\s+\d+건\s*$", "", cleaned)
    cleaned = re.sub(r"^링크\s+\d+건\s*[/\s]*", "", cleaned)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        lowered = line.lower()
        if any(pattern.match(lowered) for pattern in _NOISE_LINE_PATTERNS):
            continue
        if any(pattern.match(lowered) for pattern in _NOISE_INLINE_PATTERNS):
            continue
        if lowered in seen:
            continue
        deduped.append(line)
        seen.add(lowered)
    if not deduped:
        return ""
    compact = " ".join(deduped)
    return re.sub(r"\s{2,}", " ", compact).strip()


def _normalize_display_summary_v2(text: str) -> str:
    if not text:
        return ""
    cleaned = _URL_SPLIT_PATTERN.sub("", str(text))
    cleaned = re.sub(r"\s*/\s*링크\s+\d+건\s*$", "", cleaned)
    cleaned = re.sub(r"^\s*링크\s+\d+건\s*[/\s]*", "", cleaned)

    for pattern in _NOISE_SNIPPET_PATTERNS:
        cleaned = pattern.sub("", cleaned)

    lines: list[str] = []
    raw_lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    for line in raw_lines:
        lines.extend([chunk.strip() for chunk in _SENTENCE_END_PATTERN.split(line) if chunk.strip()])

    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        lowered = line.lower()
        if any(pattern.match(lowered) for pattern in _NOISE_LINE_PATTERNS):
            continue
        if any(pattern.match(lowered) for pattern in _NOISE_INLINE_PATTERNS):
            continue
        if lowered in seen:
            continue
        deduped.append(line)
        seen.add(lowered)
    if not deduped:
        return ""
    compact = " ".join(deduped)
    return re.sub(r"\s{2,}", " ", compact).strip()


_normalize_display_summary = _normalize_display_summary_v2


@dataclass(frozen=True)
class ClassificationResult:
    curation_type: str
    confidence: float
    title: str
    summary: str
    tags: list[str]
    reason: str = "rules"


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
        found = _URL_SPLIT_PATTERN.findall(text)
        normalized: list[str] = []
        seen: set[str] = set()
        for item in found:
            cleaned = item.strip().rstrip(".,)")
            if cleaned and cleaned not in seen:
                url = self._normalize_tracking_url(cleaned)
                key = url.rstrip("/").lower()
                if key not in seen:
                    normalized.append(url)
                    seen.add(key)
        return normalized

    def _normalize_tracking_url(self, value: str) -> str:
        try:
            parsed = urlparse(value)
            if not parsed.scheme or not parsed.netloc:
                return value
            query = []
            raw_query = parsed.query.split("&") if parsed.query else []
            for item in raw_query:
                if "=" in item:
                    key, val = item.split("=", 1)
                else:
                    key = item
                    val = ""
                if any(pattern.match(key.strip()) for pattern in _TRACKING_PARAM_PATTERNS):
                    continue
                if val:
                    query.append(f"{key}={val}")
                else:
                    query.append(key)
            normalized_query = "&".join(query)
            parsed = parsed._replace(query=normalized_query)
            return parsed.geturl()
        except Exception:
            return value

    def _cleanup_signal_text(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""
        compacted: list[str] = []
        seen: set[str] = set()
        for line in lines:
            lowered = line.lower().strip()
            if any(pattern.match(lowered) for pattern in _NOISE_LINE_PATTERNS):
                continue
            if any(pattern.match(lowered) for pattern in _NOISE_INLINE_PATTERNS):
                continue
            if lowered in seen:
                continue
            compacted.append(line.strip())
            seen.add(lowered)
        return " ".join(compacted)

    def _isolate_signal_text(self, text: str) -> str:
        if not text:
            return ""
        cleaned = text.replace("\r", " ").replace("\n", " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"\[/?(?:dot\.move|link)\]", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = self._cleanup_signal_text(cleaned)
        return cleaned

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

    @staticmethod
    def _url_host(value: str) -> str:
        try:
            parsed = urlparse(value)
            return (parsed.netloc or "").lower()
        except Exception:
            return ""

    @staticmethod
    def _has_ig_uxui_signal(text: str, attachment_text: str = "") -> bool:
        lowered = f"{text} {attachment_text}".lower()
        return "instagram" in lowered and (
            any(token in lowered for token in _IDEA_HINTS | _UXUI_HINTS)
            or "ux" in lowered
            or "ui" in lowered
            or "디자인" in lowered
        )

    def _explicit_type_from_text(self, text: str) -> str | None:
        lower = text.lower().strip()
        for token, mapped in _EXPLICIT_TYPE_TOKENS.items():
            if lower.startswith(token):
                return mapped
        return None

    def _rule_classify(
        self,
        text: str,
        urls: list[str],
        attachments: list[dict[str, Any]],
    ) -> tuple[str, float, str]:
        has_uxui_hint = self._has_any_hint(text, _UXUI_HINTS)
        has_idea_hint = self._has_any_hint(text, _IDEA_HINTS)
        has_photo_hint = self._has_any_hint(text, _PHOTO_HINTS)
        has_music_hint = self._has_any_hint(text, _MUSIC_HINTS)
        has_youtube_hint = self._has_any_hint(text, _YOUTUBE_HINTS)
        explicit_type = self._explicit_type_from_text(text)

        if explicit_type in _ALLOWED_TYPES:
            return (explicit_type, 0.99, "explicit_token")

        if not text and attachments:
            image_count = len([x for x in attachments if bool(x.get("is_image"))])
            if image_count:
                return ("photo", 0.96, "image_attachment")

        if urls:
            if has_uxui_hint or has_idea_hint:
                return ("idea", 0.96, "uxui_idea_text_with_url")
            # music.youtube.com 또는 유튜브 링크+음악 문맥은 music으로 라우팅.
            if any("music.youtube.com" in url.lower() for url in urls):
                return ("music", 0.97, "music_youtube_domain")
            if any(self._is_youtube_url(url) for url in urls):
                if has_music_hint:
                    return ("music", 0.94, "youtube_url_music_hint")
                if any(self._url_host(url).startswith("instagram.") for url in urls):
                    return ("youtube", 0.8, "youtube_hint_on_instagram_link")
                return ("youtube", 0.95, "youtube_url")
            if any(self._is_music_url(url) for url in urls):
                return ("music", 0.9, "music_platform_url")
            if any(self._is_image_url(url) for url in urls):
                if has_uxui_hint or has_idea_hint:
                    return ("idea", 0.9, "image_url_uxui_idea")
                if has_photo_hint:
                    return ("photo", 0.96, "image_url_photo_hint")
                return ("photo", 0.85, "image_url_default")
            if any(self._is_social_url(url) for url in urls):
                if has_photo_hint:
                    return ("photo", 0.82, "social_photo_hint")
                if self._has_ig_uxui_signal(text):
                    return ("idea", 0.92, "instagram_social_uxui")
                return ("link", 0.93, "social_default")
            if has_youtube_hint:
                return ("youtube", 0.8, "youtube_keyword")
            if has_music_hint:
                return ("music", 0.8, "music_keyword")
            # 일반 웹 링크는 link 기본값.
            return ("link", 0.92, "default_url")

        if attachments:
            image_count = len([x for x in attachments if bool(x.get("is_image"))])
            if image_count >= max(1, len(attachments) // 2):
                if has_uxui_hint or has_idea_hint:
                    return ("idea", 0.86, "attachments_uxui_idea")
                return ("photo", 0.85, "attachments_image")

        if has_music_hint:
            return ("music", 0.72, "music_keyword")
        if has_youtube_hint:
            return ("youtube", 0.72, "youtube_keyword")
        return ("idea", 0.7, "default_text")

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

    def _build_title(
        self,
        curation_type: str,
        text: str,
        urls: list[str],
        attachments: list[dict[str, Any]],
    ) -> str:
        type_upper = curation_type.upper()
        compact_text = self._cleanup_signal_text(_strip_urls_for_title(text))
        base = compact_text.strip()
        if not base and urls:
            url = urls[0]
            if curation_type == "link":
                base = "참고 링크"
            else:
                base = _compact_url_for_title(url)
                if not base:
                    base = url
        if not base and attachments:
            base = str(attachments[0].get("filename") or "첨부 파일")
        if not base:
            base = "새 제보"
        base = base.replace("\n", " ").strip()
        return f"[{type_upper}] {truncate_text(base, 72, suffix='')}".strip()

    def _build_summary(self, text: str, urls: list[str], attachments: list[dict[str, Any]]) -> str:
        chunks: list[str] = []
        signal = self._cleanup_signal_text(text)
        # URLs are summarized separately as 링크 n건; 본문 요약에 원문 링크가 남지 않게 제거한다.
        signal = _URL_SPLIT_PATTERN.sub("", signal)
        if signal:
            sentences = [part for part in _SENTENCE_END_PATTERN.split(signal) if part.strip()]
            if not sentences:
                sentences = [signal]
            chunks.append(truncate_text(sentences[0], 180, suffix=" ..."))
        if not chunks and urls:
            if len(urls) == 1:
                chunks.append(f"링크 1건")
            else:
                chunks.append(f"링크 {len(urls)}건")
        if attachments:
            if len(attachments) == 1:
                name = str(attachments[0].get("filename") or "첨부 파일")
                chunks.append(f"첨부: {truncate_text(name, 32, suffix='...')}")
            else:
                chunks.append(f"첨부 {len(attachments)}건")
        return " / ".join(chunks) if chunks else "내용 요약 없음"

    @staticmethod
    def _sanitize_title(text: str, fallback: str) -> str:
        cleaned = _strip_urls_for_title(text)
        if not cleaned:
            cleaned = fallback
        return truncate_text(cleaned.replace("\n", " ").strip(), 72, suffix="")

    @staticmethod
    def _is_link_count_summary(value: str) -> bool:
        stripped = (value or "").strip()
        return bool(re.match(r"^링크\s+\d+건(?:\s*/\s*)?$", stripped))

    @staticmethod
    def _curation_intro(curation_type: str) -> str:
        return _TYPE_INTRO.get(curation_type, _TYPE_INTRO["idea"])

    def _one_sentence_teaser(self, curation_type: str, title: str, tags: list[str]) -> str:
        type_label = str(curation_type).lower()
        tag_hint = " · ".join(t for t in (tags or [])[:2]) or "#curation"
        clean_title = self._sanitize_title(title, fallback="[큐레이션]")
        if type_label == "link":
            return f"🧠 제보 핵심 한 줄: `{clean_title}` / 참고 링크가 도착했습니다. 적용 가능 항목인지 빠르게 판단하세요. ({tag_hint})"
        if type_label == "idea":
            return f"🚀 제보 핵심 한 줄: `{clean_title}` / 아이디어로 바로 연결 가능한 제안입니다. 실행 포인트를 골라보세요. ({tag_hint})"
        if type_label == "music":
            return f"🎧 제보 핵심 한 줄: `{clean_title}` / 음악/사운드 관련 자원입니다. 콘텐츠 운영에 바로 연결해도 좋습니다. ({tag_hint})"
        if type_label == "youtube":
            return f"🎬 제보 핵심 한 줄: `{clean_title}` / 참고 가능한 영상 제보입니다. 체크포인트를 바로 정리해보세요. ({tag_hint})"
        if type_label == "photo":
            return f"🖼️ 제보 핵심 한 줄: `{clean_title}` / 비주얼 참고용 제보입니다. 톤/메시지 정합성 판단용으로 적합합니다. ({tag_hint})"
        return f"🧩 제보 핵심 한 줄: `{clean_title}` / 운영 판단이 필요한 인풋입니다. 지금 바로 분류/반영 여부를 정하세요. ({tag_hint})"

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
            else:
                title = self._sanitize_title(
                    title,
                    fallback=self._build_title(curation_type, text, urls, attachments),
                )
            if not summary:
                summary = self._build_summary(text, urls, attachments)
            else:
                summary = _normalize_display_summary(summary)
            if not tags:
                tags = self._simple_tags(text, curation_type, urls)
            return ClassificationResult(
                curation_type=curation_type,
                confidence=0.8,
                title=title,
                summary=summary,
                tags=tags,
                reason="ai_enrich",
            )
        except Exception:
            return None

    def classify_message(self, message: discord.Message) -> ClassificationResult:
        raw_text = (message.content or "").strip()
        text = self._isolate_signal_text(raw_text)
        urls = self._extract_urls(raw_text)
        attachments = self._collect_attachment_meta(message)

        curation_type, confidence, reason = self._rule_classify(text, urls, attachments)
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
            ai_result = ClassificationResult(
                curation_type=ai_result.curation_type,
                confidence=ai_result.confidence,
                title=ai_result.title,
                summary=ai_result.summary,
                tags=ai_result.tags,
                reason="ai_enrich",
            )
            return ai_result

        return ClassificationResult(
            curation_type=curation_type,
            confidence=confidence,
            title=self._build_title(curation_type, text, urls, attachments),
            summary=self._build_summary(text, urls, attachments),
            tags=self._simple_tags(text, curation_type, urls),
            reason=reason,
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
            "classification_reason": classification.reason,
            "normalization_profile": _NORMALIZATION_PROFILE,
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
                "classification_reason": classification.reason,
                "normalization_profile": _NORMALIZATION_PROFILE,
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
                "classification_reason": classification.reason,
                "normalization_profile": _NORMALIZATION_PROFILE,
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
        text = str(submission.get("raw_text") or "")
        urls = [str(x) for x in (submission.get("urls") or []) if str(x)]
        attachments = submission.get("attachments") if isinstance(submission.get("attachments"), list) else []
        fallback_title = self._build_title(curation_type, text, urls, attachments)
        title = self._sanitize_title(str(submission.get("normalized_title") or ""), fallback=fallback_title)
        summary = _normalize_display_summary(str(submission.get("normalized_summary") or ""))
        tags = submission.get("tags") if isinstance(submission.get("tags"), list) else []
        urls = submission.get("urls") if isinstance(submission.get("urls"), list) else []
        attachments = submission.get("attachments") if isinstance(submission.get("attachments"), list) else []
        source_message_link = str(submission.get("source_message_link", "")).strip()
        reason = str(submission.get("classification_reason", "rules"))
        profile = str(submission.get("normalization_profile", _NORMALIZATION_PROFILE))

        intro = self._curation_intro(curation_type)

        author = submission.get("author_id")
        author_line = f"작성자 <@{author}>" if author else "작성자 미확인"
        embed = discord.Embed(
            title="🗂️ 큐레이션 승인 대기",
            description=f"{author_line}\n**{title}**\n{intro}",
            color=discord.Colour.orange(),
        )
        embed.add_field(name="분류", value=curation_type, inline=True)
        embed.add_field(name="분류 근거", value=truncate_text(reason, 256), inline=True)
        embed.add_field(name="정규화", value=truncate_text(profile, 256), inline=True)
        embed.add_field(name="상태", value=str(submission.get("status", "pending")), inline=True)
        embed.add_field(name="작성자", value=f"<@{submission.get('author_id')}>", inline=True)
        if summary and not self._is_link_count_summary(summary):
            embed.add_field(name="요약", value=truncate_text(summary, 1024), inline=False)
        if tags:
            embed.add_field(name="태그", value=" ".join(str(x) for x in tags[:12]), inline=False)
        if urls:
            preview = "\n".join(f"- {_short_url_display(str(u))}" for u in urls[:6])
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
        notified = False
        if isinstance(target_channel, discord.TextChannel) and message_id:
            text = str(submission.get("raw_text") or "")
            urls = [str(x) for x in (submission.get("urls") or []) if str(x)]
            attachments = submission.get("attachments") if isinstance(submission.get("attachments"), list) else []
            curation_type = str(submission.get("classified_type", "idea")).lower()
            if curation_type not in _ALLOWED_TYPES:
                curation_type = "idea"
            fallback_title = self._build_title(curation_type, text, urls, attachments)
            title = self._sanitize_title(str(submission.get("normalized_title") or ""), fallback=fallback_title)
            intro = self._curation_intro(curation_type)
            text_lines = [
                f"🔁 이미 큐레이션된 항목입니다. 새 제보는 병합 저장됐습니다.",
                f"제목: {title}",
                f"{intro}",
                f"작성자: <@{submission.get('author_id')}>",
                f"원문: {submission.get('source_message_link') or '-'}",
            ]

            await retry_discord_call(
                lambda: target_channel.send(
                    "\n".join(line for line in text_lines if line is not None),
                    suppress_embeds=True,
                )
            )
            notified = True
        if not notified:
            await self.storage.append_ops_event(
                "curation_merged_duplicate",
                {
                    "guild_id": guild.id,
                    "channel_id": channel_id or submission.get("source_channel_id"),
                    "user_id": reviewer_id,
                    "command_name": "curation_publish",
                    "submission_id": submission.get("submission_id"),
                    "duplicate_of": duplicate_target.get("submission_id"),
                    "target_message_id": message_id or None,
                    "thread_id": thread_id or None,
                    "result": "no_target_channel",
                },
                idempotency_key=f"curation_merge_orphan:{submission.get('submission_id')}:{duplicate_target.get('submission_id')}",
            )

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
        text = str(submission.get("raw_text") or "")
        urls = [str(x) for x in (submission.get("urls") or []) if str(x)]
        attachments = submission.get("attachments") if isinstance(submission.get("attachments"), list) else []
        fallback_title = self._build_title(curation_type, text, urls, attachments)
        title = self._sanitize_title(str(submission.get("normalized_title") or ""), fallback=fallback_title)
        links_text = (
            _short_url_display(str(urls[0])) if len(urls) == 1
            else "\n".join(f"- {_short_url_display(str(u))}" for u in urls[:10])
        ) if urls else "- 없음"
        links_label = f"링크 ({len(urls)}건)"
        if len(urls) <= 1:
            links_label = "링크"
        summary = _normalize_display_summary(str(submission.get("normalized_summary") or ""))
        link_summary_only = self._is_link_count_summary(summary)
        intro = self._curation_intro(curation_type)
        teaser = self._one_sentence_teaser(curation_type, title, tags)

        lines = [
            f"🧠 망상궤도 큐레이션 - {title}",
            f"작성자: <@{submission.get('author_id')}>",
            teaser,
            f"요약: {summary}" if summary and not link_summary_only else f"요약: {intro}",
            "",
            links_label,
            links_text,
            "",
            f"태그: {tags_text}",
            f"원문: {submission.get('source_message_link') or '-'}",
        ]
        if mention_text:
            lines.append(f"멘션: {mention_text}")

        if not summary or link_summary_only:
            lines[3] = f"요약: {intro}"
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
                suppress_embeds=True,
                files=files if files else None,
                allowed_mentions=allowed_mentions,
            )
        )

        thread_id: int | None = None

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
