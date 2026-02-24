#!/usr/bin/env bash

set -euo pipefail

show_help() {
  cat <<'EOF'
Usage:
  bootstrap.sh --env local|prod --guild-id <guild_id> --target-path <project_path>

Description:
  Initialize workspace helpers and validate baseline contracts for .Agent.
EOF
}

ENV="local"
TARGET_PATH=""
GUILD_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      ENV="$2"; shift 2;;
    --target-path)
      TARGET_PATH="$2"; shift 2;;
    --guild-id)
      GUILD_ID="$2"; shift 2;;
    -h|--help)
      show_help; exit 0;;
    *)
      echo "Unknown arg: $1" >&2
      show_help
      exit 1;;
  esac
done

if [[ -z "$TARGET_PATH" || -z "$GUILD_ID" ]]; then
  echo "target-path and guild-id are required." >&2
  show_help
  exit 1
fi

if [[ ! -d "$TARGET_PATH" ]]; then
  echo "Target path not found: $TARGET_PATH" >&2
  exit 1
fi

cd "$TARGET_PATH"
touch .Agent/.initialized
echo "initialized_at=$(date +%Y-%m-%dT%H:%M:%S%:z)" > .Agent/bootstrap.env
echo "env=$ENV" >> .Agent/bootstrap.env
echo "target_guild_id=$GUILD_ID" >> .Agent/bootstrap.env

echo "Bootstrap completed at $(date)"
echo "target_path=$TARGET_PATH"
echo "target_guild_id=$GUILD_ID"
echo "Next: bash .Agent/scripts/validate.sh"
