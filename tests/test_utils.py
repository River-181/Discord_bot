from __future__ import annotations

from bot.utils import slugify


def test_slugify_basic() -> None:
    assert slugify("쿵덕 v2") == "쿵덕-v2"
    assert slugify("  A   B  ") == "a-b"
    assert slugify("!!!") == "warroom"
