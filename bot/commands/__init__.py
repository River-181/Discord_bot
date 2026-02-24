from bot.commands import curation, event_reminder, meeting, music, news, status, warroom


def register_all(bot) -> None:
    meeting.register(bot)
    music.register(bot)
    news.register(bot)
    warroom.register(bot)
    curation.register(bot)
    event_reminder.register(bot)
    status.register(bot)
