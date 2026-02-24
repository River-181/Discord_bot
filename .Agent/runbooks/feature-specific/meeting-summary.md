# Meeting Summary Feature Runbook

## 핵심 목적
회의/채널 내용을 누락 없이 요약하고 `결정-log`로 의사결정을 이관한다.

## 핵심 트러블슈팅

- "요약할 메시지가 없습니다"
  - 실행 채널이 잘못되었는지 확인
  - `window_minutes` 증가
  - 스레드 메시지인지 `scope:thread`로 실행
- 명령 캐시 반응 지연
  - 봇 재시작 후 재시도
  - `ops_events`에서 `meeting_summary_invoked` 확인

## 운영 규칙

- 기본은 채널 240분 요약
- 결정 로그 저장 시 `publish_to_decision_log=True` 권고
