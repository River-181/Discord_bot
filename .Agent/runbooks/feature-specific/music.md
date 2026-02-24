# Music Feature Runbook

## 운영 목적
음성 채널 내 공유 음악 플레이어를 저소음으로 제공하되 핵심 제어를 유지.

## 기본 제약

- 동일 음성 채널 제약 유지
- 허용 사용자는 DM/서버 정책 + allowlist 정책을 따른다
- 오류(`OpusNotLoaded`)가 발생하면 즉시 재시작 후 플래그 확인

## 표준 동작

1. `/music_join` (필요 시)
2. `/music_play <query-or-url>`
3. `/music_panel`(필요 시)로 공개 재생 상태 동기화
4. `/music_stop` 종료

## 실패 대응

- Opus 관련 실패: `PyNaCl`, FFmpeg, Discord 연결 상태 점검
- 재생 대기 실패: `/music_queue`로 상태 확인 후 큐 정리
