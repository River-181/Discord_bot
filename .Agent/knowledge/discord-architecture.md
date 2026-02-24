# Discord Architecture Knowledge

## 구성

- Bot runtime: `discord.py` on Python
- Command layer: `/meeting_summary`, `/warroom_*`, `/news_*`, `/music_*`, `/event_reminder_*`, `/bot_status`, `/curation_*`, `DM assistant`
- Monitoring: FastAPI API + Streamlit dashboard (`tools/dashboard`)

## 데이터 원천

- `data/*.jsonl` (결정/요약/워룸/이벤트/큐레이션/뮤직 로그)
- 로그: `data/logs/*.log`

## 운영 포인트

- launchd 권장 운영
- 로컬 JSONL이 사실상 운영 상태의 truth
- 대시보드는 읽기 전용 가시성으로만 사용
