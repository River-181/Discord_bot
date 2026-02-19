# Discord Command Migration Runbook (2026-02-18)

## Scope
- Guild: `Team.망상궤도` (`1401492009486651452`)
- Canonical command: `/meeting_summary`
- Temporary command: `/meeting_summary_v2`
- Deprecation window: `2026-02-18` to `2026-02-24`
- Removal date: `2026-02-25`

## Day 0 Checklist (2026-02-18)
1. Ensure launchd mode is running.
```bash
cd /Users/river/tools/mangsang-orbit-assistant
./scripts/botctl.sh status --launchd
```
2. Verify command sync and option parity.
```bash
.venv/bin/python scripts/sync_probe.py
```
3. Confirm output:
- `guild_command_count = 7`
- `global_command_count = 0`
- `meeting_options_equal = True`
4. Post operator notice:
- Cache error workaround: use `/meeting_summary_v2`.

## Daily Checks (D1, D3)
1. Run probe.
```bash
cd /Users/river/tools/mangsang-orbit-assistant
.venv/bin/python scripts/sync_probe.py
```
2. Review status command in Discord:
- `/bot_status`
3. Review ops events:
- `command_sync_completed`
- `meeting_summary_invoked`
- `meeting_summary_no_messages`
- `meeting_summary_fallback_to_meeting_source`

## D+7 Removal Steps (2026-02-25)
1. Remove `/meeting_summary_v2` registration in `bot/commands/meeting.py`.
2. Restart bot and resync commands.
```bash
cd /Users/river/tools/mangsang-orbit-assistant
launchctl kickstart -k gui/$(id -u)/com.mangsang.orbit.assistant
.venv/bin/python scripts/sync_probe.py --phase post-migration
```
3. Confirm output:
- `guild_command_count = 6`
- `/meeting_summary_v2` not in command list
- `/meeting_summary` works end-to-end
4. Post final migration notice in `망상궤도-비서-공간`.

## Incident Handling
- If user sees `더는 사용되지 않는 명령어`:
1. Ask user to run `/meeting_summary_v2`.
2. Run sync probe.
3. Ask user to refresh Discord client (`Ctrl/Cmd + R`).
- If user sees `애플리케이션이 응답하지 않았어요`:
1. Check launchd status.
2. Check duplicated `bot.app` process.
3. Restart via launchd kickstart.
