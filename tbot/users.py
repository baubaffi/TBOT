"""Данные пользователей системы задач."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True, slots=True)
class User:
    """Описание пользователя системы задач."""

    user_id: int
    full_name: str
    role: Optional[str] = None
    username: Optional[str] = None

    @property
    def first_name(self) -> str:
        """Возвращает имя пользователя без фамилии."""
        return self.full_name.split()[0]


USERS: Dict[int, User] = {
    1311714242: User(
        user_id=1311714242,
        full_name="Ольга Храмцова",
        role="Дебошир",
        username="@gavblya",
    ),
    609995295: User(
        user_id=609995295,
        full_name="Илья Колпаков",
        username="@kolpak_i",
    ),
    459228268: User(
        user_id=459228268,
        full_name="Павел Шульгин",
        username="@Zulgin97",
    ),
    5055233726: User(
        user_id=5055233726,
        full_name="Анастасия",
        username="@hihiololo",
    ),
    7216096348: User(
        user_id=7216096348,
        full_name="Владислав Уткин",
        username="@respectoKotE3",
    ),
    678543417: User(
        user_id=678543417,
        full_name="Дарья Домрачева",
        username="@danny_gate",
    ),
    5575874649: User(
        user_id=5575874649,
        full_name="Любовь Зенченко",
        username="@Lubavaablin",
    ),
    7247710860: User(
        user_id=7247710860,
        full_name="Александр Пинаев",
        role="Администратор системы задач",
    ),
}


# Словарь направлений и человеко-понятных названий
DIRECTION_LABELS: Dict[str, str] = {
    "all": "Все направления",
    "stn": "Социально-творческое направление (СТН)",
    "oan": "Организационно-аналитическое направление (ОАН)",
    "nmsd": "Направление маркетинга, смм, дизайна (НМСД)",
    "noim": "Направление обучения и методологии (НОиМ)",
    "nnia": "Направление набора и адаптации (ННиА)",
}


# Направления пользователей (используем коды направлений)
USER_DIRECTIONS: Dict[int, tuple[str, ...]] = {
    1311714242: ("stn",),
    609995295: ("all",),
    459228268: ("noim",),
    5055233726: ("stn",),
    7216096348: ("stn",),
    678543417: ("nmsd", "oan", "stn"),
    5575874649: ("stn", "nnia"),
    7247710860: ("oan", "noim", "nmsd", "nnia"),
}


def _normalize_direction(direction: str) -> Optional[str]:
    """Приводит значение направления к стандартному коду."""

    if not direction:
        return None

    normalized = direction.strip().lower()

    # Сначала пытаемся найти точное совпадение с кодом
    if normalized in DIRECTION_LABELS:
        return normalized

    # Проверяем совпадение с полным названием направления
    for code, label in DIRECTION_LABELS.items():
        label_lower = label.lower()
        if normalized == label_lower:
            return code

        # Учитываем короткое обозначение в скобках
        if "(" in label_lower and ")" in label_lower:
            short_name = label_lower.split("(")[-1].split(")")[0].strip()
            if normalized == short_name:
                return code

        # Учитываем форму без скобок и лишних символов
        stripped_label = label_lower.split("(")[0].strip()
        if normalized == stripped_label:
            return code

    # Дополнительные ручные алиасы для часто встречающихся вариантов
    aliases = {
        "ниа": "nnia",
        "нна": "nnia",
        "нниа": "nnia",
        "все": "all",
    }

    return aliases.get(normalized)


def get_direction_label(direction: str) -> str:
    """Возвращает человеко-понятное название направления."""

    code = _normalize_direction(direction)
    if code is None:
        return direction
    return DIRECTION_LABELS[code]


def get_users_by_direction(direction: str) -> List[User]:
    """Возвращает список пользователей по направлению."""

    code = _normalize_direction(direction)
    if code is None:
        return []

    if code == "all":
        return list(USERS.values())

    result: List[User] = []

    for user_id, user_directions in USER_DIRECTIONS.items():
        if code in user_directions or "all" in user_directions:
            user = USERS.get(user_id)
            if user is not None:
                result.append(user)

    return result


def is_user_in_direction(user_id: int, direction: str) -> bool:
    """Проверяет, принадлежит ли пользователь к направлению."""

    code = _normalize_direction(direction)
    if code is None:
        return False

    user_directions = USER_DIRECTIONS.get(user_id, ())
    return code in user_directions or "all" in user_directions
