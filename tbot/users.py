"""Данные пользователей системы задач."""

from dataclasses import dataclass
from typing import Optional, Dict, Tuple


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


# Направления пользователей
USER_DIRECTIONS: Dict[int, Tuple[str, ...]] = {
    1311714242: ("СТН",),
    609995295: ("Все направления",),
    459228268: ("НОиМ",),
    5055233726: ("СТН",),
    7216096348: ("СТН",),
    678543417: ("НМСД", "ОАН", "СТН"),
    5575874649: ("СТН", "НиА"),
    7247710860: ("ОАН", "НОиМ", "НМСД", "НиА"),
}


def get_users_by_direction(direction: str) -> list[User]:
    """Возвращает список пользователей по направлению."""
    users = []
    direction_key = direction.upper()
    
    for user_id, user_directions in USER_DIRECTIONS.items():
        if direction_key in user_directions or "Все направления" in user_directions:
            if user_id in USERS:
                users.append(USERS[user_id])
    
    return users


def is_user_in_direction(user_id: int, direction: str) -> bool:
    """Проверяет, принадлежит ли пользователь к направлению."""
    if user_id not in USER_DIRECTIONS:
        return False
    
    user_directions = USER_DIRECTIONS[user_id]
    direction_key = direction.upper()
    
    return direction_key in user_directions or "Все направления" in user_directions