from __future__ import annotations

import hashlib
import html
import logging
import re
import ssl
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import aiohttp
import certifi
import discord
import feedparser

from bot.services.retry import retry_discord_call
from bot.services.storage import StorageService
from bot.utils import find_text_channel_by_name, truncate_text

LOGGER = logging.getLogger("mangsang-orbit-assistant")
FIELD_VALUE_LIMIT = 1024
EMBED_FIELD_MAX = 25
EMBED_TOTAL_SAFE_LIMIT = 5800


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _strip_html(value: str) -> str:
    # RSS descriptions are often HTML snippets. Keep it simple and safe.
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\\s+", " ", value).strip()
    return value


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def build_google_news_rss_url(query: str) -> str:
    q = quote_plus(query)
    return f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"


@dataclass(frozen=True)
class TopicConfig:
    name: str
    query: str


@dataclass(frozen=True)
class NewsItem:
    topic: str
    title: str
    url: str
    source: str
    published_at: str | None
    description: str | None
    hash: str


@dataclass(frozen=True)
class DigestResult:
    digest_id: str
    posted_message_id: int | None
    digest_channel_id: int | None
    jump_url: str | None
    items_count: int
    skipped_count: int
    error_count: int


class NewsService:
    def __init__(
        self,
        *,
        timezone: str,
        channels_config: dict[str, str],
        news_config: dict[str, Any],
        storage: StorageService,
        gemini_api_key: str | None = None,
        gemini_model: str = "gemini-2.0-flash",
        gemini_timeout_seconds: int = 25,
    ) -> None:
        self.tz = ZoneInfo(timezone)
        self.channels_config = channels_config
        self.news_config = news_config
        self.storage = storage

        self.gemini_api_key = gemini_api_key
        self.gemini_model = gemini_model
        self.gemini_timeout_seconds = gemini_timeout_seconds

        self._ssl_context = ssl.create_default_context(cafile=certifi.where())

        # Lazy import to keep failure localized.
        self._genai_client = None
        if gemini_api_key:
            try:
                from google import genai  # type: ignore
                from google.genai import types as genai_types  # type: ignore

                self._genai_client = (genai.Client(api_key=gemini_api_key), genai_types)
            except Exception:
                self._genai_client = None

    def enabled(self) -> bool:
        return bool(self.news_config.get("enabled", False))

    def _topics(self) -> list[TopicConfig]:
        topics_raw = self.news_config.get("topics") or []
        topics: list[TopicConfig] = []
        for item in topics_raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            query = str(item.get("query", "")).strip()
            if not name or not query:
                continue
            topics.append(TopicConfig(name=name, query=query))
        return topics

    def _dedupe_hashes(self, dedupe_days: int) -> set[str]:
        cutoff = datetime.now(UTC) - timedelta(days=dedupe_days)
        seen: set[str] = set()
        for row in self.storage.read_jsonl("news_items"):
            fetched_at = _parse_utc_iso(str(row.get("fetched_at", "")))
            if fetched_at and fetched_at < cutoff:
                continue
            h = row.get("hash")
            if h:
                seen.add(str(h))
        return seen

    async def fetch_feed(self, session: aiohttp.ClientSession, url: str) -> bytes:
        headers = {"User-Agent": "mangsang-orbit-assistant/1.0 (RSS; contact: ops)"}
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            return await resp.read()

    def parse_rss(self, xml_bytes: bytes) -> list[dict[str, Any]]:
        parsed = feedparser.parse(xml_bytes)
        entries = getattr(parsed, "entries", []) or []
        out: list[dict[str, Any]] = []
        for entry in entries:
            try:
                out.append(dict(entry))
            except Exception:
                continue
        return out

    def _entry_published_utc(self, entry: dict[str, Any]) -> datetime | None:
        st = entry.get("published_parsed") or entry.get("updated_parsed")
        if not st:
            return None
        try:
            # feedparser uses time.struct_time (UTC-ish). Treat as UTC.
            return datetime(*st[:6], tzinfo=UTC)
        except Exception:
            return None

    def _entry_source(self, entry: dict[str, Any]) -> str:
        source = ""
        src_obj = entry.get("source")
        if isinstance(src_obj, dict):
            source = str(src_obj.get("title", "")).strip()
        if source:
            return source
        # Google News often has "Title - Source" in title. Try last split.
        title = str(entry.get("title", "")).strip()
        if " - " in title:
            return title.rsplit(" - ", 1)[-1].strip()
        return ""

    def _entry_url(self, entry: dict[str, Any]) -> str:
        link = str(entry.get("link", "")).strip()
        if link:
            return link
        links = entry.get("links") or []
        if isinstance(links, list) and links:
            href = links[0].get("href")
            if href:
                return str(href)
        return ""

    def _entry_description(self, entry: dict[str, Any]) -> str:
        summary = str(entry.get("summary", "") or entry.get("description", "") or "").strip()
        return _strip_html(summary) if summary else ""

    def _filter_by_window(self, items: list[NewsItem], window_hours: int) -> list[NewsItem]:
        if window_hours <= 0:
            return items
        cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
        out: list[NewsItem] = []
        for item in items:
            published = _parse_utc_iso(item.published_at) if item.published_at else None
            if published and published < cutoff:
                continue
            out.append(item)
        return out

    async def _one_line_summary(self, item: NewsItem) -> str:
        # Default: use description snippet or a safe generic phrase.
        fallback = truncate_text(item.description or "관련 소식입니다.", 110, suffix=" ...")
        if not self._genai_client:
            return fallback

        client, genai_types = self._genai_client
        prompt = (
            "다음 뉴스 항목을 한국어 한 줄(최대 110자)로 요약하세요. "
            "원문을 길게 인용하지 말고 맥락만 말하세요.\n\n"
            f"제목: {item.title}\n"
            f"출처: {item.source}\n"
            f"설명: {truncate_text(item.description or '', 300, suffix=' ...')}\n"
        )
        try:
            response = client.models.generate_content(
                model=self.gemini_model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=140,
                ),
            )
            text = str(getattr(response, "text", "") or "").strip()
            if not text:
                return fallback
            # Normalize to single line.
            text = re.sub(r"\\s+", " ", text).strip()
            return truncate_text(text, 110, suffix=" ...")
        except Exception:
            return fallback

    def _format_bullet(self, item: NewsItem, one_liner: str) -> str:
        title = truncate_text(item.title, 90, suffix=" ...")
        source = truncate_text(item.source or "source", 30, suffix=" ...")
        one_liner = truncate_text(one_liner, 110, suffix=" ...")
        return f"• [{title}]({item.url}) — ({source}) · {one_liner}"

    def _split_topic_fields(self, topic: str, bullets: list[str]) -> tuple[list[tuple[str, str]], int]:
        fields: list[tuple[str, str]] = []
        current_lines: list[str] = []
        current_len = 0
        line_truncated_count = 0

        def _push_current() -> None:
            nonlocal current_lines, current_len
            if not current_lines:
                return
            field_name = topic if not fields else f"{topic} (계속)"
            fields.append((field_name, "\n".join(current_lines)))
            current_lines = []
            current_len = 0

        for raw_line in bullets:
            line = raw_line
            if len(line) > FIELD_VALUE_LIMIT:
                line = truncate_text(line, FIELD_VALUE_LIMIT - len(" (길이 제한)"), suffix=" (길이 제한)")
                line_truncated_count += 1

            if not current_lines:
                current_lines = [line]
                current_len = len(line)
                continue

            projected = current_len + 1 + len(line)
            if projected <= FIELD_VALUE_LIMIT:
                current_lines.append(line)
                current_len = projected
                continue

            _push_current()
            current_lines = [line]
            current_len = len(line)

        _push_current()
        return fields, line_truncated_count

    def _embed_char_count(self, embed: discord.Embed) -> int:
        total = 0
        total += len(embed.title or "")
        total += len(embed.description or "")
        if embed.footer and embed.footer.text:
            total += len(embed.footer.text)
        for field in embed.fields:
            total += len(field.name or "")
            total += len(field.value or "")
        return total

    def _new_digest_embed(
        self,
        *,
        kind_label: str,
        window_hours: int,
        selected_count: int,
        candidate_count: int,
        per_topic_limit: int,
        max_total_items: int,
        continued: bool,
    ) -> discord.Embed:
        now_local = datetime.now(self.tz).replace(microsecond=0)
        title = f"🛰️ 뉴스 레이다 ({kind_label})"
        if continued:
            title = f"{title} · 계속"
        description = (
            f"최근 {window_hours}시간 기준, 정책(per_topic_limit={per_topic_limit}, "
            f"max_total_items={max_total_items})으로 선정한 링크 다이제스트입니다. "
            f"표시 항목: {selected_count}건 (선정 후보 {candidate_count}건). "
            "토론은 스레드에서 진행하세요."
        )
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Colour.blurple(),
            timestamp=now_local,
        )

    def _build_embeds_paginated(
        self,
        *,
        kind_label: str,
        window_hours: int,
        bullets_by_topic: dict[str, list[str]],
        selected_count: int,
        candidate_count: int,
        per_topic_limit: int,
        max_total_items: int,
    ) -> tuple[list[discord.Embed], dict[str, int]]:
        all_fields: list[tuple[str, str]] = []
        line_truncated_count = 0
        for topic, bullets in bullets_by_topic.items():
            if not bullets:
                continue
            topic_fields, topic_truncated = self._split_topic_fields(topic, bullets)
            all_fields.extend(topic_fields)
            line_truncated_count += topic_truncated

        embeds: list[discord.Embed] = []
        current = self._new_digest_embed(
            kind_label=kind_label,
            window_hours=window_hours,
            selected_count=selected_count,
            candidate_count=candidate_count,
            per_topic_limit=per_topic_limit,
            max_total_items=max_total_items,
            continued=False,
        )
        embeds.append(current)

        for name, value in all_fields:
            projected = self._embed_char_count(current) + len(name) + len(value)
            if len(current.fields) >= EMBED_FIELD_MAX or projected > EMBED_TOTAL_SAFE_LIMIT:
                current = self._new_digest_embed(
                    kind_label=kind_label,
                    window_hours=window_hours,
                    selected_count=selected_count,
                    candidate_count=candidate_count,
                    per_topic_limit=per_topic_limit,
                    max_total_items=max_total_items,
                    continued=True,
                )
                embeds.append(current)
            current.add_field(name=name, value=value, inline=False)

        for idx, embed in enumerate(embeds, start=1):
            embed.set_footer(text=f"페이지 {idx}/{len(embeds)}")

        stats = {
            "embed_count": len(embeds),
            "field_count": len(all_fields),
            "line_truncated_count": line_truncated_count,
        }
        return embeds, stats

    async def _post_log_line(
        self,
        *,
        guild: discord.Guild,
        log_channel: discord.TextChannel | None,
        line: str,
    ) -> None:
        if not log_channel:
            return
        await retry_discord_call(lambda: log_channel.send(line))

    async def _post_paginated_digest(
        self,
        *,
        digest_channel: discord.TextChannel,
        embeds: list[discord.Embed],
    ) -> tuple[discord.Message | None, int, str | None]:
        if not embeds:
            return (None, 0, None)

        first_message = await retry_discord_call(lambda: digest_channel.send(embed=embeds[0]))
        pages_in_thread = 0
        thread_jump_url: str | None = None

        if len(embeds) <= 1:
            # Keep thread for discussion even on single page.
            try:
                thread = await retry_discord_call(
                    lambda: first_message.create_thread(
                        name=f"토론 · {datetime.now(self.tz).strftime('%m/%d %H:%M')}",
                        auto_archive_duration=1440,
                    )
                )
                thread_jump_url = thread.jump_url
            except Exception:
                thread_jump_url = None
            return (first_message, pages_in_thread, thread_jump_url)

        # For multi-page digests, keep page 1 in channel and page 2+ in thread.
        thread: discord.Thread | None = None
        try:
            thread = await retry_discord_call(
                lambda: first_message.create_thread(
                    name=f"뉴스 레이다 상세 · {datetime.now(self.tz).strftime('%m/%d %H:%M')}",
                    auto_archive_duration=1440,
                )
            )
            thread_jump_url = thread.jump_url
        except Exception:
            thread = None

        if thread:
            for embed in embeds[1:]:
                await retry_discord_call(lambda e=embed: thread.send(embed=e))
                pages_in_thread += 1
            return (first_message, pages_in_thread, thread_jump_url)

        # Thread creation failed, fallback: post all remaining pages to channel.
        for embed in embeds[1:]:
            await retry_discord_call(lambda e=embed: digest_channel.send(embed=e))
        return (first_message, 0, None)

    async def run_digest(
        self,
        *,
        bot: discord.Client,
        guild_id: int,
        window_hours: int | None = None,
        kind: str = "scheduled",
    ) -> DigestResult:
        digest_id = str(uuid.uuid4())
        window_hours = int(window_hours or int(self.news_config.get("window_hours", 12) or 12))
        per_topic_limit = int(self.news_config.get("per_topic_limit", 8) or 8)
        max_total_items = int(self.news_config.get("max_total_items", 40) or 40)
        dedupe_days = int(self.news_config.get("dedupe_days", 7) or 7)

        await self.storage.append_ops_event(
            "news_digest_started",
            {
                "digest_id": digest_id,
                "guild_id": guild_id,
                "window_hours": window_hours,
                "kind": kind,
            },
            idempotency_key=f"news_digest_started:{kind}:{digest_id}",
        )

        guild = getattr(bot, "get_guild")(guild_id) if hasattr(bot, "get_guild") else None
        if not isinstance(guild, discord.Guild):
            await self.storage.append_ops_event(
                "news_post_error",
                {"digest_id": digest_id, "guild_id": guild_id, "error": "guild_not_found"},
            )
            return DigestResult(
                digest_id=digest_id,
                posted_message_id=None,
                digest_channel_id=None,
                jump_url=None,
                items_count=0,
                skipped_count=0,
                error_count=1,
            )

        digest_channel_name = str(self.channels_config.get("news_digest", "")).strip()
        log_channel_name = str(self.channels_config.get("news_log", "")).strip()
        fallback_name = str(self.channels_config.get("assistant_output", "")).strip()

        digest_channel = find_text_channel_by_name(guild, digest_channel_name) if digest_channel_name else None
        if not digest_channel and fallback_name:
            digest_channel = find_text_channel_by_name(guild, fallback_name)
            await self.storage.append_ops_event(
                "news_post_error",
                {
                    "digest_id": digest_id,
                    "guild_id": guild_id,
                    "error": "digest_channel_missing_fallback",
                    "digest_channel_name": digest_channel_name,
                    "fallback": fallback_name,
                },
                idempotency_key=f"news_channel_fallback:{guild_id}:{digest_id}",
            )

        log_channel = find_text_channel_by_name(guild, log_channel_name) if log_channel_name else None
        if not log_channel and fallback_name:
            log_channel = find_text_channel_by_name(guild, fallback_name)

        if not digest_channel:
            await self.storage.append_ops_event(
                "news_post_error",
                {"digest_id": digest_id, "guild_id": guild_id, "error": "no_digest_channel"},
            )
            return DigestResult(
                digest_id=digest_id,
                posted_message_id=None,
                digest_channel_id=None,
                jump_url=None,
                items_count=0,
                skipped_count=0,
                error_count=1,
            )

        topics = self._topics()
        seen_hashes = self._dedupe_hashes(dedupe_days=dedupe_days)

        fetched_items: list[NewsItem] = []
        errors = 0
        skipped = 0

        connector = aiohttp.TCPConnector(ssl=self._ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            for topic in topics:
                feed_url = build_google_news_rss_url(topic.query)
                try:
                    xml = await self.fetch_feed(session, feed_url)
                    entries = self.parse_rss(xml)
                except Exception as exc:
                    errors += 1
                    await self.storage.append_ops_event(
                        "news_fetch_error",
                        {"digest_id": digest_id, "topic": topic.name, "error": f"{type(exc).__name__}: {exc}"},
                    )
                    continue

                for entry in entries:
                    url = self._entry_url(entry)
                    title = str(entry.get("title", "")).strip()
                    if not url or not title:
                        continue
                    h = _sha256_hex(url)
                    if h in seen_hashes:
                        skipped += 1
                        continue
                    published_dt = self._entry_published_utc(entry)
                    published_at = (
                        published_dt.isoformat(timespec="seconds").replace("+00:00", "Z") if published_dt else None
                    )
                    source = self._entry_source(entry)
                    desc = self._entry_description(entry)
                    fetched_items.append(
                        NewsItem(
                            topic=topic.name,
                            title=title,
                            url=url,
                            source=source,
                            published_at=published_at,
                            description=desc,
                            hash=h,
                        )
                    )

        fetched_items = self._filter_by_window(fetched_items, window_hours=window_hours)
        candidate_count = len(fetched_items)
        # Sort newest first, unknown published at end.
        fetched_items.sort(
            key=lambda x: _parse_utc_iso(x.published_at or "") or datetime(1970, 1, 1, tzinfo=UTC),
            reverse=True,
        )

        # Select final items with per-topic and global limits.
        selected: list[NewsItem] = []
        per_topic_counts: dict[str, int] = {}
        for item in fetched_items:
            if len(selected) >= max_total_items:
                break
            count = per_topic_counts.get(item.topic, 0)
            if count >= per_topic_limit:
                continue
            selected.append(item)
            per_topic_counts[item.topic] = count + 1

        # Build bullets (summaries are generated only for selected items).
        bullets_by_topic: dict[str, list[str]] = {t.name: [] for t in topics}
        for item in selected:
            one_liner = await self._one_line_summary(item)
            bullets_by_topic.setdefault(item.topic, []).append(self._format_bullet(item, one_liner))

        embeds, pagination_stats = self._build_embeds_paginated(
            kind_label=kind,
            window_hours=window_hours,
            bullets_by_topic=bullets_by_topic,
            selected_count=len(selected),
            candidate_count=candidate_count,
            per_topic_limit=per_topic_limit,
            max_total_items=max_total_items,
        )

        await self.storage.append_ops_event(
            "news_digest_paginated",
            {
                "digest_id": digest_id,
                "embed_count": pagination_stats["embed_count"],
                "field_count": pagination_stats["field_count"],
                "line_truncated_count": pagination_stats["line_truncated_count"],
            },
        )

        posted_message: discord.Message | None = None
        pages_in_thread = 0
        thread_jump_url: str | None = None
        try:
            posted_message, pages_in_thread, thread_jump_url = await self._post_paginated_digest(
                digest_channel=digest_channel,
                embeds=embeds,
            )
        except Exception as exc:
            errors += 1
            await self.storage.append_ops_event(
                "news_post_error",
                {"digest_id": digest_id, "error": f"{type(exc).__name__}: {exc}"},
            )

        jump_url = posted_message.jump_url if posted_message else None
        posted_message_id = posted_message.id if posted_message else None
        digest_channel_id = digest_channel.id if digest_channel else None

        # Persist items and digest record.
        for item in selected:
            await self.storage.append_news_item(
                {
                    "item_id": str(uuid.uuid4()),
                    "topic": item.topic,
                    "title": item.title,
                    "url": item.url,
                    "source": item.source,
                    "published_at": item.published_at,
                    "fetched_at": _utc_now_iso(),
                    "hash": item.hash,
                }
            )

        await self.storage.append_news_digest(
            {
                "digest_id": digest_id,
                "run_at": _utc_now_iso(),
                "window_hours": window_hours,
                "topics": [t.name for t in topics],
                "items_count": len(selected),
                "posted_message_id": posted_message_id,
                "digest_channel_id": digest_channel_id,
                "thread_jump_url": thread_jump_url,
                "pages_in_thread": pages_in_thread,
                "kind": kind,
            }
        )

        if skipped:
            await self.storage.append_ops_event(
                "news_dedupe_skipped",
                {"digest_id": digest_id, "skipped": skipped},
            )

        await self.storage.append_ops_event(
            "news_digest_completed",
            {
                "digest_id": digest_id,
                "guild_id": guild_id,
                "items": len(selected),
                "skipped": skipped,
                "errors": errors,
                "posted_message_id": posted_message_id,
                "digest_channel_id": digest_channel_id,
                "pages_in_thread": pages_in_thread,
            },
        )

        kind_label = "09:00" if kind == "morning" else "18:00" if kind == "evening" else kind
        await self._post_log_line(
            guild=guild,
            log_channel=log_channel,
            line=(
                f"🛰️ 뉴스 다이제스트({kind_label}) posted: {jump_url or '(post failed)'}"
                f" | items={len(selected)} | skipped={skipped} | errors={errors}"
                f" | thread_pages={pages_in_thread}"
            ),
        )

        return DigestResult(
            digest_id=digest_id,
            posted_message_id=posted_message_id,
            digest_channel_id=digest_channel_id,
            jump_url=jump_url,
            items_count=len(selected),
            skipped_count=skipped,
            error_count=errors,
        )
