# Dashboard Runbook

## 목적
봇 상태/워룸/요약/이벤트를 운영자가 빠르게 판단하도록 시각화 유지.

## 점검 항목

- `/api/health` 정상 응답
- `data_dir_exists`, `jsonl_ok` 정상
- runtime 상태 `running`인지
- 워룸 active/archived 합계 정합성
- 최근 이벤트 경보 카운트

## 정합성 위반

- JSONL 누락: 대시보드는 빈 배열 반환 + 경고 플래그로 처리
- API 타임아웃: 백엔드 캐시 TTL/쿼리 제한 점검
