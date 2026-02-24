# Issue Pattern Knowledge

## 자주 발생 패턴

- Opus 라이브러리 이슈(음악 재생 실패)
- 명령 캐시 불일치(슬래시 명령 반응 없음)
- launchd 비기동
- curation 결과 포맷 품질 저하(요약/태그 누락)
- 이벤트 알림 중복

## 우선 대응

- 증상 기준으로 먼저 로그, 다음 명령 상태, 마지막으로 구성 파일 점검
- 반복 패턴은 `incident-response`로 즉시 분기
