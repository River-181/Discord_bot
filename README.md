# Mangsang Orbit Assistant

Discord 운영 자동화를 위한 `discord.py` 기반 팀 비서 봇입니다.  
회의 요약, 워룸 라이프사이클, 뉴스 레이다, DM 비서, 음악 재생 기능을 하나의 봇으로 통합합니다.

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
- 이벤트 리마인더: `/event_reminder_status`, `/event_reminder_config`
- DM 하이브리드 비서: `도움말`, `상태`, `워룸`, `뉴스`, `요약 <텍스트>`
- 음악 기능(MUSIC-1): `/music` 그룹 10종 서브명령
- 운영 점검: `/bot_status`

## Music (MUSIC-1)
정책 고정값:
- 음원 정책: `hybrid`
- 제어 권한: `봇과 같은 음성 채널 사용자만`
- 알림 정책: `low_noise` (ephemeral 중심)
- 길이 제한: 기본 `180분` (`music.max_track_minutes`)

지원 명령:
- `/music join channel:#voice(optional)`
- `/music play query_or_url:str`
- `/music pause`
- `/music resume`
- `/music skip`
- `/music queue page:int`
- `/music volume percent:int(optional)`
- `/music now`
- `/music stop`
- `/music leave`

소스 정책:
- 일반 사용자: 직접 URL(`http/https`)만 허용
- allowlist 사용자: YouTube URL/검색어 허용(`yt-dlp`)

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
- 채널에는 `1페이지`만 게시
- `2페이지 이상`은 자동 생성된 뉴스 스레드에 연속 게시
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
- `/event_reminder_status`
- `/event_reminder_config enabled:bool reminder_minutes:int send_dm:bool`
- `/music join channel:#voice(optional)`
- `/music play query_or_url:str`
- `/music pause`
- `/music resume`
- `/music skip`
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

## Docs
- `docs/command-migration-runbook-2026-02-18.md`
