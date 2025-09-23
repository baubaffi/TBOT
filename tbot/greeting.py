"""Логика приветствия пользователя при входе."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time
from typing import Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

from .users import USERS, User

LOGGER = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True, slots=True)
class TimeRange:
    """Диапазон времени, в пределах которого действует приветствие."""

    start: time
    end: time
    greeting: str

    def includes(self, dt: datetime) -> bool:
        """Проверяет, попадает ли время в диапазон."""

        # Для диапазонов, пересекающих полночь, обрабатываем отдельно
        if self.start <= self.end:
            return self.start <= dt.time() <= self.end
        return dt.time() >= self.start or dt.time() <= self.end


def _build_time_ranges() -> Iterable[TimeRange]:
    """Создаёт набор диапазонов времени для приветствий."""

    # Границы включительные, поэтому берём минуты 59 для завершения диапазона
    return (
        TimeRange(time(5, 0), time(10, 59), "Доброе утро"),
        TimeRange(time(11, 0), time(16, 59), "Добрый день"),
        TimeRange(time(17, 0), time(22, 59), "Добрый вечер"),
        TimeRange(time(23, 0), time(23, 59), "Доброй ночи"),
        TimeRange(time(0, 0), time(4, 59), "Доброй ночи"),
    )


TIME_RANGES: tuple[TimeRange, ...] = tuple(_build_time_ranges())


def determine_greeting(dt: datetime) -> str:
    """Возвращает приветствие в зависимости от времени суток."""

    # Если время пришло без таймзоны, переводим его в московскую
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MOSCOW_TZ)
    else:
        dt = dt.astimezone(MOSCOW_TZ)

    for time_range in TIME_RANGES:
        if time_range.includes(dt):
            return time_range.greeting

    # Сюда мы не должны попадать, но на всякий случай оставим дефолт
    LOGGER.debug("Не найден подходящий диапазон времени, используется дефолтное приветствие")
    return "Здравствуйте"


def greet_user(
    user_id: int,
    current_time: Optional[datetime] = None,
    users: Mapping[int, User] = USERS,
) -> str:
    """Формирует приветствие для пользователя или сообщает об ограничении доступа."""

    # Получаем текущее время в московской таймзоне
    now = (current_time or datetime.now(tz=MOSCOW_TZ))
    if now.tzinfo is None:
        now = now.replace(tzinfo=MOSCOW_TZ)
    else:
        now = now.astimezone(MOSCOW_TZ)

    user = users.get(user_id)
    if user is None:
        # Логируем попытку доступа не из белого списка
        LOGGER.warning("Попытка доступа от неизвестного пользователя: %s", user_id)
        return "Доступ ограничен. Обратитесь к администратору системы задач."

    greeting = determine_greeting(now)
    first_name = user.first_name
    return f"{greeting}, {first_name}!"
