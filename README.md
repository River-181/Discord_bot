# Mangsang Orbit Assistant

Discord 운영 자동화를 위한 `discord.py` 기반 팀 비서 봇입니다.  
회의 요약, 워룸 라이프사이클, 뉴스 레이다, DM 비서, 음악 재생, 큐레이션 자동등록 기능을 하나의 봇으로 통합합니다.
개발/운영용 Agent Lab은 봇 기능이 아니라 로컬 대시보드 레이어로 분리되어 동작합니다.

## Overview
- Runtime: Python 3.13 / `discord.py` 2.x
- Timezone: `Asia/Seoul`
- AI: Gemini (`GEMINI_API_KEY`) + 룰 기반 fallback
- Storage: JSONL (`data/*.jsonl`) + daily snapshot
- Deploy: `launchd` 권장 (`scripts/botctl.sh`)

## Core Features
- 회의 요약: `/meeting_summary`, `/decision_add`
- 워룸 자동화: `/warroom_open`, `/warroom_close`, `/warroom_list`
- 뉴스 레이다: `/news_run_now`, `/news_config`
- 큐레이션 자동등록: `/curation_status`, `/curation_config`, `/curation_publish`, `/curation_reject`
- 이벤트 리마인더: `/event_reminder_status`, `/event_reminder_config`
- DM 하이브리드 비서: `도움말`, `상태`, `워룸`, `뉴스`, `요약 <텍스트>`
- 음악 기능(MUSIC-1): `/music` 그룹 11종 서브명령
- 운영 점검: `/bot_status`

## Curation (CURATION-1)
정책 고정값:
- 입력 경로: DM + 인박스 채널
- 게시 정책: approve 모드(운영자 승인 후 게시)
- 분류 방식: 규칙 + Gemini 보조(신뢰도 낮을 때만)
- 승인 권한: `Manage Guild` 또는 `Administrator`
- 중복 처리: 기존 게시 스레드 병합

기본 인프라(자동 생성):
- 카테고리: `------🗂️-07-큐레이션-----`
- 채널: `📥-큐레이션-인박스`, `🔗-큐레이션-링크`, `💡-큐레이션-아이디어`, `🎵-큐레이션-뮤직`, `📺-큐레이션-유튜브`, `🖼️-큐레이션-사진`
- 역할: `@product`, `@growth`, `@knowledge`

동작:
- 유저가 DM 또는 인박스 채널에 링크/아이디어/음악/유튜브/사진 제보
- 봇이 제목/요약/태그/타입을 정규화하여 승인 대기 카드 생성
- 운영자가 카드 버튼(`승인/반려/채널변경/태그수정`)으로 처리
- 승인 시 대상 채널 게시 + 작성자 멘션 + 원문 링크 + 역할 멘션

## Agent Lab (개발/운영 대시보드 전용)
목표:
- Discord 봇 개발 워크플로우를 병렬 팀 형태로 추적
- Streamlit `연구소 타이쿤` 탭에서 미션/진행률/병목을 시각화
- 봇 슬래시 명령에 개발용 오케스트레이션을 섞지 않음
- Agent 제어는 Discord 명령이 아니라 `CLI + 대시보드 입력 UI`에서만 수행

역할:
- `discord-dev` (development)
- `bot-tester` (qa)
- `ops-analyst` (ops)
- `dashboard-dev` (dashboard)

로컬 운영 명령:
```bash
cd /Users/river/tools/mangsang-orbit-assistant
python3 tools/dashboard/scripts/agent_teamctl.py create --mission "이벤트 리마인더 개선" --tasks "payload 정리;예외 테스트;로그 분석;랩 UI 수정"
python3 tools/dashboard/scripts/agent_teamctl.py update --agent discord-dev --status active --progress 45 --note "payload 1차 반영"
python3 tools/dashboard/scripts/agent_teamctl.py status
```

대시보드 입력 경로:
- `연구소 타이쿤` 탭 > `Agent Lab 제어면`
- `Create`: mission/tasks 기반 팀 런 생성
- `Update`: team run + agent 선택 후 status/progress 갱신

데이터 계약:
- 파일: `data/agent_sessions.jsonl`
- 주요 필드: `session_id`, `assignment_id`, `team_run_id`, `mission`, `agent_name`, `task`, `status`, `progress`, `started_at`, `updated_at`, `completed_at`, `mode`, `assigned_by/updated_by`, `note`

## Music (MUSIC-1)
정책 고정값:
- 음원 정책: `hybrid`
- 제어 권한: `봇과 같은 음성 채널 사용자만`
- 알림 정책: `low_noise` (ephemeral 중심)
- 길이 제한: 기본 `180분` (`music.max_track_minutes`)
- 패널 갱신: `edit_last` + persistent view(재시작 후 기존 버튼 유지)

지원 명령:
- `/music join channel:#voice(optional)`
- `/music play query_or_url:str`
- `/music pause`
- `/music resume`
- `/music skip`
- `/music panel`
- `/music queue page:int`
- `/music volume percent:int(optional)`
- `/music now`
- `/music stop`
- `/music leave`

소스 정책:
- 일반 사용자: 직접 URL(`http/https`)만 허용
- allowlist 사용자: YouTube URL/검색어 허용(`yt-dlp`)

패널 UI:
- 임베드 섹션: `현재 재생`, `다음 큐`, `세션(상태/음량/채널)`
- 상태 기반 버튼: `일시정지/재개`, `스킵`, `정지`, `나가기`, `-10%`, `+10%`, `큐 보기`, `새로고침`
- 재생 컨텍스트가 없을 때 일부 버튼이 자동 비활성화됨

## Scheduler Defaults
`config/settings.yaml` 기본/권장 스케줄:
- `news_digest_morning_cron`: `0 8 * * *` (매일 08:00)
- `news_digest_evening_cron`: `0 18 * * 1-5` (평일 18:00)
- `music_housekeeping_cron`: `*/5 * * * *`

## Music Playback Architectures
이 저장소는 현재 `discord.py + FFmpeg + yt-dlp` 방식입니다.

대안:
- Direct Voice (`discord.py` VoiceClient + FFmpeg)
  - 장점: 단순, 단일 프로세스, 빠른 구축
  - 단점: 대규모 길드/다중 재생 시 CPU/네트워크 부하 증가
- Lavalink Node + Client Library
  - 장점: 오디오 처리 분리, 안정적인 대규모 운영
  - 단점: Java 노드 운영 필요, 인프라 복잡도 증가

참고 문서:
- discord.py FAQ (Voice 관련): <https://discordpy.readthedocs.io/en/stable/faq.html#how-do-i-pass-a-coroutine-to-the-player-s-after-function>
- discord.py migrating notes (voice 관련): <https://discordpy.readthedocs.io/en/stable/migrating_to_v1.html#voice-changes>
- Lavalink 공식 문서: <https://lavalink.dev/>
- Lavalink Python clients list: <https://lavalink.dev/client-libraries.html>
- yt-dlp 공식 저장소: <https://github.com/yt-dlp/yt-dlp>

## News Radar Paging
- 기본 채널은 1페이지(토픽 필드 기준)로 요약하며,
- 초과 항목은 동일 메시지 스레드에서 `2페이지`, `3페이지`로 연속 게시합니다.
- 기본 선정량: `per_topic_limit=8`, `max_total_items=40`

## Event Reminder (EVENT-REMINDER-1)
- 원본: Discord Scheduled Event
- 스캔 주기: 1분 (`event_reminder.scan_cron`)
- 알림 시점: 시작 `5분 전` (Phase 1 고정)
- 채널 알림: `운영-브리핑` (`@here` + 참가자 멘션 분할)
- DM 알림: 참가자별 1회
- 중복 방지: `event_id + start_at + user_id` idempotency key

## Quick Start
```bash
cd /Users/river/tools/mangsang-orbit-assistant
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 -m bot.app
```

## Environment Variables
`.env` 예시:
```env
DISCORD_BOT_TOKEN=
GEMINI_API_KEY=
TARGET_GUILD_ID=1401492009486651452
TZ=Asia/Seoul
DATA_DIR=./data
FFMPEG_PATH=/opt/homebrew/bin/ffmpeg
OPUS_LIBRARY_PATH=/opt/homebrew/opt/opus/lib/libopus.0.dylib
```

## Music 런타임 설정 (`music` 섹션)
`config/settings.yaml`의 `music` 섹션 권장값:
```yaml
music:
  enabled: true
  source_policy: "hybrid"
  allowlist_user_ids:
    - 286397219886858240
  default_voice_channel: "음악 라운지"
  idle_disconnect_minutes: 10
  max_queue_size: 30
  max_track_minutes: 180
  default_volume: 70
  notice_policy: "low_noise"
  ffmpeg_path: "/opt/homebrew/bin/ffmpeg"
  opus_library_path: "/opt/homebrew/opt/opus/lib/libopus.0.dylib"
  show_control_card: true
  announce_now_playing: true
  music_panel_command_enabled: true
  default_control_channel: "auto"
  panel_update_mode: "edit_last"
```

## Recommended Operations (launchd)
```bash
cd /Users/river/tools/mangsang-orbit-assistant
./scripts/botctl.sh start --launchd
./scripts/botctl.sh status --launchd
./scripts/botctl.sh logs --launchd
./scripts/botctl.sh stop --launchd
```

## Command Reference
### Slash Commands
- `/meeting_summary scope:{thread|channel} window_minutes:int publish_to_decision_log:bool source_channel:#channel(optional)`
- `/meeting_summary_v2 scope:{thread|channel} window_minutes:int publish_to_decision_log:bool source_channel:#channel(optional)`  
  (`2026-02-25` 제거 예정)
- `/decision_add title:str owner:str due_date:str context_url:str`
- `/warroom_open name:str zone:{core|product|growth} ttl_days:int`
- `/warroom_close name:str reason:str`
- `/warroom_list status:{active|archived|all}`
- `/news_run_now hours:int`
- `/news_config`
- `/curation_status`
- `/curation_config mode:{approve|auto} intake_channel:#channel`
- `/curation_publish submission_id:str target:#channel(optional) create_thread:bool(optional, default false)`
- `/curation_reject submission_id:str reason:str`
- `/event_reminder_status`
- `/event_reminder_config enabled:bool reminder_minutes:int send_dm:bool`
- `/music join channel:#voice(optional)`
- `/music play query_or_url:str`
- `/music pause`
- `/music resume`
- `/music skip`
- `/music panel`
- `/music queue page:int`
- `/music volume percent:int(optional)`
- `/music now`
- `/music stop`
- `/music leave`
- `/bot_status`

### DM Commands (Hybrid + Allowlist)
- `도움말|help|?`
- `상태|status`
- `워룸|warroom`
- `뉴스|news [hours]` (allowlist 사용자만 실행)
- `요약 <텍스트>|summary <text>`

자연어 DM은 Q&A/가이드만 처리하며, 서버 변경 액션은 자동 실행하지 않습니다.

## Health Checks
```bash
cd /Users/river/tools/mangsang-orbit-assistant
.venv/bin/python scripts/sync_probe.py
./scripts/botctl.sh status --launchd
```

## Data Layout
- `data/decisions.jsonl`
- `data/warrooms.jsonl`
- `data/summaries.jsonl`
- `data/news_items.jsonl`
- `data/news_digests.jsonl`
- `data/ops_events.ndjson`

## Development & Test
```bash
cd /Users/river/tools/mangsang-orbit-assistant
.venv/bin/pytest -q
```

## Voice Troubleshooting
- 에러 `OpusNotLoaded`가 뜨면:
```bash
brew install opus
```
- `.env`에 `OPUS_LIBRARY_PATH`를 설정하고 봇을 재시작:
```bash
OPUS_LIBRARY_PATH=/opt/homebrew/opt/opus/lib/libopus.0.dylib
./scripts/botctl.sh stop --launchd
./scripts/botctl.sh start --launchd
```
- 증상: `상호작용 실패`
  - 원인: 구버전 패널 메시지/재시작 직후 stale 컴포넌트
  - 조치: `/music panel` 1회 실행으로 최신 패널 재게시
- 증상: 음성 채널에서 재생 시작은 되는데 소리가 안 남
  - 조치 1: 대상 음성 채널에서 봇 권한 `연결(connect)` + `말하기(speak)` 확인
  - 조치 2: Stage 채널이면 봇이 청중(suppressed) 상태가 아닌지 확인(발언 허용)
  - 조치 3: `FFMPEG_PATH`, `OPUS_LIBRARY_PATH` 재확인 후 재시작

## Docs
- `docs/command-migration-runbook.md`
- `docs/agent-team-playbook.md`
