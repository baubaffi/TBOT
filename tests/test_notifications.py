from __future__ import annotations

import asyncio
from datetime import datetime

from tbot.bot import notify_task_participants
from tbot.tasks import Task, TaskPriority


class DummyBot:
    """Фиктивный бот для проверки уведомлений."""

    def __init__(self) -> None:
        self.sent_messages: list[tuple[int, str, object]] = []

    async def send_message(self, chat_id: int, text: str, reply_markup=None) -> None:
        self.sent_messages.append((chat_id, text, reply_markup))


def test_workgroup_members_do_not_notify_each_other() -> None:
    task = Task(
        task_id=1,
        title="Тестовая задача",
        description="",
        author_id=7247710860,
        created_date=datetime.now(),
        due_date=None,
        priority=TaskPriority.MEDIUM,
        responsible_user_id=609995295,
        workgroup=[1311714242, 678543417],
    )

    bot = DummyBot()

    asyncio.run(
        notify_task_participants(
            bot,
            task,
            actor_id=1311714242,
            action_description="проверяет фильтрацию уведомлений.",
        )
    )

    recipients = {chat_id for chat_id, *_ in bot.sent_messages}

    assert 7247710860 in recipients
    assert 609995295 in recipients
    assert 1311714242 not in recipients
    assert 678543417 not in recipients
