"""Логика статусов и уведомлений для системы задач."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Mapping, Sequence, Set


class PersonalStatus(Enum):
    """Персональные статусы участника задачи."""

    NEW = "new"
    IN_PROGRESS = "in_progress"
    ON_REVIEW = "on_review"
    CONFIRMED = "confirmed"
    DONE = "done"


class GlobalStatus(Enum):
    """Глобальный статус задачи в общем списке."""

    NEW = "new"
    IN_PROGRESS = "in_progress"
    ON_REVIEW = "on_review"
    COMPLETED = "completed"


@dataclass(frozen=True)
class ActivityEntry:
    """Запись лога действий по задаче."""

    actor_id: int
    description: str
    is_status_change: bool = False
    related_participants: frozenset[int] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        """Нормализует участников, связанных с событием."""

        # В источниках данных поле может приходить в разных форматах или вовсе быть пустым.
        # Приводим его к неизменяемому набору, чтобы дальнейшая логика работала стабильно.
        participants = self.related_participants
        if not participants:
            object.__setattr__(self, "related_participants", frozenset())
            return

        if not isinstance(participants, frozenset):
            object.__setattr__(self, "related_participants", frozenset(participants))


def personal_section(status: PersonalStatus) -> str:
    """Возвращает название персонального раздела для статуса."""

    section_titles = {
        PersonalStatus.NEW: "Новые",
        PersonalStatus.IN_PROGRESS: "В работе",
        PersonalStatus.ON_REVIEW: "На проверке",
        PersonalStatus.CONFIRMED: "Выполненные",
        PersonalStatus.DONE: "Выполненные",
    }
    return section_titles[status]


def personal_sections_for_participants(
    participant_statuses: Mapping[int, PersonalStatus]
) -> Dict[int, str]:
    """Возвращает отображение участника к названию персонального раздела."""

    # Каждый участник видит задачу в разделе, который соответствует его статусу.
    return {
        participant_id: personal_section(status)
        for participant_id, status in participant_statuses.items()
    }


def visible_participants(participants: Iterable[int], author_id: int) -> List[int]:
    """Возвращает список участников без автора."""

    return [participant_id for participant_id in participants if participant_id != author_id]


def should_show_take_button(author_id: int, responsible_id: int | None, user_id: int) -> bool:
    """Определяет, нужно ли показывать кнопку «Взять в работу» пользователю."""

    if user_id != author_id:
        return True

    if responsible_id is None:
        return True

    return author_id != responsible_id


def calculate_global_status(
    participant_statuses: Sequence[PersonalStatus],
    *,
    manual_completed: bool = False,
) -> GlobalStatus:
    """Вычисляет глобальный статус задачи по статусам участников."""

    if manual_completed:
        return GlobalStatus.COMPLETED

    if not participant_statuses:
        return GlobalStatus.NEW

    if all(status == PersonalStatus.NEW for status in participant_statuses):
        return GlobalStatus.NEW

    if all(status in {PersonalStatus.CONFIRMED, PersonalStatus.DONE} for status in participant_statuses):
        return GlobalStatus.COMPLETED

    if all(
        status in {PersonalStatus.ON_REVIEW, PersonalStatus.CONFIRMED, PersonalStatus.DONE}
        for status in participant_statuses
    ):
        return GlobalStatus.ON_REVIEW

    return GlobalStatus.IN_PROGRESS


def recipients_on_take(author_id: int, responsible_id: int | None, actor_id: int) -> Set[int]:
    """Возвращает пользователей, которых нужно уведомить при взятии задачи в работу."""

    recipients: Set[int] = set()

    if author_id != actor_id:
        recipients.add(author_id)

    if responsible_id and responsible_id != actor_id:
        recipients.add(responsible_id)

    return recipients


def recipients_on_confirmation(
    author_id: int,
    responsible_id: int | None,
    actor_id: int,
    participant_id: int,
) -> Set[int]:
    """Возвращает пользователей, которых нужно уведомить при подтверждении выполнения."""

    recipients: Set[int] = {participant_id}

    if author_id != actor_id:
        recipients.add(author_id)

    if responsible_id and responsible_id != actor_id:
        recipients.add(responsible_id)

    return recipients


def filter_activity_feed(
    entries: Iterable[ActivityEntry],
    *,
    viewer_id: int,
    author_id: int,
) -> List[ActivityEntry]:
    """Фильтрует записи лога для отображения пользователю."""

    if viewer_id == author_id:
        return list(entries)

    visible: List[ActivityEntry] = []
    for entry in entries:
        if entry.actor_id == viewer_id:
            visible.append(entry)
            continue

        if not entry.is_status_change:
            continue

        if viewer_id not in entry.related_participants:
            continue

        if entry.actor_id == author_id and len(entry.related_participants) > 1:
            continue

        visible.append(entry)

    return visible

