"""Проверки индивидуальных статусов участников задачи."""

from datetime import datetime

from tbot.tasks import (
    Task,
    TaskPriority,
    TaskStatus,
    get_participant_status,
    recalc_task_status,
    set_participant_status,
)


def _make_task() -> Task:
    """Создаёт задачу с автором, ответственным и рабочей группой."""

    task = Task(
        task_id=1,
        title="Тестовая задача",
        description="",
        author_id=1,
        created_date=datetime.now(),
        due_date=None,
        priority=TaskPriority.MEDIUM,
        responsible_user_id=2,
        workgroup=[3, 4],
    )

    for participant_id in {1, 2, 3, 4}:
        task.participant_statuses[participant_id] = TaskStatus.NEW

    return task


def test_author_sees_workgroup_progress() -> None:
    """Автор должен видеть статус ""В работе"", если участник начал работу."""

    task = _make_task()

    set_participant_status(task, 3, TaskStatus.ACTIVE)
    recalc_task_status(task)

    assert get_participant_status(task, 3) is TaskStatus.ACTIVE
    assert get_participant_status(task, 1) is TaskStatus.ACTIVE
    assert get_participant_status(task, 2) is TaskStatus.NEW
    assert get_participant_status(task, 4) is TaskStatus.NEW


def test_author_sees_responsible_progress() -> None:
    """Если ответственный начал работу, автор тоже видит статус ""В работе""."""

    task = _make_task()

    set_participant_status(task, 2, TaskStatus.ACTIVE)
    recalc_task_status(task)

    assert get_participant_status(task, 2) is TaskStatus.ACTIVE
    assert get_participant_status(task, 1) is TaskStatus.ACTIVE
    assert get_participant_status(task, 3) is TaskStatus.NEW
    assert get_participant_status(task, 4) is TaskStatus.NEW


def test_author_sees_pause_when_only_postponed() -> None:
    """Пауза у рабочих приводит к отображению паузы у автора."""

    task = _make_task()

    set_participant_status(task, 3, TaskStatus.PAUSED)
    recalc_task_status(task)

    assert get_participant_status(task, 3) is TaskStatus.PAUSED
    assert get_participant_status(task, 1) is TaskStatus.PAUSED
    assert get_participant_status(task, 2) is TaskStatus.NEW
    assert get_participant_status(task, 4) is TaskStatus.NEW


def test_active_has_priority_over_pause() -> None:
    """Если кто-то работает, автор видит статус ""В работе"" даже при паузе у других."""

    task = _make_task()

    set_participant_status(task, 3, TaskStatus.PAUSED)
    set_participant_status(task, 2, TaskStatus.ACTIVE)
    recalc_task_status(task)

    assert get_participant_status(task, 2) is TaskStatus.ACTIVE
    assert get_participant_status(task, 3) is TaskStatus.PAUSED
    assert get_participant_status(task, 1) is TaskStatus.ACTIVE


def test_author_pause_when_responsible_paused() -> None:
    """Пауза ответственного без активных участников отражается у автора."""

    task = _make_task()

    set_participant_status(task, 2, TaskStatus.PAUSED)
    recalc_task_status(task)

    assert get_participant_status(task, 2) is TaskStatus.PAUSED
    assert get_participant_status(task, 1) is TaskStatus.PAUSED
    assert get_participant_status(task, 3) is TaskStatus.NEW
    assert get_participant_status(task, 4) is TaskStatus.NEW
