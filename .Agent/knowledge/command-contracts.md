# Command Contracts

## Discord Slash Commands

회사의 운영 채널에서 사용되는 명령은 아래 범주를 기준으로 관리:

- 회의/결정: `meeting_summary`, `warroom_*`, `decision_add`, `bot_status`
- 큐레이션: `curation_*`, 인박스 버튼(승인/반려)
- 뉴스: `news_run_now`, `news_config`
- 음악: `music_*`, `music_panel`
- 이벤트 알림: `event_reminder_status`, `event_reminder_config`
- DM: 지원 쿼리(`요약`, `help`, `status` 등)

## 변경 원칙

1. 사용자 관점 문구 변경 시 runbook 동시 갱신
2. 권한 스코프 변경 시 `contacts.json` 및 문서 교체
3. 비상 fallback 동작은 `incident-response`와 연동
