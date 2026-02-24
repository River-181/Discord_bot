# Bot Lifecycle Runbook

## 목적
봇의 기동, 건강점검, 종료, 업데이트 반영 시 일관된 절차를 고정합니다.

## 기동 체크

1. 저장소 위치 확인
2. 설정 최신성 확인
   - `config/settings.yaml`
   - `.env` (실행용, 로컬 변수 존재만 점검)
3. `bash .Agent/scripts/validate.sh` 실행
4. 실행 방식 판단
   - 우선: launchd
   - 디버그: scripts/botctl.sh daemon

## 재시작

1. `bash scripts/botctl.sh status --launchd`
2. 중복 프로세스 확인
3. 재시작:
   - `bash scripts/botctl.sh stop --launchd`
   - `bash scripts/botctl.sh start --launchd`
4. `/bot_status` 및 이벤트 로그 확인

## 정지

1. `bash scripts/botctl.sh stop --launchd`
2. Voice/Thread 관련 잔류 알림 확인
3. 종료 직후 `bash scripts/botctl.sh status --launchd`

## 업데이트 반영

1. 코드 배포 또는 pull
2. 의존성 필요 시 재설치
3. `bash .Agent/scripts/validate.sh`
4. 봇 재시작 후 핵심 명령(`/meeting_summary`, `/warroom_open`, `/news_run_now`, `/music_panel`) 동작 확인

## 실패 시 기본 대응

- 명령 실패: `ops_events.ndjson`에서 최근 20분 에러 로그 확인
- launchd 미실행: `scripts/botctl.sh status --launchd`와 `manage_launchd.sh` 상태 비교
- 연쇄 실패: `/Users/river/tools/mangsang-orbit-assistant/.Agent/runbooks/incident-response.md`로 이관
