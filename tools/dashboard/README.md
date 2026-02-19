# 망상궤도 비서 운영 대시보드

Phase 1 기준 Discord 운영 현황을 시각화하는 GUI.
Backend: FastAPI, Frontend: Streamlit.

## 구조

- `tools/dashboard/backend/app.py`: API 서버
- `tools/dashboard/backend/dashboard_backend.py`: 실행 엔트리
- `tools/dashboard/backend/services/*`: JSONL/launchd 상태 리더
- `tools/dashboard/frontend/app.py`: Streamlit UI
- `tools/dashboard/frontend/components/*`: 화면 컴포넌트

## 실행

```bash
cd /Users/river/tools/mangsang-orbit-assistant

# 필요 패키지
./.venv/bin/pip install -r requirements.txt

# 백엔드 + 프론트 시작
./tools/dashboard/scripts/start.sh

# 상태
./tools/dashboard/scripts/status.sh

# 종료
./tools/dashboard/scripts/stop.sh
```

기본 포트
- backend: `8080`
- frontend: `8501`

환경변수
- `DASHBOARD_BACKEND_URL` (프론트엔드에서 백엔드 주소 오버라이드)
- `DASHBOARD_BACKEND_PORT`, `DASHBOARD_FRONTEND_PORT` (시작 스크립트)
- `DASHBOARD_PROJECT_ROOT`, `DASHBOARD_DATA_DIR` (테스트/운영 분리)
- `DASHBOARD_RUNTIME_LABEL`

## API

- `GET /api/health`
- `GET /api/overview`
- `GET /api/warrooms?status=all|active|archived&limit=100`
- `GET /api/summaries?scope=all|thread|channel&limit=50`
- `GET /api/decisions?status=all|open|closed&limit=100`
- `GET /api/events?event_type=all|scheduled_inactivity_scan|error|warning&limit=200`
- `GET /api/metrics/quick?hours=24`
- `POST /api/runtime/refresh`

### API 예시

```bash
curl http://127.0.0.1:8080/api/health
curl 'http://127.0.0.1:8080/api/overview'
curl 'http://127.0.0.1:8080/api/warrooms?status=active&limit=50'
curl 'http://127.0.0.1:8080/api/events?event_type=warning&limit=50'
curl 'http://127.0.0.1:8080/api/metrics/quick?hours=24'
```

## 사용자 점검 체크리스트

1. 운영중 상태 확인
   - `/api/health`의 `runtime_state.state`, `jsonl_ok`
2. 워룸 상태 확인
   - `/api/overview`, `/api/warrooms`
3. 요약/결정 추적
   - `/api/summaries`, `/api/decisions`
4. 이벤트/에러 추적
   - `/api/events`, `/api/metrics/quick`

## 고장 대응

- 대시보드가 200은 나지만 화면 데이터가 비어 있으면
  - `/api/health`의 `data_missing`/`missing_files` 확인
  - 누락 파일을 확인하고 다시 시작
- JSON 파싱 오류
  - `corrupt_lines`가 0보다 크면 해당 JSONL 라인 정리
- 런타임 비정상
  - `runtime_state.state`가 `running`이 아니면 봇/launchd 상태 확인
- 응답이 느려지면
  - 파일 크기가 큰 경우 `limit` 값을 낮춰 확인
