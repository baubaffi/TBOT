"""Проверки отображения персональных статусов в текстах бота."""

import asyncio
from datetime import datetime

from tbot.bot import build_task_detail_text, build_tasks_list_text, send_task_reminder
from tbot.tasks import (
    Task,
    TaskPriority,
    TaskStatus,
    recalc_task_status,
    set_participant_status,
)

AUTHOR_ID = 7247710860
RESPONSIBLE_ID = 609995295
WORKGROUP_IDS = [1311714242, 678543417]


class _DummyBot:
    """Простая заглушка бота для проверки отправленных сообщений."""

    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, reply_markup=None) -> None:
        """Сохраняет текст сообщения без реальной отправки."""

        self.messages.append((chat_id, text))


def _make_task() -> Task:
    """Создаёт задачу с автором, ответственным и рабочей группой."""

    task = Task(
        task_id=1,
        title="Тестовая задача",
        description="",
        author_id=AUTHOR_ID,
        created_date=datetime.now(),
        due_date=None,
        priority=TaskPriority.MEDIUM,
        responsible_user_id=RESPONSIBLE_ID,
        workgroup=list(WORKGROUP_IDS),
    )

    participants = {AUTHOR_ID, RESPONSIBLE_ID, *WORKGROUP_IDS}

    for participant_id in participants:
        task.participant_statuses[participant_id] = TaskStatus.NEW

    return task


def test_task_detail_uses_personal_status_for_viewer() -> None:
    """Карточка задачи должна показывать статус зрителя, а не общий."""

    task = _make_task()
    set_participant_status(task, WORKGROUP_IDS[0], TaskStatus.ACTIVE)
    recalc_task_status(task)

    author_text = build_task_detail_text(task, viewer_id=AUTHOR_ID)
    member_text = build_task_detail_text(task, viewer_id=WORKGROUP_IDS[1])

    assert "Статус: В работе" in author_text
    assert "Статус: Новая" in member_text


def test_tasks_list_uses_personal_status_icon() -> None:
    """В списке задач участник должен видеть свой статус по иконке."""

    task = _make_task()
    set_participant_status(task, WORKGROUP_IDS[0], TaskStatus.ACTIVE)
    recalc_task_status(task)

    author_list = build_tasks_list_text([task], "все", 1, viewer_id=AUTHOR_ID)
    member_list = build_tasks_list_text([task], "все", 1, viewer_id=WORKGROUP_IDS[1])

    assert "1. 🔄 🟡" in author_list
    assert "1. 🆕 🟡" in member_list


def test_send_task_reminder_uses_personal_status() -> None:
    """Напоминания должны содержать персональный статус получателя."""

    task = _make_task()
    set_participant_status(task, WORKGROUP_IDS[0], TaskStatus.ACTIVE)
    recalc_task_status(task)

    bot = _DummyBot()
    asyncio.run(
        send_task_reminder(
            bot,
            task,
            actor_id=AUTHOR_ID,
            recipients=list(WORKGROUP_IDS),
        )
    )

    messages = dict(bot.messages)

    first_member, second_member = WORKGROUP_IDS
    assert "Статус: 🔄 В работе" in messages[first_member]
    assert "Статус: 🆕 Новая" in messages[second_member]
