from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import discord

T = TypeVar("T")


async def retry_discord_call(
    func: Callable[[], Awaitable[T]],
    *,
    attempts: int = 4,
    base_delay: float = 1.0,
) -> T:
    delay = base_delay
    last_exc: Exception | None = None
    for _ in range(attempts):
        try:
            return await func()
        except discord.HTTPException as exc:
            last_exc = exc
            if exc.status not in (429, 500, 502, 503, 504):
                raise
            await asyncio.sleep(delay)
            delay *= 2
    if last_exc:
        raise last_exc
    raise RuntimeError("retry_discord_call failed without exception")
