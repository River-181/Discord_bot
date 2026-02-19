# 새 Discord 공간에 ‘망상궤도 비서’ 붙이는 방법
Discord 세팅부터 봇 연결, 운영 검증까지. 15분 안에 “바로 쓰는 상태” 만들기 (2026-02-19 기준)

새 서버에서 봇을 굴리다가 막히는 지점은 대부분 4가지입니다.
- 앱 권한/Intent 누락
- 서버 채널명과 `config/settings.yaml` 불일치
- 슬래시 명령 캐시 불일치(“더는 사용되지 않는 명령어”)
- 이벤트는 만들었는데 리마인더가 안 오는 상태

이 글은 위 3가지를 “설정 순서 + 검증 루프”로 한 번에 끝내는 실무 절차만 담았습니다.

> TL;DR
> 1) Developer Portal 설정 고정
> 2) 새 서버에서 채널명 매칭(또는 `settings.yaml` 수정)
> 3) `launchd`로 실행 + `sync_probe.py`로 검증
> 4) Scheduled Event 5분 전 채널/DM 알림 확인
> 이 4단계를 지키면 새 공간 연결은 재현 가능해집니다.

---

## 0) 준비물 (5분)

필요한 것:
- Discord Developer Portal에서 앱(봇) 설정 권한
- 새 Discord 서버(공간) 생성/관리 권한
- 로컬 실행 경로: `/Users/river/tools/mangsang-orbit-assistant`
- 환경 변수:
  - `DISCORD_BOT_TOKEN`
  - `GEMINI_API_KEY` (요약 기능 품질용. 없으면 fallback 또는 비동작 가능)

운영 기본값:
- 시간대: `Asia/Seoul`

> Security Note
> Bot Token / API Key를 Discord 채팅이나 스크린샷에 그대로 남기지 마세요. 노출되면 즉시 키를 회전(재발급)해야 합니다.

---

## 1) Developer Portal 설정(먼저 고정)

새 서버를 만들기 전에 “앱 설정”을 먼저 고정하는 게 안전합니다.

### 1-1) General Information
- App Name: `망상궤도 비서`
- Description: 회의 요약/결정 로그/워룸 관리 목적을 2줄로 명시

Figure 1. Developer Portal `General Information` (앱 이름/설명 확인)

### 1-2) Installation
- `Guild Install` ON
- 내부 서버 운영이면 `User Install` OFF 권장
- Scopes:
  - `bot`
  - `applications.commands`

Figure 2. `Installation` (Guild Install + scopes 확인)

### 1-3) OAuth2
- Public Client OFF
- Redirect URI는 쓰지 않으면 비워둠

Figure 3. `OAuth2` (불필요한 공개 설정 OFF)

### 1-4) Bot (Intents)
Privileged Gateway Intents:
- `Message Content Intent` ON (필수)
- `Server Members Intent` ON (권장)
- `Presence Intent`는 현재 미사용이면 OFF 유지

Figure 4. `Bot` (Privileged Intents 영역이 보이게)

### 1-5) Webhooks / Activities / Verification
- Phase 1 기준: Webhooks, Activities는 미사용이면 기본값 유지

Figure 5. `Webhooks` (설정 불필요, 기본값 유지)
Figure 6. `App Verification` (검증은 100+ 서버 이후에 필요할 수 있음)
Figure 7. `Discord Social SDK > Getting Started` (미사용이면 스킵)
Figure 8. `Activities > Settings` (미사용이면 스킵)
Figure 9. `Activities > URL Mappings` (미사용이면 스킵)
Figure 10. `Activities > Art Assets` (미사용이면 스킵)

---

## 2) 새 서버에 봇 초대

초대 URL 예시:

```text
https://discord.com/oauth2/authorize?client_id=1472278807917363262&scope=bot%20applications.commands&permissions=311385213968
```

체크:
- `bot` + `applications.commands` 둘 다 포함
- 권한이 빠지면 워룸 생성/요약/스레드 기능이 “부분적으로만” 실패합니다(가장 디버깅이 어려운 타입).

---

## 3) 서버 구조 세팅: “채널명 매칭”이 핵심

봇은 `/Users/river/tools/mangsang-orbit-assistant/config/settings.yaml`의 이름을 기준으로 채널을 찾습니다.
즉, 새 서버에서 채널명을 그대로 만들면 연결이 가장 단순합니다.

현재 기본 채널(권장, 최소):
- `회의` (회의 원문이 쌓이는 곳)
- `망상궤도-비서-공간` (봇 결과물/로그가 모이는 허브)
- `운영-브리핑` (딥워크 예외 채널로도 사용)
- `가이드` (운영 안내)

워룸 카테고리(권장):
- `------🧱-01-코어--------`
- `------🧩-02-제품--------`
- `------🚀-03-성장--------`
- `------🔊-06-음성채널-----`
- `----------아카이브----------`

> 팁: “결정-log / knowledge-base / automation-log”를 따로 분리하고 싶으면,
> `settings.yaml`에서 `channels.decision_log`, `channels.knowledge_base`, `channels.automation_log`를 각각 다른 채널명으로 바꾸면 됩니다.

---

## 4) 채널명을 다르게 쓰고 싶다면(설정 파일만 수정)

수정 파일:
- `/Users/river/tools/mangsang-orbit-assistant/config/settings.yaml`

자주 수정하는 키:
- `channels.meeting_source` (회의 원문 채널)
- `channels.assistant_output` (봇 결과 출력 채널)
- `channels.decision_log` / `channels.knowledge_base` / `channels.automation_log`
- `warroom.text_category_by_zone.*`
- `warroom.voice_category`
- `warroom.archive_category`

수정 후 재시작:

```bash
launchctl kickstart -k gui/$(id -u)/com.mangsang.orbit.assistant
```

---

## 5) 실행은 launchd “단일 모드”로 고정

운영 표준:

```bash
cd /Users/river/tools/mangsang-orbit-assistant
./scripts/botctl.sh start --launchd
./scripts/botctl.sh status --launchd
```

로그:

```bash
./scripts/botctl.sh logs --launchd
```

> “애플리케이션이 응답하지 않았어요”가 간헐적으로 뜨면,
> 거의 항상 봇 프로세스 중단 또는 중복 인스턴스 충돌입니다. 운영은 `launchd` 하나만 쓰는 게 답입니다.

---

## 6) 연결 검증 루프(이 단계가 핵심)

### 6-1) 명령 동기화/캐시 검증(로컬)

```bash
cd /Users/river/tools/mangsang-orbit-assistant
.venv/bin/python scripts/sync_probe.py
```

정상 기준(핵심만):
- `guild_command_count: 12`
- `global_command_count: 0`
- `meeting_options_equal: True`

### 6-2) Discord 내부 점검

Discord에서:
- `/bot_status` 실행

확인 포인트:
- `process_mode: launchd`
- `has_meeting_summary: True`
- `has_meeting_summary_v2: True` (마이그레이션 기간에만)
- `event_reminder_enabled: True`
- `event_reminder_scan_cron: */1 * * * *`
- `event_reminder_channel: 운영-브리핑`

---

## 7) 첫 스모크 테스트(복붙)

### 7-1) 회의 요약(캐시 우회 버전)

```text
/meeting_summary_v2 scope:channel window_minutes:240 publish_to_decision_log:false source_channel:#회의
```

주의:
- `scope=thread`일 때는 `source_channel`을 넣지 않습니다.
- “메시지 수: 1”은 정상일 수 있습니다.
  - Discord “메시지 1개” 안에 로그를 길게 붙여넣으면, 요약은 길게 나오되 메시지 수는 1로 표시됩니다.

Figure 11. 캐시 오류 예시(“더는 사용되지 않는 명령어입니다”)
Figure 12. `/meeting_summary_v2` 성공 결과 예시

### 7-2) 워룸 생성/조회/종료

```text
/warroom_open name:space-onboarding zone:product ttl_days:7
/warroom_list status:active
/warroom_close name:space-onboarding reason:setup-check-complete
```

Figure 13. `/warroom_open` 성공 결과 예시

### 7-3) 이벤트 5분 전 리마인더 상태/설정

```text
/event_reminder_status
/event_reminder_config enabled:true reminder_minutes:5 send_dm:true
```

의도:
- `운영-브리핑` 채널에 `@here + 참가자 멘션` 발송
- 이벤트 참가자에게 개별 DM 발송
- 동일 이벤트/동일 시작시각은 중복 발송 방지

Figure 14. `/event_reminder_status` 결과 예시
Figure 15. 5분 전 알림 채널 메시지 예시

---

## 8) 운영 중 자주 만나는 에러와 즉시 대응

### A) “더는 사용되지 않는 명령어입니다”
원인:
- 슬래시 명령 캐시 불일치(Discord 클라이언트/서버 캐시)

대응:
1. `/meeting_summary_v2`로 우회 실행
2. 로컬에서 `sync_probe.py` 실행
3. Discord 클라이언트 새로고침(`Ctrl/Cmd + R`)

### B) “애플리케이션이 응답하지 않았어요”
원인:
- 봇 프로세스 중단, 또는 중복 실행

대응:
1. `./scripts/botctl.sh status --launchd`
2. `launchctl kickstart -k gui/$(id -u)/com.mangsang.orbit.assistant`
3. `./scripts/botctl.sh logs --launchd`로 원인 확인

### C) “요약할 메시지가 없습니다”
원인:
- 실행 채널이 회의 원문 채널이 아님
- 최근 `window_minutes` 범위에 텍스트가 없음(이미지/첨부만 있으면 제외될 수 있음)
- `Message Content Intent` OFF

대응:
1. `source_channel:#회의`로 명시
2. `window_minutes` 늘려 재시도(예: 240)
3. Developer Portal에서 `Message Content Intent`가 ON인지 재확인

### D) 이벤트를 만들었는데 5분 전 알림이 안 온다
원인:
- 이벤트 시작시각이 아직 5분 윈도우 밖
- 이벤트 참가자가 없어 DM 발송 대상이 없음
- `event_reminder.enabled` 또는 `send_dm` 설정 비활성
- `운영-브리핑` 채널명이 실제와 불일치

대응:
1. `/event_reminder_status`로 마지막 스캔 결과 확인
2. `config/settings.yaml`의 `event_reminder.reminder_channel` 채널명 확인
3. 봇 재시작 후 `data/ops_events.ndjson`에 `event_reminder_scan_completed` 기록 확인

---

## 9) 7일 마이그레이션 정책(2026-02-25에 정리)

마이그레이션 기간:
- 2026-02-18 ~ 2026-02-24: `/meeting_summary` + `/meeting_summary_v2` 병행
- 2026-02-25: `/meeting_summary_v2` 제거, `/meeting_summary`만 유지

정리 후 검증:

```bash
cd /Users/river/tools/mangsang-orbit-assistant
.venv/bin/python scripts/sync_probe.py --phase post-migration
```

---

## 결론

새 공간 연결은 “기능 개발”보다 “운영 표준” 문제입니다.

`Developer Portal 설정 고정 -> 채널명 매칭 -> launchd 실행 -> sync_probe 검증 -> 이벤트 리마인더 점검`
이 루프를 팀 표준으로 만들면, 서버가 늘어나도 같은 품질로 재현 가능합니다.
