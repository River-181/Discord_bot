# Team.망상궤도 내부 지식 문서
## Discord 세팅 + AI + 봇 운영 통합 매뉴얼 (2026-02-25 반영)

문서 버전: v1.1  
작성 기준일: 2026-02-25  
적용 대상: Team.망상궤도 Discord 서버 운영자/개발자/PM  
표준 시간대: Asia/Seoul

---

## 작성 1차 (초안)

### 1) 목적
이 문서는 Discord 앱/봇 설정, 서버 채널 운영, AI 요약 자동화, 워룸 라이프사이클, 장애 대응을 단일 문서로 통합해 팀 운영 표준을 고정한다.

### 2) 현재 시스템 한 줄 요약
- 봇 이름: `망상궤도 비서`
- 실행 모델: `Gemini 2.0 Flash + fallback`
- 운영 방식: `launchd` 상시 실행
- 데이터 원본: Discord 메시지
- 보조 저장: JSONL (`summaries`, `decisions`, `warrooms`, `ops_events`)

### 3) 핵심 명령
- `/meeting_summary`
- `/meeting_summary_v2` (캐시 우회용, 2026-02-25 제거 예정)
- `/decision_add`
- `/warroom_open`, `/warroom_close`, `/warroom_list`
- `/bot_status`

### 4) 핵심 위험
- 디스코드 명령 캐시 충돌 (`더는 사용되지 않는 명령어입니다`)
- 잘못된 채널에서 요약 실행 시 메시지 0건 오해
- 봇 프로세스 중복/중지 시 응답 실패

---

## 검토 1차

### 보완 필요 항목
1. 디스코드 개발자 포털 페이지별 설정값을 메뉴 단위로 명확히 써야 한다.
2. “이미지 첨부 위치”를 번호별로 고정해야 인수인계가 가능하다.
3. 운영 실행 명령, 점검 명령, 장애 복구 절차를 복붙 가능한 형태로 제공해야 한다.
4. D+7 명령 제거 절차(2026-02-25)를 날짜 기준으로 문서화해야 한다.
5. 보안 주의사항(토큰/키 회전)을 반드시 포함해야 한다.

---

## 작성 2차 (개정 완성본)

## A. 운영 원칙

### A-1. 범위
- 이 문서는 Discord 개발자 포털 설정, 서버 채널 운영, 봇 실행/점검, 요약/결정/워룸 자동화, 장애 대응을 다룬다.
- UI 디자인 변경이나 기능 확장은 이 문서 범위 밖이다.

### A-2. 표준 실행 모드
- 운영 표준은 `launchd` 단일 모드다.
- `manage_bot.sh`는 수동 디버그용이다.
- 운영 명령은 `botctl.sh`를 우선 사용한다.

### A-3. 운영 목표
- 명령 응답 실패 체감 최소화
- 회의/결정 기록 누락 방지
- 워룸 생성/종료 자동화
- 중복 실행/캐시 충돌 재발 방지

---

## B. Discord 개발자 포털 설정 표준

### B-1. General Information
- App Name: `망상궤도 비서`
- Description: 팀 운영 자동화(회의 요약/결정 로그/워룸 관리) 목적 문구 입력
- Tags: `automation`, `summarization`, `operations`, `productivity`, `discord-bot`

이미지 삽입:
- [첨부 이미지 01] General Information 화면

### B-2. Installation
- Installation Contexts:
- `Guild Install` ON
- `User Install` OFF (내부 서버 전용 운영 권장)
- Default Install Settings / Guild Install / Scopes:
- `bot`
- `applications.commands`

이미지 삽입:
- [첨부 이미지 02] Installation 화면

### B-3. OAuth2
- Public Client: OFF
- Redirect URI: 현재 미사용 시 비워둠
- URL Generator 스코프:
- `bot`
- `applications.commands`

이미지 삽입:
- [첨부 이미지 03] OAuth2 화면

### B-4. Bot
- Public Bot: 내부 운영이면 OFF 권장
- Requires OAuth2 Code Grant: OFF
- Privileged Gateway Intents:
- `Message Content Intent` ON (필수)
- `Server Members Intent` ON (권장)
- `Presence Intent` OFF (현재 코드 미사용)

이미지 삽입:
- [첨부 이미지 04] Bot 화면

### B-5. Webhooks
- Endpoint URL 미설정 (현재 구조에서 미사용)
- Events OFF 유지

이미지 삽입:
- [첨부 이미지 05] Webhooks 화면

### B-6. App Verification
- 100개 서버 미만 운영 중에는 즉시 필수 아님
- 확장 대비: Terms/Privacy URL 준비

이미지 삽입:
- [첨부 이미지 06] App Verification 화면

### B-7. Discord Social SDK / Activities
- 현 운영에서 미사용
- `Getting Started`, `Activity Settings`, `URL Mappings`, `Art Assets`는 설정하지 않음

이미지 삽입:
- [첨부 이미지 07] Social SDK Getting Started
- [첨부 이미지 08] Activity Settings
- [첨부 이미지 09] Activity URL Mappings
- [첨부 이미지 10] Activity Assets

---

## C. 서버 채널/카테고리 운영 기준

### C-1. 핵심 카테고리 (현재 합의안)
- `---------00-온보딩---------`
- `---------01-코어-----------`
- `---------02-제품-----------`
- `---------03-성장-----------`
- `---------04-지식-----------`
- `---------05-커뮤니티-------`
- `---------06-음성채널-------`

### C-2. 봇 기록 핵심 채널
- 회의 원본 기본 채널: `회의`
- 결정/요약/자동화 기록 채널: `망상궤도-비서-공간`
- 운영 브리핑 채널: `운영-브리핑`
- 자동화 로그 채널: `망상궤도-비서-공간`

### C-3. 워룸 카테고리 매핑
- 텍스트 카테고리:
- core -> `------🧱-01-코어--------`
- product -> `------🧩-02-제품--------`
- growth -> `------🚀-03-성장--------`
- 음성 카테고리: `------🔊-06-음성채널-----`
- 종료 후 이동: `----------아카이브----------`

---

## D. 봇 아키텍처 및 데이터 흐름

### D-1. 소스 경로
- 루트: `/Users/river/tools/mangsang-orbit-assistant`
- 주요 파일:
- `/Users/river/tools/mangsang-orbit-assistant/bot/app.py`
- `/Users/river/tools/mangsang-orbit-assistant/bot/commands/meeting.py`
- `/Users/river/tools/mangsang-orbit-assistant/bot/commands/warroom.py`
- `/Users/river/tools/mangsang-orbit-assistant/bot/commands/status.py`
- `/Users/river/tools/mangsang-orbit-assistant/config/settings.yaml`

### D-2. 데이터 저장 파일
- `/Users/river/tools/mangsang-orbit-assistant/data/summaries.jsonl`
- `/Users/river/tools/mangsang-orbit-assistant/data/decisions.jsonl`
- `/Users/river/tools/mangsang-orbit-assistant/data/warrooms.jsonl`
- `/Users/river/tools/mangsang-orbit-assistant/data/ops_events.ndjson`
- `/Users/river/tools/mangsang-orbit-assistant/data/snapshots/`

### D-3. 이벤트 기반 자동 동작
- `on_message`:
- 워룸 활동 시간 갱신
- 스레드 전환 권고
- Deep Work 멘션 가드
- 슬래시 명령:
- 회의 요약/결정 추출
- 워룸 생성/종료/목록 조회
- 스케줄러:
- 비활성 워룸 스캔
- 일일 백업

---

## E. 명령어 운영 가이드

### E-1. 회의 요약
- 표준: `/meeting_summary`
- 임시 우회: `/meeting_summary_v2` (2026-02-25 제거 예정)

#### 파라미터
- `scope`: `channel` 또는 `thread`
- `window_minutes`: 5~720
- `publish_to_decision_log`: `True` 또는 `False`
- `source_channel`: `scope=channel`일 때만 사용

#### 실행 예시
```bash
/meeting_summary_v2 scope:channel window_minutes:240 publish_to_decision_log:false source_channel:#회의
```

#### 중요 규칙
- `scope=thread`일 때 `source_channel`를 넣으면 오류다.
- 채널 잘못 선택 시 자동으로 `meeting_source(회의)` 폴백을 시도한다.

### E-2. 워룸 생성/종료
- 생성:
```bash
/warroom_open name:충남지원사업 zone:product ttl_days:7
```
- 종료:
```bash
/warroom_close name:충남지원사업 reason:1차 제출 완료
```
- 조회:
```bash
/warroom_list status:active
```

#### 종료 동작
- 채널 삭제가 아니라 아카이브 이동
- 이름에 `arch-` 접두
- 종료 요약이 기록 채널로 전송

### E-3. 상태 점검
- 디스코드:
```bash
/bot_status
```
- 현재 출력에 포함:
- `process_mode`
- `guild_command_count`
- `has_meeting_summary`
- `has_meeting_summary_v2`
- `meeting_options_equal`

---

## F. 실행/운영 명령어 표준

### F-1. 표준 운영(launchd)
```bash
cd /Users/river/tools/mangsang-orbit-assistant
./scripts/botctl.sh start --launchd
./scripts/botctl.sh status --launchd
./scripts/botctl.sh logs --launchd
./scripts/botctl.sh stop --launchd
```

### F-2. 명령 동기화 검증
```bash
cd /Users/river/tools/mangsang-orbit-assistant
.venv/bin/python scripts/sync_probe.py
```

통과 기준:
- `guild_command_count = 16`
- `global_command_count = 0`
- `meeting_options_equal = True`
- `sync-probe ok phase=migration`

### F-3. D+7 이후 검증(2026-02-25)
```bash
cd /Users/river/tools/mangsang-orbit-assistant
.venv/bin/python scripts/sync_probe.py --phase post-migration
```

---

## G. 캐시/응답 문제 대응 매뉴얼

### G-1. 증상: 더는 사용되지 않는 명령어입니다
원인:
- 디스코드 슬래시 명령 캐시 불일치

대응:
1. `/meeting_summary_v2`로 즉시 우회
2. `sync_probe.py` 실행으로 명령 등록 상태 점검
3. Discord 클라이언트 새로고침 (`Ctrl/Cmd + R`)

### G-2. 증상: 애플리케이션이 응답하지 않았어요
원인:
- 봇 비가동 또는 중복 인스턴스 충돌

대응:
1. `./scripts/botctl.sh status --launchd`
2. 필요 시 `launchctl kickstart -k gui/$(id -u)/com.mangsang.orbit.assistant`
3. 중복 프로세스 확인 및 정리

### G-3. 증상: 요약할 메시지가 없습니다
원인:
- 잘못된 채널에서 실행
- 텍스트 없이 첨부만 있는 메시지
- Message Content Intent/권한 이슈

대응:
1. `source_channel:#회의`로 재실행
2. `scope`와 채널 타입 확인
3. 봇 권한/intent 확인

### G-4. 증상: 음악 패널 버튼에서 `상호작용 실패`
원인:
- 구버전 패널 메시지의 컴포넌트가 남아 있거나 재시작 직후 stale 상태

대응:
1. `/music panel` 실행으로 패널 재게시
2. 동일 현상 반복 시 `./scripts/botctl.sh restart` 후 재확인
3. 채널에 구 패널 메시지가 여러 개면 최신 1개만 남기고 정리

### G-5. 증상: 음성 채널에서 음악이 들리지 않음
원인:
- 채널 권한 부족 (`connect`/`speak`)
- Stage 채널에서 봇이 청중(suppressed) 상태
- Opus/FFmpeg 경로 누락

대응:
1. 대상 음성 채널에서 봇 권한 `연결(connect)`/`말하기(speak)` 확인
2. Stage 채널이면 봇 발언 허용(unsuppress) 적용
3. 환경값 확인: `OPUS_LIBRARY_PATH`, `FFMPEG_PATH`
4. 봇 재기동 후 재테스트 (`/music join` -> `/music play`)

### G-6. 뉴스 레이다 정기 발행 시간
- 아침 발행: `매일 08:00` (`news_digest_morning_cron = "0 8 * * *"`)
- 저녁 발행: `평일 18:00` (`news_digest_evening_cron = "0 18 * * 1-5"`)

---

## H. 보안/컴플라이언스

### H-1. 비밀정보 관리
- 토큰/API 키는 `.env`로만 관리
- 문서/채널/스크린샷에 키를 노출하지 않는다
- 노출 이력 있으면 즉시 회전:
- Discord Bot Token Reset
- Gemini/OpenAI 키 재발급

### H-2. 앱 검증 대비
- Terms of Service URL
- Privacy Policy URL
- 팀 2FA/이메일 인증 상태 점검

---

## I. 마이그레이션 일정 (고정)

- D0: 2026-02-18
- `/meeting_summary` + `/meeting_summary_v2` 병행 운영
- D1: 2026-02-19
- 장애 문의 추세 점검
- D3: 2026-02-21
- 중간 운영 리뷰
- D7: 2026-02-25
- `/meeting_summary_v2` 제거
- `/meeting_summary` 단일화

상세 실행 문서:
- `/Users/river/tools/mangsang-orbit-assistant/docs/command-migration-runbook-2026-02-18.md`

---

## J. 첨부 이미지 삽입 지시서

아래 순서대로 본 문서 해당 섹션에 이미지 삽입:
- 첨부 이미지 01 -> `B-1 General Information`
- 첨부 이미지 02 -> `B-2 Installation`
- 첨부 이미지 03 -> `B-3 OAuth2`
- 첨부 이미지 04 -> `B-4 Bot`
- 첨부 이미지 05 -> `B-5 Webhooks`
- 첨부 이미지 06 -> `B-6 App Verification`
- 첨부 이미지 07 -> `B-7 Social SDK`
- 첨부 이미지 08 -> `B-7 Activity Settings`
- 첨부 이미지 09 -> `B-7 Activity URL Mappings`
- 첨부 이미지 10 -> `B-7 Activity Assets`

운영 증빙 이미지(옵션):
- 명령 캐시 오류 화면
- `/meeting_summary_v2` 성공 요약 화면
- `/warroom_open` 성공 화면

---

## 검토 2차 (출고 점검)

### 점검 항목
1. 코드/설정 사실값과 문서 값이 일치하는가
2. 운영자가 복붙으로 실행 가능한가
3. 장애 대응 절차가 증상 기준으로 충분한가
4. D+7 제거 절차가 날짜/명령 포함으로 완결인가
5. 첨부 이미지 삽입 위치가 명확한가

### 점검 결과
- 1 통과: 설정/명령/채널/스크립트 경로 반영 완료
- 2 통과: 실행/검증 명령 블록 제공
- 3 통과: 3대 증상 대응 루틴 포함
- 4 통과: 2026-02-25 제거 절차 명시
- 5 통과: 이미지 01~10 매핑 완료

최종 상태: 배포 가능
