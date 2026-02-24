from __future__ import annotations

import asyncio
from pathlib import Path

from bot.services.curation import CurationService, _normalize_display_summary, _short_url_display, _strip_urls_for_title
from bot.services.storage import DataFiles, StorageService


class _DummyAttachment:
    def __init__(self, filename: str, url: str, content_type: str | None = None) -> None:
        self.id = 1
        self.filename = filename
        self.url = url
        self.proxy_url = url
        self.size = 100
        self.content_type = content_type


class _DummyAuthor:
    def __init__(self) -> None:
        self.id = 10
        self.display_name = "tester"


class _DummyChannel:
    def __init__(self) -> None:
        self.id = 20


class _DummyMessage:
    def __init__(self, content: str, attachments: list[_DummyAttachment] | None = None) -> None:
        self.content = content
        self.attachments = attachments or []
        self.author = _DummyAuthor()
        self.channel = _DummyChannel()
        self.id = 30
        self.jump_url = "https://discord.com/channels/1/2/3"


def _make_storage(tmp_path: Path) -> StorageService:
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


def _make_service(tmp_path: Path) -> CurationService:
    storage = _make_storage(tmp_path)
    return CurationService(
        timezone="Asia/Seoul",
        config={"enabled": True},
        channels_config={},
        storage=storage,
        gemini_api_key=None,
        gemini_model="gemini-2.0-flash",
        gemini_timeout_seconds=25,
    )


def test_rule_classification_youtube(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage("이거 봐 https://youtu.be/abc")
    result = service.classify_message(msg)
    assert result.curation_type == "youtube"


def test_rule_classification_instagram_defaults_to_link(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage("https://www.instagram.com/p/DVGq8eSAQUR/")
    result = service.classify_message(msg)
    assert result.curation_type == "link"


def test_rule_classification_uxui_link_as_idea(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage("UXUI 참고 링크 https://www.instagram.com/p/DVGq8eSAQUR/")
    result = service.classify_message(msg)
    assert result.curation_type == "idea"
    assert "#uxui" in result.tags


def test_rule_classification_instagram_with_uxui_keyword_and_title_clean(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage("[dot.move] UX/UI 링크 정리: https://www.instagram.com/p/DVGq8eSAQUR/?utm_source=ig_web_copy_link")
    result = service.classify_message(msg)
    assert result.curation_type == "idea"
    assert result.title.startswith("[IDEA]")
    assert result.summary == "링크 1건" or "/ 링크 1건" in result.summary or "첨부" in result.summary


def test_rule_classification_instagram_without_uxui_as_link(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage("사진 올려봄 https://www.instagram.com/p/abc/")
    result = service.classify_message(msg)
    assert result.curation_type in {"link", "photo"}


def test_rule_classification_music_platform(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage("https://open.spotify.com/track/xyz")
    result = service.classify_message(msg)
    assert result.curation_type == "music"


def test_rule_classification_music_youtube_domain(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage("https://music.youtube.com/watch?v=abc")
    result = service.classify_message(msg)
    assert result.curation_type == "music"


def test_rule_classification_youtube_with_music_hint(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage("노래 추천 영상 https://www.youtube.com/watch?v=abc")
    result = service.classify_message(msg)
    assert result.curation_type == "music"


def test_rule_classification_social_photo_hint(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage("사진 모음 https://www.instagram.com/p/abc/")
    result = service.classify_message(msg)
    assert result.curation_type == "photo"


def test_rule_classification_explicit_type_override(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage("[idea] https://www.instagram.com/p/abc/")
    result = service.classify_message(msg)
    assert result.curation_type == "idea"


def test_rule_classification_photo_attachment(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage("", attachments=[_DummyAttachment("photo.png", "https://cdn/x.png", "image/png")])
    result = service.classify_message(msg)
    assert result.curation_type == "photo"


def test_rule_classification_image_attachment_with_idea_context(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage(
        "디자인 개선 의견입니다",
        attachments=[_DummyAttachment("screen.png", "https://cdn/x.png", "image/png")],
    )
    result = service.classify_message(msg)
    assert result.curation_type == "idea"


def test_signal_noise_isolation_removes_repeated_lines_and_social_noise(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage(
        "사진 2건 전달\n"
        "좋아요 3\n"
        "좋아요 3\n"
        "https://www.instagram.com/p/abc/?utm_source=ig_web_copy_link&igsh=NTc4MTIwNjQ2YQ== "
        "https://www.instagram.com/p/abc/?utm_source=ig_web_copy_link&igsh=NTc4MTIwNjQ2YQ== "
    )
    result = service.classify_message(msg)
    assert len(result.title) > 0
    # 링크 트래킹 파라미터 제거 후 중복도 제거되어야 함
    assert "utm_source" not in result.summary
    assert "#instagram" in result.tags


def test_extract_urls_deduplicates_and_normalizes_tracking(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    text = (
        "https://www.instagram.com/p/DVGq8eSAQUR/?utm_source=ig_web_copy_link&igsh=NTc4MTIwNjQ2YQ== "
        "https://www.instagram.com/p/DVGq8eSAQUR/?utm_source=another&igsh=abc"
    )
    urls = service._extract_urls(text)
    assert len(urls) == 1
    assert "utm_source" not in urls[0]


def test_should_detect_candidate(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage("아이디어: 다음 주 운영 개선")
    assert service.is_curation_candidate(msg) is True


def test_curation_summary_display_normalization() -> None:
    raw = "핵심 링크 정리입니다. https://github.com/shanraisshan/claude-code-best-practice / 링크 1건"
    normalized = _normalize_display_summary(raw)
    assert "https://" not in normalized
    assert normalized == "핵심 링크 정리입니다."


def test_curation_summary_normalization_removes_repeated_social_noise() -> None:
    raw = "\n".join(
        [
            "Sam Sifton",
            "Sam Sifton, the host of The Morning",
            "Sam Sifton",
            "좋아요 12",
            "Sam Sifton, the host of The Morning",
        ]
    )
    normalized = _normalize_display_summary(raw)
    assert "좋아요" not in normalized
    assert "Sam Sifton" in normalized
    # 중복 문구는 한 번만 남아야 한다
    assert normalized.count("Sam Sifton, the host of The Morning") == 1


def test_curation_summary_normalization_removes_inline_social_noise() -> None:
    raw = "좋아요 12 | Sam Sifton, the host of The Morning | Likes 33"
    normalized = _normalize_display_summary(raw)
    assert "좋아요" not in normalized
    assert "Likes" not in normalized
    assert normalized == "Sam Sifton, the host of The Morning"


def test_curation_publish_format_matches_template(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    lines = service._build_published_message_lines(
        title="[LINK] github.com/shanraisshan/claude-code-best-practice",
        summary="AI 코드 리뷰와 협업 패턴 정리 가이드입니다. 적용 가능성이 높습니다.",
        urls=["https://github.com/shanraisshan/claude-code-best-practice"],
        author_id=286,
        source_message_link="https://discord.com/channels/1/2/3",
        mention_role=None,
        mention_role_name="knowledge",
        tags=["#curation", "#ai", "#github", "#link"],
    )
    content = "\n".join(lines)
    assert content.startswith("훅: [LINK] github.com/shanraisshan/claude-code-best-practice")
    assert "요약:" in content
    assert "- AI 코드 리뷰와 협업 패턴 정리 가이드입니다." in content
    assert "링크: https://github.com/shanraisshan/claude-code-best-practice" in content
    assert "작성자: <@286>" in content
    assert "원문: https://discord.com/channels/1/2/3" in content
    assert "멘션: @knowledge" in content
    assert content.endswith("#curation #ai #github #link")
    assert "..." not in content


def test_curation_publish_format_multiple_urls_shows_total_count(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    lines = service._build_published_message_lines(
        title="[LINK] reference",
        summary="다중 링크 제보입니다.",
        urls=[
            "https://a.example.com/first",
            "https://b.example.com/second",
            "https://c.example.com/third",
        ],
        author_id=400,
        source_message_link="https://discord.com/channels/1/2/3",
        mention_role=None,
        mention_role_name="knowledge",
        tags=["#curation", "#link"],
    )
    content = "\n".join(lines)
    assert "링크: https://a.example.com/first (총 3건)" in content


def test_rule_classification_instagram_social_without_uxui_hint_defaults_to_link(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage("https://instagram.com/p/abc/")
    result = service.classify_message(msg)
    assert result.curation_type == "link"


def test_rule_classification_instagram_uxui_signal_as_idea(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    msg = _DummyMessage("UX/UI 분석 아이디어 공유: https://instagram.com/p/abc/")
    result = service.classify_message(msg)
    assert result.curation_type == "idea"


def test_curation_build_summary_does_not_append_link_count_if_signal_exists(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    text = "아이디어 공유: 인터페이스 정리 링크를 참고하세요"
    summary = service._build_summary(text, ["https://example.com/x"], [])
    assert "링크 1건" not in summary
    assert "인터페이스 정리" in summary

def test_curation_title_without_redundant_url() -> None:
    title = _strip_urls_for_title("https://github.com/shanraisshan/claude-code-best-practice")
    assert title == ""
    short = _short_url_display("https://github.com/shanraisshan/claude-code-best-practice")
    assert short == "github.com/shanraisshan/claude-code-best-practice"


def test_curation_title_generated_from_url_only_is_compact(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    text = "https://github.com/shanraisshan/claude-code-best-practice"
    title = service._build_title("link", text, [text], [])
    assert title == "[LINK] 참고 링크"


def test_review_embed_title_does_not_include_raw_url(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    submission = {
        "submission_id": "s1",
        "classified_type": "link",
        "raw_text": "https://github.com/shanraisshan/claude-code-best-practice",
        "urls": ["https://github.com/shanraisshan/claude-code-best-practice"],
        "attachments": [],
        "normalized_title": "",
        "normalized_summary": "링크 1건",
        "tags": ["#ai", "#curation"],
        "source_message_link": "https://discord.com/channels/1/2/3",
        "status": "pending",
        "author_id": 10,
        "normalization_profile": "compact_v2",
        "classification_reason": "rules",
    }
    embed = service.build_review_embed(submission, guild=None)
    assert "https://github.com/shanraisshan/claude-code-best-practice" not in embed.description


def test_counts_latest_status(tmp_path: Path) -> None:
    service = _make_service(tmp_path)

    async def _run() -> None:
        await service.storage.append_curation_submission(
            {
                "submission_id": "s1",
                "status": "pending",
                "created_at": "2026-02-24T00:00:00Z",
            }
        )
        await service.storage.append_curation_submission(
            {
                "submission_id": "s1",
                "status": "approved",
                "created_at": "2026-02-24T00:01:00Z",
            }
        )
        await service.storage.append_curation_submission(
            {
                "submission_id": "s2",
                "status": "rejected",
                "created_at": "2026-02-24T00:02:00Z",
            }
        )

    asyncio.run(_run())

    counts = service.counts()
    assert counts["total"] == 2
    assert counts["approved"] == 1
    assert counts["rejected"] == 1
    assert counts["pending"] == 0
