# 새 Discord 공간에 망상궤도 비서를 연결하는 방법
## Discord 세팅 + 봇 연결 + 운영 검증을 한 번에 끝내는 실무 가이드 (2026-02-18)

문서 목적: 기존 서버가 아닌 **새 Discord 공간(새 서버)** 에 망상궤도 비서를 붙여서 바로 운영 가능한 상태를 만드는 방법을 Medium 블로그 형식으로 제공한다.

---

## 작성 1차 (초안)

### 글의 중심 메시지
- 새 서버 연결 실패는 대부분 “앱 권한”, “채널 이름 불일치”, “명령 캐시”에서 발생한다.
- 따라서 설정 순서와 검증 순서를 분리하면 연결 성공률이 크게 올라간다.

### 초안 목차
1. 사전 준비
2. Discord Developer Portal 세팅
3. 새 서버 초대
4. 채널/카테고리 맞춤
5. 봇 실행
6. 동기화/스모크 테스트
7. 장애 대응

---

## 검토 1차

### 보완 포인트
1. 새 공간에서 바로 복붙 가능한 명령어를 포함해야 한다.
2. 채널명을 다르게 쓰고 싶을 때 `config/settings.yaml` 수정 규칙을 넣어야 한다.
3. 실제 운영 기준(`launchd`, `sync_probe.py`, `/bot_status`) 검증 루프를 명시해야 한다.
4. 첨부 이미지 삽입 위치를 단계별로 고정해야 한다.
5. 캐시 오류 우회(`meeting_summary_v2`)를 본문에 반드시 넣어야 한다.

---

## 작성 2차 (완전체 원고)

> **TL;DR**  
> 새 Discord 공간에 봇을 붙일 때는  
> 1) Developer Portal 권한/Intent 정렬  
> 2) 서버 채널명-설정 파일 매칭  
> 3) `launchd` 실행 + `sync_probe.py` 검증  
> 이 3단계만 정확히 지키면 된다.

---

### 왜 “새 공간 연결”에서 자주 막힐까

실무에서 문제는 기능이 아니라 연결 순서에서 생긴다.

- 앱은 살아 있는데 명령이 “더는 사용되지 않음”으로 보임
- 채널은 있는데 요약 명령이 메시지 0건으로 뜸
- 봇은 초대됐는데 응답이 가끔 안 옴

이 글은 이 세 가지를 한 번에 해결하는 기준 절차를 제공한다.

---

### 0. 준비물 (5분)

- Discord 앱: `망상궤도 비서`
- 서버(새 공간) 생성 권한
- 로컬 운영 경로: `/Users/river/tools/mangsang-orbit-assistant`
- 환경 변수:
- `DISCORD_BOT_TOKEN`
- `GEMINI_API_KEY` (요약 모델 사용 시)

운영 기본 시간대:
- `Asia/Seoul`

---

### 1. Developer Portal 설정 (먼저 고정)

새 공간 연결은 서버보다 **앱 설정**을 먼저 고정해야 한다.

#### 1-1) General Information
- App Name: `망상궤도 비서`
- Description: 회의 요약/결정 로그/워룸 관리 목적을 명시

#### 1-2) Installation
- `Guild Install` ON
- `User Install` OFF (팀 내부 서버 운영이면 권장)
- Scopes:
- `bot`
- `applications.commands`

#### 1-3) OAuth2
- Public Client OFF
- Redirect URI 미사용이면 비워둠

#### 1-4) Bot
- `Requires OAuth2 Code Grant` OFF
- Privileged Gateway Intents:
- `Message Content Intent` ON (필수)
- `Server Members Intent` ON (권장)
- `Presence Intent` OFF (현재 미사용)

#### 1-5) Webhooks / Activities
- 현재 구조에서 미사용, 기본 OFF 유지

---

### 2. 새 공간(새 서버)에 봇 초대

초대 URL 예시:

```text
https://discord.com/oauth2/authorize?client_id=1472278807917363262&scope=bot%20applications.commands&permissions=311385213968
```

핵심:
- `bot + applications.commands` 둘 다 필요
- 권한 누락 시 워룸 생성/요약/스레드 기능이 부분 실패한다

---

### 3. 서버 구조 세팅: “이름 매칭”이 핵심

봇은 `config/settings.yaml`의 채널명을 기준으로 동작한다.  
즉, 새 공간에서 채널명을 동일하게 만들거나, 설정 파일을 새 이름으로 바꿔야 한다.

현재 기준 채널:
- `회의`
- `망상궤도-비서-공간`
- `운영-브리핑`
- `가이드`

워룸 카테고리(기준):
- `------🧱-01-코어--------`
- `------🧩-02-제품--------`
- `------🚀-03-성장--------`
- `------🔊-06-음성채널-----`
- `----------아카이브----------`

---

### 4. 채널명을 다르게 쓰고 싶다면

새 공간에서 명칭을 다르게 쓰면 아래 파일을 수정한다.

파일:
- `/Users/river/tools/mangsang-orbit-assistant/config/settings.yaml`

수정 포인트:
- `channels.meeting_source`
- `channels.decision_log`
- `channels.assistant_output`
- `warroom.text_category_by_zone.*`
- `warroom.voice_category`
- `warroom.archive_category`

수정 후에는 반드시 재시작:

```bash
launchctl kickstart -k gui/$(id -u)/com.mangsang.orbit.assistant
```

---

### 5. 실행은 launchd 단일 모드로 고정

운영 표준 명령:

```bash
cd /Users/river/tools/mangsang-orbit-assistant
./scripts/botctl.sh start --launchd
./scripts/botctl.sh status --launchd
```

로그 확인:

```bash
./scripts/botctl.sh logs --launchd
```

---

### 6. 연결 검증 루프 (이 단계가 핵심)

#### 6-1) 명령 동기화 검증

```bash
cd /Users/river/tools/mangsang-orbit-assistant
.venv/bin/python scripts/sync_probe.py
```

정상 기준:
- `guild_command_count 7`
- `global_command_count 0`
- `meeting_options_equal True`
- `sync-probe ok phase=migration`

#### 6-2) Discord 내부 점검
- `/bot_status` 실행
- 확인 값:
- `process_mode: launchd`
- `has_meeting_summary: True`
- `has_meeting_summary_v2: True`
- `meeting_options_equal: True`

---

### 7. 새 공간에서 첫 스모크 테스트

#### 7-1) 요약 테스트

```text
/meeting_summary_v2 scope:channel window_minutes:240 publish_to_decision_log:false source_channel:#회의
```

참고:
- 캐시 문제로 `/meeting_summary`가 즉시 안 먹히면 `/meeting_summary_v2`부터 사용
- `scope=thread`이면 `source_channel`를 넣지 않는다

#### 7-2) 워룸 테스트

```text
/warroom_open name:space-onboarding zone:product ttl_days:7
/warroom_list status:active
/warroom_close name:space-onboarding reason:setup-check-complete
```

---

### 8. 운영 중 자주 만나는 에러와 즉시 대응

#### 에러 A) 더는 사용되지 않는 명령어입니다
- 원인: 슬래시 명령 캐시 불일치
- 대응:
1. `/meeting_summary_v2` 실행
2. `sync_probe.py` 실행
3. Discord 새로고침 (`Ctrl/Cmd + R`)

#### 에러 B) 애플리케이션이 응답하지 않았어요
- 원인: 프로세스 중단/중복 인스턴스 충돌
- 대응:
1. `./scripts/botctl.sh status --launchd`
2. `launchctl kickstart -k gui/$(id -u)/com.mangsang.orbit.assistant`
3. 로그 확인

#### 에러 C) 요약할 메시지가 없습니다
- 원인: 실행 채널 착오, 텍스트 미존재, 권한/intent 이슈
- 대응:
1. `source_channel:#회의` 지정
2. 텍스트 메시지 확인
3. `Message Content Intent` 확인

---

### 9. D+7 정리 정책 (2026-02-25)

- 임시 명령 `/meeting_summary_v2` 제거
- 표준 명령 `/meeting_summary` 단일화

검증:

```bash
cd /Users/river/tools/mangsang-orbit-assistant
.venv/bin/python scripts/sync_probe.py --phase post-migration
```

---

### 10. 보안 체크리스트

- 토큰/API 키는 `.env`만 사용
- 키 노출 시 즉시 회전(Discord Bot Token, Gemini/OpenAI 키)
- 스크린샷/문서 공유 전에 키/식별자 마스킹

---

### 결론

새 공간 연결은 기능 개발 문제가 아니라 **운영 표준 문제**다.  
`권한 고정 -> 채널명 매칭 -> launchd 실행 -> sync_probe 검증` 루프를 지키면,  
팀이 바뀌어도 같은 품질로 재현 가능한 봇 운영을 만들 수 있다.

---

## 첨부 이미지 사용 가이드 (본문 삽입 순서)

아래 이미지를 본문에 순서대로 삽입:

1. 이미지 01: Developer Portal `General Information`
2. 이미지 02: `Installation`
3. 이미지 03: `OAuth2`
4. 이미지 04: `Bot` (Privileged Intents 영역 포함)
5. 이미지 05: `Webhooks`
6. 이미지 06: `App Verification`
7. 이미지 07: `Discord Social SDK > Getting Started`
8. 이미지 08: `Activities > Settings`
9. 이미지 09: `Activities > URL Mappings`
10. 이미지 10: `Activities > Art Assets`
11. 이미지 11(옵션): `더는 사용되지 않는 명령어입니다` 오류 예시
12. 이미지 12(옵션): `/meeting_summary_v2` 성공 결과 예시
13. 이미지 13(옵션): `/warroom_open` 성공 결과 예시

권장 캡션 스타일:
- “Figure N. [기능/페이지]에서 반드시 확인할 설정값”

---

## 검토 2차

### 검토 체크리스트
1. 새 공간 세팅 절차가 처음 보는 운영자도 따라할 수 있는가
2. 복붙 가능한 명령이 충분한가
3. 캐시/응답/요약 0건 이슈 대응이 포함되었는가
4. 첨부 이미지 위치가 단계별로 고정되었는가
5. D+7 제거 정책이 날짜와 함께 명확한가

### 검토 결과
- 1 통과
- 2 통과
- 3 통과
- 4 통과
- 5 통과

최종 상태: 배포 가능 (Medium 게시용 완전체)
