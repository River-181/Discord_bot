#!/usr/bin/env bash

set -euo pipefail

INCIDENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../incidents && pwd)"
TITLE=""
SEVERITY="medium"
DESCRIPTION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --title)
      TITLE="$2"; shift 2;;
    --severity)
      SEVERITY="$2"; shift 2;;
    --desc|--description)
      DESCRIPTION="$2"; shift 2;;
    -h|--help)
      cat <<'EOF'
Usage:
  new-incident.sh --title "<title>" --severity <low|medium|high> [--description "<text>"]
EOF
      exit 0;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1;;
  esac
done

if [[ -z "$TITLE" ]]; then
  echo "title is required" >&2
  exit 1
fi

mkdir -p "$INCIDENT_DIR"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$INCIDENT_DIR/incident_${TS}.md"

cat > "$OUT" <<EOF
# Incident: ${TITLE}

Severity: ${SEVERITY}
Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Owner: 운영자

## 증상

${DESCRIPTION}

## 조치
- [ ]
- [ ]

## 원인 추정
- 

## 복구 상태
- [ ] 진행 중
- [ ] 완료

EOF

echo "created=$OUT"
