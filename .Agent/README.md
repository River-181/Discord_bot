# .Agent

`망상궤도 비서` 운영을 위한 워크스페이스 관리 공간입니다.  
코드 구현이 아닌 **운영 체계(운영 매뉴얼, 장애 대응, 변경 이력, 인수인계)**의 정합성을 관리합니다.

## 핵심 위치

- 매니페스트
  - `manifests/manifest.json`
  - `manifests/contacts.json`
- Runbook (운영 대응표준)
  - `runbooks/bot-lifecycle.md`
  - `runbooks/launchd-ops.md`
  - `runbooks/incident-response.md`
  - `runbooks/deploy-release.md`
  - `runbooks/feature-specific/meeting-summary.md`
  - `runbooks/feature-specific/warroom.md`
  - `runbooks/feature-specific/news-radar.md`
  - `runbooks/feature-specific/curation.md`
  - `runbooks/feature-specific/music.md`
  - `runbooks/feature-specific/event-reminder.md`
  - `runbooks/feature-specific/dashboard.md`
- Ops 체크리스트
  - `ops-checklists/daily.md`
  - `ops-checklists/weekly.md`
  - `ops-checklists/pre-deploy.md`
  - `ops-checklists/post-incident.md`
- 지식/규약
  - `knowledge/discord-architecture.md`
  - `knowledge/command-contracts.md`
  - `knowledge/issue-patterns.md`
  - `knowledge/faq.md`
- Agent Team 가이드
  - `agent-lab/policy.md`
  - `agent-lab/session-template.md`
  - `agent-lab/README.md`
  - `agent-lab/commands.md`
- 스크립트
  - `scripts/bootstrap.sh`
  - `scripts/validate.sh`
  - `scripts/new-incident.sh`
- 템플릿
  - `templates/incident-report.md`
  - `templates/release-note.md`
  - `templates/session-brief.md`
- 스냅샷/사고 기록
  - `snapshots/` (git 제외)
  - `incidents/` (git 제외)

## 기본 운영 규칙

1. 운영 판단 근거와 결정은 `.Agent` 문서로 남깁니다.
2. 장애 대응, 스케줄 변경, 롤백은 runbook에 있는 절차만 사용합니다.
3. `.env`, 토큰, 비밀키는 **절대** `.Agent`에 저장하지 않습니다.
4. `manifest.json` 및 `contacts.json`은 운영의 정합성 검증 대상으로 간주합니다.

## 빠른 실행

- 환경 초기화: `bash .Agent/scripts/bootstrap.sh --env local --guild-id <target_guild_id> --target-path /Users/river/tools/mangsang-orbit-assistant`
- 규격 검증: `bash .Agent/scripts/validate.sh`
- 사고 기록 생성: `bash .Agent/scripts/new-incident.sh --title "<사건 제목>" --severity medium`

## 정책 참고

- `target_guild_id`: 1401492009486651452
- 시간대: Asia/Seoul
- 단일 서버 운영을 기준으로 작성
