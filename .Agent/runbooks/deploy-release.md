# Deploy & Release Runbook

## 배포 전

1. `git status` 깨끗한지 확인
2. `bash .Agent/scripts/validate.sh`
3. 변경 위험도 분류: 설정만, 기능 변경, 스키마 변경 여부
4. 스테이징(가능 시 로컬)에서 기본 명령 스모크 실행

## 배포

1. 코드 반영
2. 의존성 반영(`requirements.txt`) 설치
3. `bash scripts/botctl.sh restart --launchd` 또는 `--daemon`(임시)
4. 핵심 명령 최소 재검증:
   - `/meeting_summary`
   - `/news_run_now`
   - `/warroom_open`
   - `/event_reminder_status`
   - `/music_panel`(설정 시)

## 배포 후

1. 30분 내 자동 오류/응답 추세 확인
2. 대시보드 오버뷰에 이상 징후 없음 확인
3. `release-note` 템플릿으로 변경 로그 작성
