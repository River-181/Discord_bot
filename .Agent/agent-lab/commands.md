# Agent Lab CLI Guide

## Create

```bash
python3 tools/dashboard/scripts/agent_teamctl.py create --mission "..." --tasks "task1;task2" --assigned-by "<id or name>"
```

## Update

```bash
python3 tools/dashboard/scripts/agent_teamctl.py update \
  --agent discord-dev \
  --status active \
  --progress 40 \
  --note "..." \
  --team-run-id team-...
```

## Status

```bash
python3 tools/dashboard/scripts/agent_teamctl.py status --limit 10
```
