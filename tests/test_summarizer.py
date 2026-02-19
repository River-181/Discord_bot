from __future__ import annotations

from bot.services.summarizer import SummarizerService


def test_fallback_extract() -> None:
    service = SummarizerService(model="gemini-1.5-flash", timeout_seconds=10, gemini_api_key=None)
    messages = [
        {"author": "a", "content": "결정: 이번 주에 배포하기로", "created_at": "2026-02-16T10:00:00"},
        {"author": "b", "content": "TODO 담당 민수, 금요일까지 API 정리", "created_at": "2026-02-16T10:02:00"},
        {"author": "c", "content": "리스크: 서버다운 가능성", "created_at": "2026-02-16T10:03:00"},
    ]

    result = service.summarize(messages, scope_label="channel")
    assert result.fallback_used is True
    assert any("결정" in x for x in result.decisions)
    assert any("TODO" in x for x in result.actions)
    assert any("리스크" in x for x in result.risks)
