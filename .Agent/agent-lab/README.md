# Agent Lab

`agent_teamctl.py`를 통해 에이전트 미션/업무 배정을 관리한다.  
Discord 채팅 명령은 운영 전용이 아니므로 사용하지 않는다.

## 사용 경로

- CLI: `tools/dashboard/scripts/agent_teamctl.py`
- Dashboard UI: `tools/dashboard/frontend/components/agent_lab.py` (읽기/조작 탭)
- 데이터: `data/agent_sessions.jsonl`

## 표준 흐름

1. 미션 생성: `create`
2. 작업 상태 갱신: `update`
3. 진행 상황 확인: `status`

## 규칙

- 동일 assignment는 append-only
- 마지막 행이 최신 상태로 간주
- 100% 진행은 `completed` 전환 시 강제 고정
