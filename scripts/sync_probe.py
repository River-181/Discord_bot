from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import certifi
import httpx
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from bot.config import load_settings


def parse_phase(argv: list[str]) -> str:
    phase = "migration"
    if len(argv) >= 3 and argv[1] == "--phase":
        phase = argv[2].strip().lower()
    if phase not in {"migration", "post-migration"}:
        raise ValueError("phase must be one of: migration, post-migration")
    return phase


async def main() -> int:
    try:
        phase = parse_phase(sys.argv)
    except ValueError as exc:
        print(str(exc))
        print("usage: .venv/bin/python scripts/sync_probe.py [--phase migration|post-migration]")
        return 2

    settings = load_settings(ROOT_DIR)
    load_dotenv(ROOT_DIR / ".env")
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("DISCORD_BOT_TOKEN missing")
        return 2
    if not settings.target_guild_id:
        print("target_guild_id missing in settings.yaml")
        return 2

    headers = {"Authorization": f"Bot {token}"}
    timeout = httpx.Timeout(20.0, connect=10.0)
    verify_path = certifi.where()
    async with httpx.AsyncClient(timeout=timeout, verify=verify_path, headers=headers) as client:
        app_resp = await client.get("https://discord.com/api/v10/oauth2/applications/@me")
        if app_resp.status_code != 200:
            print("app_lookup_failed", app_resp.status_code, app_resp.text)
            return 1
        app_id = str(app_resp.json().get("id", ""))
        if not app_id:
            print("app_id missing")
            return 1

        guild_resp = await client.get(
            f"https://discord.com/api/v10/applications/{app_id}/guilds/{settings.target_guild_id}/commands"
        )
        global_resp = await client.get(f"https://discord.com/api/v10/applications/{app_id}/commands")
        if guild_resp.status_code != 200:
            print("guild_command_lookup_failed", guild_resp.status_code, guild_resp.text)
            return 1
        if global_resp.status_code != 200:
            print("global_command_lookup_failed", global_resp.status_code, global_resp.text)
            return 1

        guild_commands = guild_resp.json()
        global_commands = global_resp.json()
        guild_names = sorted(command.get("name", "") for command in guild_commands)
        global_names = sorted(command.get("name", "") for command in global_commands)

        print("app_id", app_id)
        print("guild_id", settings.target_guild_id)
        print("guild_command_count", len(guild_commands))
        print("guild_commands", ",".join(guild_names))
        print("global_command_count", len(global_commands))
        if global_names:
            print("global_commands", ",".join(global_names))

        def option_names(command_name: str) -> list[str]:
            for command in guild_commands:
                if command.get("name") == command_name:
                    return sorted(option.get("name", "") for option in command.get("options", []))
            return []

        v1_opts = option_names("meeting_summary")
        v2_opts = option_names("meeting_summary_v2")
        meeting_options_equal = bool(v1_opts and v2_opts and v1_opts == v2_opts)
        print("meeting_summary_opts", ",".join(v1_opts))
        print("meeting_summary_v2_opts", ",".join(v2_opts))
        print("meeting_options_equal", meeting_options_equal)

        has_meeting = "meeting_summary" in guild_names
        has_meeting_v2 = "meeting_summary_v2" in guild_names

        if global_commands:
            print("sync-probe failed global commands should be empty in guild mode")
            return 1
        if not has_meeting:
            print("sync-probe failed meeting_summary missing")
            return 1
        if phase == "migration":
            if not has_meeting_v2:
                print("sync-probe failed meeting_summary_v2 missing")
                return 1
            if not meeting_options_equal:
                print("sync-probe failed meeting_summary and meeting_summary_v2 options mismatch")
                return 1
        else:
            if has_meeting_v2:
                print("sync-probe failed meeting_summary_v2 should be removed in post-migration phase")
                return 1

    print("sync-probe ok", f"phase={phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
