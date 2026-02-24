# Agent Lab Playbook (Developer Control Plane)

`Team.망상궤도`의 Agent Lab은 Discord 사용자 기능이 아니라, 봇 개발/운영을 위한 로컬 제어면입니다.

## 운영 원칙
- Agent 제어는 `CLI + 대시보드`에서만 수행
- Discord 슬래시 명령으로는 Agent 상태를 변경하지 않음
- 데이터 입력은 수동 기록만 허용 (자동 GitHub/CI 연동 없음)

## 역할 모델
- `discord-dev`: 기능 구현/수정
- `bot-tester`: 회귀 테스트/검증
- `ops-analyst`: 로그/지표 분석
- `dashboard-dev`: 대시보드 UX/시각화

## 데이터 파일
- 경로: `data/agent_sessions.jsonl`
- 한 줄당 1개 세션 이벤트(JSON)
- malformed line은 대시보드에서 skip하고 경고 카운트로 표시

## 표준 스키마
- `session_id`: 이벤트 고유 ID(UUID)
- `assignment_id`: 동일 assignment 체인 ID
- `team_run_id`: 팀 미션 런 ID
- `mission`: 미션명
- `agent_name`: `discord-dev|bot-tester|ops-analyst|dashboard-dev`
- `department`: `development|qa|ops|dashboard`
- `task`: 작업 설명
- `status`: `active|completed|idle|error`
- `progress`: 0..100 (`completed`면 100)
- `started_at`: 시작 시각(ISO)
- `updated_at`: 업데이트 시각(ISO)
- `completed_at`: 완료 시각(ISO or null)
- `mode`: `local_teamctl` 또는 `local_dashboard`
- `assigned_by`: 생성자
- `updated_by`: 수정자
- `note`: 선택 메모

## 운영 경로 1: CLI
```bash
cd /Users/river/tools/mangsang-orbit-assistant
python3 tools/dashboard/scripts/agent_teamctl.py create --mission "이벤트 리마인더 고도화" --tasks "payload 정리;예외 테스트;로그 분석;대시보드 경고 배지"
python3 tools/dashboard/scripts/agent_teamctl.py update --agent discord-dev --status active --progress 45 --team-run-id team-20260220-090000-abc123 --note "payload 1차 반영"
python3 tools/dashboard/scripts/agent_teamctl.py status --limit 10
```

## 운영 경로 2: 대시보드 입력 UI
- 위치: Streamlit `연구소 타이쿤` 탭 > `Agent Lab 제어면`
- 기능:
  - `Create`: mission/tasks/assigned_by 입력 후 team run 생성
  - `Update`: team run + agent 선택 후 status/progress 갱신
- 제약:
  - team run 선택 없이 업데이트 불가
  - 선택 run에 해당 agent assignment가 없으면 업데이트 차단

## 권장 운영 루프
1. 미션을 결과 중심으로 1줄 정의
2. tasks를 4~8개로 분할해 병렬 배치
3. 30~60분 단위로 status/progress 갱신
4. 오류 슬롯(`error`) 발생 시 원인/대응을 note에 기록
5. 종료 시 `completed` + `100`으로 명시 종료

## 관측 포인트 (연구소 타이쿤 탭)
- 미션 라인: 활성/완료/오류/대기 슬롯 비율
- 시설 패널: 역할별 현재 작업과 진행률
- 실시간 로그: 최근 완료/진행 이벤트
- 파싱 경고: `agent_sessions.jsonl` 손상 라인 수

## 비범위 (Phase 1)
- GitHub 이벤트 자동 수집
- CI 파이프라인 상태 자동 반영
- 자율 실행형 AI 워커
