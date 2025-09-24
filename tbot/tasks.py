"""Модуль для работы с задачами."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Iterable, List, Optional, Set


class TaskStatus(Enum):
    """Статусы задач."""

    NEW = "Новая"
    ACTIVE = "В работе"
    PAUSED = "На паузе"
    IN_REVIEW = "На проверке"
    COMPLETED = "Завершена"
    OVERDUE = "Просрочена"


class TaskPriority(Enum):
    """Приоритеты задач."""
    
    LOW = "🟢 Низкий"
    MEDIUM = "🟡 Средний"
    HIGH = "🟠 Высокий"
    CRITICAL = "🔴 Критический"


@dataclass
class Task:
    """Задача."""

    task_id: int
    title: str
    description: str
    author_id: int
    created_date: datetime
    due_date: Optional[datetime]
    priority: TaskPriority
    status: TaskStatus = TaskStatus.NEW
    project: str = ""
    direction: str = ""
    responsible_user_id: int = 0
    workgroup: List[int] = field(default_factory=list)
    is_private: bool = False
    completed_date: Optional[datetime] = None
    current_executor_id: Optional[int] = None
    last_action: Optional[str] = None
    last_actor_id: Optional[int] = None
    last_action_time: Optional[datetime] = None
    status_before_overdue: Optional[TaskStatus] = None
    participant_statuses: Dict[int, TaskStatus] = field(default_factory=dict)
    pending_confirmations: Set[int] = field(default_factory=set)
    awaiting_author_confirmation: bool = False


# Хранилище задач (временное, в памяти)
TASKS: dict[int, Task] = {}
_task_id_counter = 1


def create_task(
    title: str,
    description: str,
    author_id: int,
    priority: TaskPriority,
    due_date: Optional[datetime] = None,
    project: str = "",
    direction: str = "",
    responsible_user_id: int = 0,
    workgroup: Optional[Iterable[int]] = None,
    is_private: bool = False
) -> Task:
    """Создает новую задачу."""
    global _task_id_counter

    workgroup_list = list(workgroup) if workgroup is not None else []

    participants: Set[int] = {author_id}
    if responsible_user_id:
        participants.add(responsible_user_id)
    participants.update(workgroup_list)

    participant_statuses = {participant_id: TaskStatus.NEW for participant_id in participants}

    task = Task(
        task_id=_task_id_counter,
        title=title,
        description=description,
        author_id=author_id,
        created_date=datetime.now(),
        due_date=due_date,
        priority=priority,
        project=project,
        direction=direction,
        responsible_user_id=responsible_user_id,
        workgroup=workgroup_list,
        is_private=is_private,
        participant_statuses=participant_statuses,
    )

    TASKS[_task_id_counter] = task
    _task_id_counter += 1

    refresh_task_status(task)

    return task


def get_task(task_id: int) -> Optional[Task]:
    """Возвращает задачу по ID."""
    return TASKS.get(task_id)


def get_user_tasks(user_id: int) -> List[Task]:
    """Возвращает задачи пользователя."""
    user_tasks = []

    for task in TASKS.values():
        if (not task.is_private or 
            user_id == task.author_id or 
            user_id == task.responsible_user_id or 
            user_id in task.workgroup):
            user_tasks.append(task)

    return user_tasks


def update_task_status(task_id: int, status: TaskStatus) -> bool:
    """Обновляет статус задачи."""
    task = TASKS.get(task_id)
    if task:
        task.status = status
        if status == TaskStatus.COMPLETED:
            task.completed_date = datetime.now()
        return True
    return False


def delete_task(task_id: int) -> bool:
    """Удаляет задачу."""
    if task_id in TASKS:
        del TASKS[task_id]
        return True
    return False


def is_user_involved(task: Task, user_id: int) -> bool:
    """Проверяет, вовлечен ли пользователь в задачу."""

    return (
        user_id == task.author_id
        or user_id == task.responsible_user_id
        or user_id in task.workgroup
    )


def refresh_task_status(task: Task, reference: Optional[datetime] = None) -> None:
    """Обновляет статус задачи в зависимости от срока исполнения."""

    if task.status == TaskStatus.COMPLETED:
        return

    if reference is None:
        reference = datetime.now()

    if task.due_date and task.due_date < reference:
        if task.status != TaskStatus.OVERDUE:
            task.status_before_overdue = calculate_overall_status(task)
        task.status = TaskStatus.OVERDUE
    elif task.status == TaskStatus.OVERDUE:
        if task.due_date and task.due_date >= reference:
            previous_status = task.status_before_overdue or calculate_overall_status(task)
            task.status = previous_status
            task.status_before_overdue = None
        elif task.due_date is None:
            previous_status = task.status_before_overdue or calculate_overall_status(task)
            task.status = previous_status
            task.status_before_overdue = None
    else:
        recalc_task_status(task)


def refresh_all_tasks_statuses(reference: Optional[datetime] = None) -> None:
    """Обновляет статусы всех задач."""

    for task in TASKS.values():
        refresh_task_status(task, reference)


def get_involved_tasks(user_id: int) -> List[Task]:
    """Возвращает задачи, в которых участвует пользователь."""

    refresh_all_tasks_statuses()
    return [task for task in TASKS.values() if is_user_involved(task, user_id)]


def record_task_action(task: Task, user_id: int, action: str) -> None:
    """Фиксирует последнее действие по задаче."""

    task.last_action = action
    task.last_actor_id = user_id
    task.last_action_time = datetime.now()


def get_task_participants(task: Task) -> Set[int]:
    """Возвращает множество участников задачи."""

    participants: Set[int] = {task.author_id}
    if task.responsible_user_id:
        participants.add(task.responsible_user_id)
    participants.update(task.workgroup)
    return participants


def ensure_participant_entry(task: Task, user_id: int) -> None:
    """Гарантирует наличие записи о статусе участника."""

    if user_id not in task.participant_statuses:
        task.participant_statuses[user_id] = TaskStatus.NEW


def set_participant_status(task: Task, user_id: int, status: TaskStatus) -> None:
    """Устанавливает индивидуальный статус участника."""

    ensure_participant_entry(task, user_id)
    task.participant_statuses[user_id] = status
    if user_id != task.author_id:
        _sync_author_status(task)


def set_all_participants_status(task: Task, status: TaskStatus) -> None:
    """Устанавливает единый статус для всех участников."""

    for participant_id in get_task_participants(task):
        set_participant_status(task, participant_id, status)
    _sync_author_status(task)


def get_participant_status(task: Task, user_id: int) -> TaskStatus:
    """Возвращает статус участника задачи."""

    ensure_participant_entry(task, user_id)
    return task.participant_statuses[user_id]


def get_personal_status_for_user(task: Task, user_id: Optional[int]) -> TaskStatus:
    """Возвращает статус задачи для конкретного пользователя."""

    if user_id is None:
        return task.status

    if user_id not in get_task_participants(task):
        return task.status

    ensure_participant_entry(task, user_id)
    return task.participant_statuses[user_id]


def _sync_author_status(task: Task) -> None:
    """Синхронизирует статус автора с текущей активностью участников."""

    participants = [
        participant_id
        for participant_id in get_task_participants(task)
        if participant_id != task.author_id
    ]

    # Если других участников нет, оставляем статус автора без изменений.
    if not participants:
        return

    ensure_participant_entry(task, task.author_id)

    if task.awaiting_author_confirmation and task.pending_confirmations:
        task.participant_statuses[task.author_id] = TaskStatus.IN_REVIEW
        return

    participant_statuses = [
        get_participant_status(task, participant_id)
        for participant_id in participants
    ]

    if any(status == TaskStatus.ACTIVE for status in participant_statuses):
        task.participant_statuses[task.author_id] = TaskStatus.ACTIVE
        return

    if any(status == TaskStatus.PAUSED for status in participant_statuses):
        task.participant_statuses[task.author_id] = TaskStatus.PAUSED
        return

    if all(status == TaskStatus.COMPLETED for status in participant_statuses):
        task.participant_statuses[task.author_id] = TaskStatus.COMPLETED
        return

    task.participant_statuses[task.author_id] = TaskStatus.NEW


def calculate_overall_status(task: Task) -> TaskStatus:
    """Определяет общий статус задачи на основе действий участников."""

    participants = [
        get_participant_status(task, participant_id)
        for participant_id in get_task_participants(task)
        if participant_id != task.author_id
    ]

    if task.awaiting_author_confirmation and task.pending_confirmations:
        return TaskStatus.IN_REVIEW

    if not participants:
        return TaskStatus.NEW

    if all(status == TaskStatus.COMPLETED for status in participants):
        return TaskStatus.COMPLETED

    if any(status == TaskStatus.ACTIVE for status in participants):
        return TaskStatus.ACTIVE

    if any(status == TaskStatus.PAUSED for status in participants):
        return TaskStatus.PAUSED

    if any(status == TaskStatus.NEW for status in participants):
        return TaskStatus.NEW

    return TaskStatus.NEW


def recalc_task_status(task: Task) -> None:
    """Пересчитывает общий статус задачи."""

    new_status = calculate_overall_status(task)
    if task.status == TaskStatus.OVERDUE:
        task.status_before_overdue = new_status
    else:
        task.status = new_status
        task.status_before_overdue = None
    _sync_author_status(task)


def add_pending_confirmation(task: Task, user_id: int) -> None:
    """Добавляет участника в список ожидающих подтверждения автора."""

    task.pending_confirmations.add(user_id)
    task.awaiting_author_confirmation = True
    recalc_task_status(task)


def remove_pending_confirmation(task: Task, user_id: int) -> None:
    """Удаляет участника из списка ожидающих подтверждения."""

    if user_id in task.pending_confirmations:
        task.pending_confirmations.remove(user_id)
    if not task.pending_confirmations:
        task.awaiting_author_confirmation = False
    recalc_task_status(task)


def clear_pending_confirmations(task: Task) -> None:
    """Очищает список ожиданий подтверждения автором."""

    task.pending_confirmations.clear()
    task.awaiting_author_confirmation = False
    recalc_task_status(task)
