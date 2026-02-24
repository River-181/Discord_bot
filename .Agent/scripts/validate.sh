#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"

check_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "[missing] $path" >&2
    return 1
  fi
  echo "[ok] $path"
}

check_manifest() {
  local path="$ROOT_DIR/manifests/manifest.json"
  local required=(workspace_name owner target_repo target_guild_id owner_alias critical_paths runbooks agent_roles last_updated_at)
  python3 - "$path" "${required[@]}" <<'PY'
import json, sys
path = sys.argv[1]
required = set(sys.argv[2:])
with open(path, "r", encoding="utf-8") as fp:
  data = json.load(fp)
missing = [k for k in required if k not in data]
if missing:
  print("[invalid] manifest.json missing: " + ", ".join(missing))
  raise SystemExit(1)
print("[ok] manifest.json schema")
PY
}

check_contacts() {
  local path="$ROOT_DIR/manifests/contacts.json"
  python3 - "$path" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fp:
  data = json.load(fp)
assert "owner" in data and data["owner"].get("discord_id"), "owner.discord_id missing"
assert "roles" in data and isinstance(data["roles"], dict), "roles missing"
print("[ok] contacts.json schema")
PY
}

echo "Validate .Agent workspace..."

check_file "$ROOT_DIR/README.md"
check_file "$ROOT_DIR/manifests/manifest.json"
check_file "$ROOT_DIR/manifests/contacts.json"

for file in \
  "$ROOT_DIR/runbooks/bot-lifecycle.md" \
  "$ROOT_DIR/runbooks/launchd-ops.md" \
  "$ROOT_DIR/runbooks/incident-response.md" \
  "$ROOT_DIR/runbooks/deploy-release.md" \
  "$ROOT_DIR/ops-checklists/daily.md" \
  "$ROOT_DIR/ops-checklists/weekly.md" \
  "$ROOT_DIR/ops-checklists/pre-deploy.md" \
  "$ROOT_DIR/ops-checklists/post-incident.md" \
  "$ROOT_DIR/knowledge/discord-architecture.md" \
  "$ROOT_DIR/knowledge/command-contracts.md" \
  "$ROOT_DIR/knowledge/issue-patterns.md" \
  "$ROOT_DIR/knowledge/faq.md" \
  "$ROOT_DIR/agent-lab/policy.md" \
  "$ROOT_DIR/agent-lab/session-template.md" \
  "$ROOT_DIR/agent-lab/README.md" \
  "$ROOT_DIR/agent-lab/commands.md" \
  "$ROOT_DIR/templates/incident-report.md" \
  "$ROOT_DIR/templates/release-note.md" \
  "$ROOT_DIR/templates/session-brief.md" \
  "$ROOT_DIR/scripts/bootstrap.sh" \
  "$ROOT_DIR/scripts/validate.sh" \
  "$ROOT_DIR/scripts/new-incident.sh"; do
  check_file "$file"
done

check_manifest
check_contacts

runbooks=(
  "runbooks/feature-specific/meeting-summary.md"
  "runbooks/feature-specific/warroom.md"
  "runbooks/feature-specific/news-radar.md"
  "runbooks/feature-specific/curation.md"
  "runbooks/feature-specific/music.md"
  "runbooks/feature-specific/event-reminder.md"
  "runbooks/feature-specific/dashboard.md"
)
for file in "${runbooks[@]}"; do
  check_file "$ROOT_DIR/$file"
done

echo "[ok] validate complete"
exit 0
