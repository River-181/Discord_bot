from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


class BotScheduler:
    def __init__(self, timezone: str) -> None:
        self.scheduler = AsyncIOScheduler(timezone=timezone)
        self.started = False

    def add_cron_job(self, name: str, cron_expr: str, func: Callable[[], Awaitable[None]]) -> None:
        trigger = CronTrigger.from_crontab(cron_expr)

        async def _runner() -> None:
            try:
                await func()
            except Exception as exc:  # pragma: no cover
                logger.exception("scheduled job failed: %s (%s)", name, exc)

        self.scheduler.add_job(_runner, trigger=trigger, id=name, replace_existing=True)

    def start(self) -> None:
        if not self.started:
            self.scheduler.start()
            self.started = True

    def shutdown(self) -> None:
        if self.started:
            self.scheduler.shutdown(wait=False)
            self.started = False
