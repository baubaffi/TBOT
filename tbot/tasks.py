"""Модуль для работы с задачами."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable, List, Optional


class TaskStatus(Enum):
    """Статусы задач."""

    NEW = "Новая"
    ACTIVE = "В работе"
    PAUSED = "На паузе"
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
        is_private=is_private
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
            task.status_before_overdue = task.status
        task.status = TaskStatus.OVERDUE
    elif task.status == TaskStatus.OVERDUE:
        if task.due_date and task.due_date >= reference:
            task.status = task.status_before_overdue or TaskStatus.NEW
            task.status_before_overdue = None
        elif task.due_date is None:
            task.status = task.status_before_overdue or TaskStatus.NEW
            task.status_before_overdue = None


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
