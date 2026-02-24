# News Radar Feature Runbook

## 운영 목적
정책/시장/아이디어 신호를 정해진 채널에 압축 전달.

## 채널 정책

- 기본 채널: `🛰️-뉴스-레이다`
- 로그 채널: `망상궤도-비서-공간`
- 스케줄: 평일 09:00 / 18:00

## 장애 대응

- RSS 수집 실패: 스케줄은 유지, 수동 `/news_run_now hours:12`로 점검
- 반복 실패 시 `ops_events`에 `news_fetch_error` 증가 확인
