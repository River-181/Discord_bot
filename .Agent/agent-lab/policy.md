# Agent Lab Policy

`Agent Lab`은 Discord 사용자 기능이 아니라 봇 **개발·운영 팀 전용 제어면**입니다.

## 운영 원칙

- Discord slash에서 Agent 관련 명령은 노출하지 않는다.
- Team/세션 기록은 로컬 `data/agent_sessions.jsonl` 중심으로 관리.
- 최종 의사결정은 `.Agent/README.md`와 runbook 기반으로 기록.
- 실험적 변경은 `status` + `progress`를 남긴 뒤 합의 후 반영.

## 권한

- 생성/업데이트는 운영 팀만 수행
- 상태 조회는 팀원 누구나 가능
- 본문/메시지 상세는 최소 보존, 이벤트 메타 중심으로 관리
