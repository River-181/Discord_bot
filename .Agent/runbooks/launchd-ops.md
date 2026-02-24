# launchd 운영 Runbook

## 대상
로컬 머신 상시 구동(권장) 시 적용.

## 기본 경로
- 서비스 이름: `com.mangsang.orbit.assistant`
- 실행 스크립트: `scripts/botctl.sh`

## 표준 동작

1. 상태 확인
   - `./scripts/botctl.sh status --launchd`
2. 시작
   - `./scripts/botctl.sh start --launchd`
3. 로그 확인
   - `tail -n 200 data/logs/launchd.out.log`
   - `tail -n 200 data/logs/launchd.err.log`
4. 실패 시
   - 재시작 후에도 로그 반복 실패면 incident 생성

## PID/중복 방지

- 시작 스크립트는 단일 인스턴스 원칙을 유지합니다.
- 기동 후 동일 채널에 동일 작업이 중복 실행되는지 대시보드 이벤트에서 확인.

## 권장 정기 점검

- 매일 24시간 중 1회:
 - `botctl` 상태
 - `data/logs/launchd.err.log`에 반복 에러 유무
 - `ops_events.ndjson` 최근 200행의 critical 에러 유무
