# Warroom Feature Runbook

## 운영 규칙

- 프로젝트 단위로 텍스트+음성 채널을 1세트 생성
- 비활성 임계 이벤트:
  - 14일: 경고
  - 30일: 자동 아카이브

## 생성/종료

- 생성: `/warroom_open name:<name> zone:core ttl_days:<n>`
- 종료: `/warroom_close name:<name> reason:<reason>`

## 점검

- `/warroom_list status:active`에서 누수 워룸 확인
- 종료 시 `결정-log`와 `knowledge-base`에 요약 잔류 여부 확인
