from __future__ import annotations

import asyncio
from pathlib import Path

from bot.services.curation import CurationService
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
