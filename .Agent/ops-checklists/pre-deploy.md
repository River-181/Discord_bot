# Pre-deploy Checklist

- [ ] `git status` 깨끗
- [ ] `bash .Agent/scripts/validate.sh` 통과
- [ ] 변경 범위 파악 및 롤백 포인트 문서화
- [ ] 핵심 명령 스모크 테스트:
  - `/meeting_summary`
  - `/warroom_open`
  - `/news_run_now`
  - `/music_panel`(해당 시)
  - `/event_reminder_status`
- [ ] 데이터 백업(필수 파일) 또는 스냅샷 보관
