from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import certifi
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from bot.app import MangsangBot


async def main() -> int:
    load_dotenv(ROOT_DIR / '.env')
    os.environ.setdefault('SSL_CERT_FILE', certifi.where())

    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        print('DISCORD_BOT_TOKEN missing')
        return 2

    bot = MangsangBot(ROOT_DIR)
    ready = asyncio.Event()

    @bot.event
    async def on_ready() -> None:
        print("on_ready reached")
        if not bot.command_guild:
            print('TARGET_GUILD_ID missing')
            ready.set()
            return
        try:
            cmds = await bot.tree.fetch_commands(guild=bot.command_guild)
            print('command_count', len(cmds))
            print('commands', ','.join(sorted(c.name for c in cmds)))
        except Exception as exc:
            print(f'fetch_error={exc!r}')
        ready.set()

    task = asyncio.create_task(bot.start(token))
    try:
        await asyncio.wait_for(ready.wait(), timeout=25)
    except TimeoutError:
        print('ready timeout')
        await bot.close()
        results = await asyncio.gather(task, return_exceptions=True)
        if results and isinstance(results[0], Exception):
            print(f"task_error={results[0]!r}")
        return 1

    await bot.close()
    results = await asyncio.gather(task, return_exceptions=True)
    if results and isinstance(results[0], Exception):
        print(f"task_error={results[0]!r}")
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
