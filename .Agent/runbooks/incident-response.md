# Incident Response Runbook

## 발생 조건
- 기능 실패가 반복되고 `/봇 반응 없음` 또는 응답 지연이 1회 이상 발생
- launchd 비실행, 알림 반복 실패, 음악/요약/워룸/뉴스 기능 핵심 손실

## 15분 대응 원칙

1. 사고 분류
   - 분류: P1(서비스 중단), P2(부분 장애), P3(일시 오류)
2. 초기 고립
   - 영향 채널: `운영-브리핑`
   - 상태: 진행 중임을 공지
3. 증상 수집
   - 최근 20분 로그( launchd / botlog / ops_events )
   - `/health` 또는 dashboard 오버뷰 캡처
4. 우회 대응
   - 핵심 기능이 죽었을 때 기능별 fallback(수동 정리/수동 알림) 수행
5. 복구
   - 원인 패치 또는 서비스 재기동
6. 사고 종료
   - 조치사항 요약 + 재발방지 항목 작성

## 기록 템플릿

- `bash .Agent/scripts/new-incident.sh --title "..."`
- 분류, 증상, 근본원인, 조치, 사전 예방 항목을 기록

## 사후 점검

- 동일 이슈 재발 방지 체크리스트를 `ops-checklists/post-incident.md`에 등록
- 필요한 경우 runbook 업데이트
