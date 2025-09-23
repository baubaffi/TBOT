"""Тесты для модуля приветствий."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tbot.greeting import determine_greeting, greet_user
from tbot.users import User

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def test_determine_greeting_ranges():
    """Проверяем, что каждый диапазон времени возвращает корректное приветствие."""

    cases = [
        (datetime(2024, 1, 1, 5, 0, tzinfo=MOSCOW_TZ), "Доброе утро"),
        (datetime(2024, 1, 1, 10, 59, tzinfo=MOSCOW_TZ), "Доброе утро"),
        (datetime(2024, 1, 1, 11, 0, tzinfo=MOSCOW_TZ), "Добрый день"),
        (datetime(2024, 1, 1, 16, 59, tzinfo=MOSCOW_TZ), "Добрый день"),
        (datetime(2024, 1, 1, 17, 0, tzinfo=MOSCOW_TZ), "Добрый вечер"),
        (datetime(2024, 1, 1, 22, 59, tzinfo=MOSCOW_TZ), "Добрый вечер"),
        (datetime(2024, 1, 1, 23, 0, tzinfo=MOSCOW_TZ), "Доброй ночи"),
        (datetime(2024, 1, 2, 4, 59, tzinfo=MOSCOW_TZ), "Доброй ночи"),
        (datetime(2024, 1, 1, 2, 0, tzinfo=MOSCOW_TZ), "Доброй ночи"),
    ]

    for dt, expected in cases:
        assert determine_greeting(dt) == expected


def test_greet_user_known_user(monkeypatch):
    """Проверяем формирование приветствия для пользователя из белого списка."""

    fake_time = datetime(2024, 1, 1, 12, 0, tzinfo=MOSCOW_TZ)
    user = User(user_id=1, full_name="Тест Пользователь")
    message = greet_user(1, current_time=fake_time, users={1: user})
    assert message == "Добрый день, Тест!"


def test_greet_user_unknown_user_logs_warning(caplog):
    """Неизвестный пользователь получает сообщение об ограничении доступа."""

    fake_time = datetime(2024, 1, 1, 12, 0, tzinfo=MOSCOW_TZ)
    with caplog.at_level("WARNING"):
        message = greet_user(999, current_time=fake_time, users={})
    assert message == "Доступ ограничен. Обратитесь к администратору системы задач."
    assert "Попытка доступа" in caplog.text


def test_greet_user_handles_naive_datetime():
    """Проверяем, что функция корректно обрабатывает наивные даты."""

    fake_time = datetime(2024, 1, 1, 9, 0)  # без таймзоны
    user = User(user_id=2, full_name="Иван Иванов")
    message = greet_user(2, current_time=fake_time, users={2: user})
    assert message == "Доброе утро, Иван!"
