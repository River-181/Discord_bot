# Event Reminder Runbook

## 목적
Discord Scheduled Event 시작 5분 전 알림(채널+DM) 자동 발송 신뢰성 확보.

## 운영 규칙

- 기본 스캔 주기: 1분
- 기본 선행시간: 5분
- 채널 메시지: `운영-브리핑`
- 멘션: `@here + 참가자 멘션` 분할 전송

## 장애 대응

- 스캔 미실행: 스케줄러 설정 및 봇 기동 상태 점검
- DM 실패: 채널 알림은 유지, `event_reminder_dm_failed` 누적 관찰
