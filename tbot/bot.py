"""Инструменты для запуска и настройки телеграм-бота."""
from __future__ import annotations

# Убираем сложный код совместимости и делаем просто
from aiogram import Bot

import asyncio
import importlib.util
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable
from .greeting import greet_user
from .users import USERS, User, get_direction_label, get_users_by_direction
from .task_logic import should_show_take_button
from .tasks import (
    Task,
    TaskPriority,
    TaskStatus,
    TASKS,
    add_pending_confirmation,
    clear_pending_confirmations,
    create_task,
    delete_task as remove_task,
    get_involved_tasks,
    get_participant_status,
    get_task_participants,
    is_user_involved,
    record_task_action,
    recalc_task_status,
    refresh_all_tasks_statuses,
    refresh_task_status,
    remove_pending_confirmation,
    set_all_participants_status,
    set_participant_status,
)

LOGGER = logging.getLogger(__name__)

# Проверяем наличие зависимости
if importlib.util.find_spec("aiogram") is None:
    raise RuntimeError(
        "Для работы телеграм-бота требуется установить пакет aiogram. "
        "Добавьте его в окружение командой 'pip install aiogram'."
    )

from aiogram import Dispatcher, F  # noqa: E402
from aiogram.filters import CommandStart, Command  # noqa: E402
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery  # noqa: E402
from aiogram.fsm.context import FSMContext  # noqa: E402
from aiogram.fsm.state import State, StatesGroup  # noqa: E402
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest

# Списки проектов и направлений
PROJECTS = {
    "crmk": "ЦРМК Буколпак",
    "kinoclub": "Киноклуб Кадр",
    "anticafe": "Антикафе Ковёр",
    "literature": "Литературный клуб Переплёт",
    "boardgames": "Проект Настолки с ведущим",
    "podcast": "Подкаст Десятиминутка",
    "tourism": "Туристический проект Цифровой Торжокъ",
    "vinyl": "Творческий проект Винил",
    "caps": "Проект Колпачки",
    "quizzes": "Квизы",
}

DIRECTIONS = {
    "all": "Все направления",
    "stn": "Социально-творческое направление (СТН)",
    "oan": "Организационно-аналитическое направление (ОАН)",
    "nmsd": "Направление маркетинга, смм, дизайна (НМСД)",
    "noim": "Направление обучения и методологии (НОиМ)",
    "nnia": "Направление набора и адаптации (ННиА)",
}


# Вспомогательная функция для отображения названия направления
def direction_title(direction_id: str) -> str:
    """Возвращает название направления без сокращения в скобках."""

    label = get_direction_label(direction_id)
    if "(" in label and ")" in label:
        return label.split("(")[0].strip()
    return label

# Состояния для создания задачи
class TaskCreation(StatesGroup):
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_due_date = State()
    waiting_for_priority = State()
    waiting_for_project = State()
    waiting_for_direction = State()
    waiting_for_responsible = State()
    waiting_for_workgroup = State()
    waiting_for_privacy = State()


class TaskUpdate(StatesGroup):
    waiting_for_postpone_date = State()
    waiting_for_postpone_reason = State()


@dataclass(slots=True)
class BotConfig:
    """Конфигурация запуска бота."""

    token: str
    drop_pending_updates: bool = True


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    try:
        admin_id = int(os.getenv("TELEGRAM_ADMIN_ID", 0))
        return user_id == admin_id
    except (ValueError, TypeError):
        return False


def parse_date(date_str: str) -> datetime | None:
    """Парсит дату из строки в формате ДД.ММ.ГГГГ или ДД-ММ-ГГГГ."""
    try:
        # Заменяем точки и дефисы на точки для единообразия
        date_str = date_str.replace('-', '.')
        return datetime.strptime(date_str, '%d.%m.%Y')
    except ValueError:
        return None


def calculate_due_date(priority: TaskPriority, created_date: datetime) -> datetime:
    """Рассчитывает дату выполнения на основе приоритета."""
    priority_days = {
        TaskPriority.CRITICAL: 1,
        TaskPriority.HIGH: 3,
        TaskPriority.MEDIUM: 10,
        TaskPriority.LOW: 15,
    }
    days = priority_days.get(priority, 10)
    return created_date + timedelta(days=days)


# Главное меню (Inline кнопки)
def main_menu_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Список задач", callback_data="all_tasks"),
                InlineKeyboardButton(text="👤 Мои задачи", callback_data="my_tasks")
            ],
            [
                InlineKeyboardButton(text="➕ Добавить задачу", callback_data="add_task")
            ],
            [
                InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")
            ]
        ]
    )


# Меню фильтров для списка задач
def tasks_filter_kb(back_to: str = "main"):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Активные", callback_data="filter_active"),
                InlineKeyboardButton(text="На проверке", callback_data="filter_review"),
            ],
            [
                InlineKeyboardButton(text="Завершенные", callback_data="filter_completed"),
                InlineKeyboardButton(text="Все задачи", callback_data="filter_all"),
            ],
            [
                InlineKeyboardButton(text="🏠 Главная", callback_data=f"back_{back_to}")
            ]
        ]
    )


# Сопоставления для отображения статусов и приоритетов
STATUS_ICONS = {
    TaskStatus.NEW: "🆕",
    TaskStatus.ACTIVE: "🔄",
    TaskStatus.PAUSED: "⏸️",
    TaskStatus.IN_REVIEW: "🔍",
    TaskStatus.COMPLETED: "✅",
    TaskStatus.OVERDUE: "⏰",
}

PRIORITY_ICONS = {
    TaskPriority.CRITICAL: "🔴",
    TaskPriority.HIGH: "🟠",
    TaskPriority.MEDIUM: "🟡",
    TaskPriority.LOW: "🟢",
}

TASKS_PER_PAGE = 5


# Меню приоритетов
def priority_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔴 Критический (1 день)", callback_data="priority_critical"),
            ],
            [
                InlineKeyboardButton(text="🟠 Высокий (3 дня)", callback_data="priority_high"),
            ],
            [
                InlineKeyboardButton(text="🟡 Средний (10 дней)", callback_data="priority_medium"),
            ],
            [
                InlineKeyboardButton(text="🟢 Низкий (15 дней)", callback_data="priority_low"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back_task_creation"),
            ]
        ]
    )


# Меню проектов
def projects_kb():
    buttons = []
    row = []
    
    for project_id, project_name in PROJECTS.items():
        row.append(InlineKeyboardButton(text=project_name, callback_data=f"project_{project_id}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_task_creation")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Меню направлений
def directions_kb():
    buttons = []
    row = []
    
    for direction_id, direction_name in DIRECTIONS.items():
        row.append(InlineKeyboardButton(text=direction_name, callback_data=f"direction_{direction_id}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_task_creation")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Меню выбора пользователей
def users_kb(users: list[User], selected_users: set[int], action: str, back_to: str):
    buttons = []
    
    for user in users:
        selected = "✅ " if user.user_id in selected_users else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{selected}{user.full_name}",
                callback_data=f"{action}_{user.user_id}"
            )
        ])
    
    buttons.append([
        InlineKeyboardButton(text="✅ Готово", callback_data=f"done_{action}"),
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_{back_to}")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Меню приватности
def privacy_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔒 Приватная", callback_data="privacy_private"),
                InlineKeyboardButton(text="🌐 Публичная", callback_data="privacy_public"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back_workgroup"),
            ]
        ]
    )


# Построение клавиатуры списка задач
def tasks_list_kb(tasks: list[Task], view: str, filter_type: str, page: int):
    """Создает клавиатуру со списком задач и пагинацией."""

    buttons: list[list[InlineKeyboardButton]] = []
    start_index = (page - 1) * TASKS_PER_PAGE
    page_tasks = tasks[start_index:start_index + TASKS_PER_PAGE]

    for idx, task in enumerate(page_tasks, start=start_index + 1):
        buttons.append([
            InlineKeyboardButton(
                text=f"{idx}. {task.title}",
                callback_data=f"task_detail:{task.task_id}:{view}:{filter_type}:{page}",
            )
        ])

    navigation_row: list[InlineKeyboardButton] = []
    if page > 1:
        navigation_row.append(InlineKeyboardButton(text="◀️", callback_data=f"tasks_page:{view}:{filter_type}:{page - 1}"))
    if start_index + len(page_tasks) < len(tasks):
        navigation_row.append(InlineKeyboardButton(text="▶️", callback_data=f"tasks_page:{view}:{filter_type}:{page + 1}"))
    if navigation_row:
        buttons.append(navigation_row)

    buttons.append([
        InlineKeyboardButton(text="📋 Фильтры", callback_data=f"tasks_filters:{view}"),
    ])
    buttons.append([
        InlineKeyboardButton(text="🏠 Главная", callback_data="back_main"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def task_detail_kb(task: Task, viewer_id: int, view: str, filter_type: str, page: int):
    """Создает клавиатуру действий на экране деталей задачи."""

    buttons: list[list[InlineKeyboardButton]] = []
    context = f"{task.task_id}:{view}:{filter_type}:{page}"
    is_author = viewer_id == task.author_id
    is_responsible = viewer_id == task.responsible_user_id
    in_workgroup = viewer_id in task.workgroup
    is_current_executor = task.current_executor_id == viewer_id
    awaiting_confirmation = task.awaiting_author_confirmation

    show_controls = task.status != TaskStatus.COMPLETED or awaiting_confirmation

    if show_controls:
        if is_current_executor:
            buttons.append([
                InlineKeyboardButton(text="✅ Завершить", callback_data=f"complete_task:{context}"),
                InlineKeyboardButton(text="⏸️ Пауза", callback_data=f"pause_task:{context}"),
            ])
            buttons.append([
                InlineKeyboardButton(text="🕒 Отложить", callback_data=f"postpone_task:{context}"),
            ])
        else:
            if not is_author and not awaiting_confirmation:
                buttons.append([
                    InlineKeyboardButton(text="🔄 Взять в работу", callback_data=f"take_task:{context}"),
                ])

            management_row: list[InlineKeyboardButton] = []

            if is_author or is_responsible:
                management_row.append(
                    InlineKeyboardButton(text="🕒 Отложить", callback_data=f"postpone_task:{context}")
                )
                management_row.append(
                    InlineKeyboardButton(text="⏸️ Пауза", callback_data=f"pause_task:{context}")
                )
            elif in_workgroup:
                management_row.append(
                    InlineKeyboardButton(text="🕒 Отложить", callback_data=f"postpone_task:{context}")
                )

            if management_row:
                buttons.append(management_row)

            if is_author and not is_current_executor:
                buttons.append([
                    InlineKeyboardButton(text="♻️ Сброс состояния", callback_data=f"reset_task_request:{context}"),
                ])

        reminder_targets = get_allowed_reminder_targets(task, viewer_id)
        if reminder_targets:
            buttons.append([
                InlineKeyboardButton(text="🔔 Напомнить всем", callback_data=f"remind_all:{context}"),
            ])
            for participant_id in sorted(reminder_targets):
                participant_name = get_user_full_name(participant_id)
                buttons.append([
                    InlineKeyboardButton(
                        text=f"🔔 Напомнить: {participant_name}",
                        callback_data=(
                            f"remind_one:{task.task_id}:{participant_id}:{view}:{filter_type}:{page}"
                        ),
                    )
                ])

    if is_author and task.status != TaskStatus.COMPLETED:
        buttons.append([
            InlineKeyboardButton(text="🏁 Завершить задачу", callback_data=f"complete_task_author:{context}"),
        ])

    if is_author and task.pending_confirmations:
        for participant_id in sorted(task.pending_confirmations):
            participant_name = get_user_full_name(participant_id)
            buttons.append([
                InlineKeyboardButton(
                    text=f"✅ Подтвердить: {participant_name}",
                    callback_data=(
                        f"confirm_completion:{task.task_id}:{participant_id}:{view}:{filter_type}:{page}"
                    ),
                )
            ])

    if is_author and (task.status == TaskStatus.COMPLETED or task.awaiting_author_confirmation):
        buttons.append([
            InlineKeyboardButton(text="🔄 Вернуть в работу", callback_data=f"return_task:{context}"),
        ])

    if is_author:
        buttons.append([
            InlineKeyboardButton(
                text="🗑️ Удалить/Отменить задачу",
                callback_data=f"delete_task:{task.task_id}:{view}:{filter_type}:{page}",
            )
        ])

    if view in {"all", "my"}:
        buttons.append([
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"tasks_page:{view}:{filter_type}:{page}"),
        ])

    buttons.append([
        InlineKeyboardButton(text="🏠 Главная", callback_data="back_main"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_user_full_name(user_id: int) -> str:
    """Возвращает полное имя пользователя или понятную заглушку."""

    user = USERS.get(user_id)
    if user is None:
        return "Неизвестный"
    return user.full_name


def detect_user_role(task: Task, user_id: int) -> str:
    """Определяет роль пользователя в задаче."""

    if user_id == task.responsible_user_id:
        return "responsible"
    if user_id == task.author_id:
        return "author"
    if user_id in task.workgroup:
        return "workgroup"
    return "viewer"


def get_allowed_reminder_targets(task: Task, actor_id: int) -> set[int]:
    """Возвращает список пользователей, которым можно отправить напоминание."""

    role = detect_user_role(task, actor_id)
    if role not in {"author", "responsible"}:
        return set()

    participants = set(get_task_participants(task))
    participants.discard(actor_id)

    if role == "responsible":
        participants.discard(task.author_id)

    return participants


def _notification_open_keyboard(task: Task) -> InlineKeyboardMarkup:
    """Создаёт клавиатуру с кнопкой открытия задачи и возвратом на главную."""

    context = f"{task.task_id}:notify:all:1"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📂 Открыть задачу",
                    callback_data=f"task_detail:{context}",
                )
            ],
            [InlineKeyboardButton(text="🏠 Главная", callback_data="back_main")],
        ]
    )


def _notification_review_keyboard(
    task: Task,
    performer_id: int,
    performer_name: str,
) -> InlineKeyboardMarkup:
    """Создаёт клавиатуру уведомления с подтверждением выполнения."""

    context = f"{task.task_id}:notify:all:1"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📂 Открыть задачу",
                    callback_data=f"task_detail:{context}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"✅ Подтвердить выполнение: {performer_name}",
                    callback_data=(
                        f"confirm_completion:{task.task_id}:{performer_id}:notify:all:1"
                    ),
                )
            ],
            [InlineKeyboardButton(text="🏠 Главная", callback_data="back_main")],
        ]
    )


async def notify_task_participants(
    bot: Bot,
    task: Task,
    actor_id: int,
    action_description: str,
    keyboard_builder: Callable[[int], InlineKeyboardMarkup | None] | None = None,
) -> None:
    """Отправляет уведомление всем участникам о действии по задаче."""

    actor_name = get_user_full_name(actor_id)
    notification_text = (
        "ℹ️ <b>Изменение по задаче</b>\n\n"
        f"📝 <b>{task.title}</b>\n"
        f"👤 {actor_name} {action_description}"
    )

    recipients = set(get_task_participants(task))

    for recipient_id in recipients:
        user = USERS.get(recipient_id)
        if user is None:
            continue
        reply_markup = None
        if keyboard_builder is not None:
            reply_markup = keyboard_builder(recipient_id)
        try:
            await bot.send_message(
                chat_id=recipient_id,
                text=notification_text,
                reply_markup=reply_markup,
            )
        except Exception as error:
            LOGGER.error(
                "Не удалось отправить уведомление пользователю %s: %s",
                recipient_id,
                error,
            )


def _build_take_notification_keyboard(
    task: Task,
    actor_id: int,
    recipient_id: int,
) -> InlineKeyboardMarkup | None:
    """Подбирает клавиатуру уведомления, когда участник взял задачу."""

    if recipient_id == actor_id:
        return None
    if recipient_id not in {task.author_id, task.responsible_user_id}:
        return None
    return _notification_open_keyboard(task)


def _build_review_notification_keyboard(
    task: Task,
    performer_id: int,
    recipient_id: int,
) -> InlineKeyboardMarkup | None:
    """Подбирает клавиатуру уведомления при отправке работы на проверку."""

    if recipient_id == performer_id:
        return None
    if recipient_id not in {task.author_id, task.responsible_user_id}:
        return None
    if recipient_id == task.responsible_user_id:
        performer_name = get_user_full_name(performer_id)
        return _notification_review_keyboard(task, performer_id, performer_name)
    return _notification_open_keyboard(task)


def build_reminder_keyboard(task: Task, recipient_id: int) -> InlineKeyboardMarkup:
    """Создаёт клавиатуру действий для напоминания по задаче."""

    buttons: list[list[InlineKeyboardButton]] = []
    context = f"{task.task_id}:notify:all:1"

    # Кнопка открытия подробной карточки задачи
    buttons.append([
        InlineKeyboardButton(
            text="📂 Открыть задачу",
            callback_data=f"task_detail:{context}",
        )
    ])

    role = detect_user_role(task, recipient_id)
    participant_status = get_participant_status(task, recipient_id)

    # Кнопку «Взять в работу» показываем только тем, кто может начать выполнение
    can_take = (
        role != "author"
        and task.status != TaskStatus.COMPLETED
        and not task.awaiting_author_confirmation
        and participant_status != TaskStatus.COMPLETED
    )
    if can_take:
        buttons.append([
            InlineKeyboardButton(
                text="🔄 Взять в работу",
                callback_data=f"take_task:{context}",
            )
        ])

    # Возможность переноса срока доступна автору, ответственному и рабочей группе
    if role in {"author", "responsible", "workgroup"}:
        buttons.append([
            InlineKeyboardButton(
                text="🕒 Отложить",
                callback_data=f"postpone_task:{context}",
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def send_task_reminder(
    bot: Bot,
    task: Task,
    actor_id: int,
    recipients: Iterable[int],
) -> None:
    """Отправляет напоминание выбранным участникам."""

    refresh_task_status(task)
    actor_name = get_user_full_name(actor_id)
    due_date = task.due_date.strftime('%d.%m.%Y') if task.due_date else "Не указан"
    reminder_text = (
        "🔔 <b>Напоминание о задаче</b>\n\n"
        f"📝 <b>{task.title}</b>\n"
        f"👤 От: {actor_name}\n"
        f"📆 Срок: {due_date}\n"
        f"📊 Статус: {task.status.value}\n\n"
        "Пожалуйста, уделите внимание выполнению задачи."
    )

    for recipient_id in recipients:
        user = USERS.get(recipient_id)
        if user is None:
            continue
        try:
            reminder_keyboard = build_reminder_keyboard(task, recipient_id)
            await bot.send_message(
                chat_id=recipient_id,
                text=reminder_text,
                reply_markup=reminder_keyboard,
            )
        except Exception as error:
            LOGGER.error(
                "Не удалось отправить напоминание пользователю %s: %s",
                recipient_id,
                error,
            )


def build_tasks_list_text(tasks: list[Task], filter_text: str, page: int) -> str:
    """Формирует текстовое представление списка задач с нумерацией."""

    total_pages = max(1, (len(tasks) + TASKS_PER_PAGE - 1) // TASKS_PER_PAGE)
    start_index = (page - 1) * TASKS_PER_PAGE
    page_tasks = tasks[start_index:start_index + TASKS_PER_PAGE]

    lines: list[str] = [f"📋 <b>{filter_text.capitalize()} задачи</b>"]
    lines.append("")

    for idx, task in enumerate(page_tasks, start=start_index + 1):
        refresh_task_status(task)
        status_icon = STATUS_ICONS.get(task.status, "❓")
        priority_icon = PRIORITY_ICONS.get(task.priority, "⚪")
        overdue_icon = "⏰ " if task.status == TaskStatus.OVERDUE else ""
        responsible_name = get_user_full_name(task.responsible_user_id)
        due_date = task.due_date.strftime('%d.%m.%Y') if task.due_date else "Без срока"

        lines.extend([
            f"{idx}. {status_icon} {priority_icon} {overdue_icon}<b>{task.title}</b>",
            f"   👤 {responsible_name}",
            f"   📅 {due_date}",
        ])

        if task.current_executor_id and task.current_executor_id in USERS:
            executor_name = get_user_full_name(task.current_executor_id)
            lines.append(f"   👷 Исполнитель: {executor_name}")

        lines.append("")

    lines.append(f"Страница {page} из {total_pages}")
    return "\n".join(lines)


def build_task_detail_text(task: Task, viewer_id: int | None = None) -> str:
    """Формирует подробное описание задачи."""

    refresh_task_status(task)
    viewer_role = "viewer"
    if viewer_id is not None:
        viewer_role = detect_user_role(task, viewer_id)

    responsible_name = get_user_full_name(task.responsible_user_id)
    author_name = get_user_full_name(task.author_id)
    due_date = task.due_date.strftime('%d.%m.%Y') if task.due_date else "Не указан"
    created = task.created_date.strftime('%d.%m.%Y')
    workgroup_names = [
        get_user_full_name(user_id)
        for user_id in task.workgroup
        if user_id in USERS
    ]
    workgroup_text = ", ".join(workgroup_names) if workgroup_names else "Не указана"
    description = task.description or "Не указано"
    project_name = PROJECTS.get(task.project, "Не указан")
    direction_name = get_direction_label(task.direction) if task.direction else "Не указано"
    status_icon = STATUS_ICONS.get(task.status, "❓")
    priority_icon = PRIORITY_ICONS.get(task.priority, "⚪")
    executor_name = None
    if task.current_executor_id and task.current_executor_id in USERS:
        executor_name = get_user_full_name(task.current_executor_id)

    lines = [
        f"📝 <b>{task.title}</b>",
        "",
        f"{status_icon} Статус: {task.status.value}",
        f"{priority_icon} Приоритет: {task.priority.value}",
        f"📄 Описание: {description}",
        f"📅 Создана: {created}",
        f"📆 Срок: {due_date}",
        f"🏢 Проект: {project_name}",
        f"🎯 Направление: {direction_name}",
        f"👤 Автор: {author_name}",
        f"✅ Ответственный: {responsible_name}",
        f"👥 Рабочая группа: {workgroup_text}",
    ]

    if executor_name:
        lines.append(f"👷 Исполнитель: {executor_name}")

    if viewer_role in {"author", "responsible"}:
        participant_lines: list[str] = []
        for participant_id in sorted(get_task_participants(task)):
            if (
                participant_id == task.author_id
                and participant_id != task.responsible_user_id
            ):
                continue

            participant_name = get_user_full_name(participant_id)
            if participant_id == task.author_id:
                role_label = "Автор"
            elif participant_id == task.responsible_user_id:
                role_label = "Ответственный"
            else:
                role_label = "Рабочая группа"
            participant_status_enum = get_participant_status(task, participant_id)
            if (
                participant_id == task.author_id
                and participant_id == task.responsible_user_id
            ):
                participant_status = "Ответственный"
            else:
                participant_status = participant_status_enum.value
            marker = ""
            if participant_id in task.pending_confirmations:
                marker = " (ожидает подтверждения)"
            participant_lines.append(
                f"   • {participant_name} ({role_label}) — {participant_status}{marker}"
            )

        if participant_lines:
            lines.append("👥 Статусы участников:")
            lines.extend(participant_lines)

    if task.awaiting_author_confirmation and task.pending_confirmations:
        pending_names = [
            get_user_full_name(participant_id)
            for participant_id in task.pending_confirmations
        ]
        lines.append(f"📨 На подтверждении: {', '.join(pending_names)}")

    if task.last_action and task.last_actor_id:
        actor_name = get_user_full_name(task.last_actor_id)
        if task.last_action_time:
            action_time = task.last_action_time.strftime('%d.%m.%Y %H:%M')
            lines.append(f"📌 Последнее действие: {task.last_action} — {actor_name} ({action_time})")
        else:
            lines.append(f"📌 Последнее действие: {task.last_action} — {actor_name}")

    if task.completed_date:
        lines.append(f"🏁 Завершена: {task.completed_date.strftime('%d.%m.%Y')}")

    return "\n".join(lines)


# Кнопки действий с задачей
def task_actions_kb(task: Task, viewer_id: int | None = None) -> InlineKeyboardMarkup:
    """Формирует клавиатуру действий с учетом роли пользователя."""

    context = f"{task.task_id}:notify:all:1"
    first_row: list[InlineKeyboardButton] = []

    if viewer_id is None or should_show_take_button(
        task.author_id,
        task.responsible_user_id or None,
        viewer_id,
    ):
        first_row.append(
            InlineKeyboardButton(
                text="🔄 Взять в работу", callback_data=f"take_task:{context}"
            )
        )

    first_row.append(
        InlineKeyboardButton(text="🕒 Отложить", callback_data=f"postpone_task:{context}")
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            first_row,
            [InlineKeyboardButton(text="🏠 Главная", callback_data="back_main")],
        ]
    )


# Меню помощи
def help_menu_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Задачи", callback_data="help_tasks"),
                InlineKeyboardButton(text="🟢 Статусы задач", callback_data="help_statuses")
            ],
            [
                InlineKeyboardButton(text="🏠 Главная", callback_data="back_main")
            ]
        ]
    )


# Меню помощи по задачам
def help_tasks_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Добавление задач", callback_data="help_add_tasks"),
                InlineKeyboardButton(text="🔍 Фильтр", callback_data="help_filter")
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back_help")
            ]
        ]
    )


# Меню помощи по статусам
def help_statuses_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 По статусу", callback_data="help_by_status"),
                InlineKeyboardButton(text="⚡ По приоритету", callback_data="help_by_priority")
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back_help")
            ]
        ]
    )


# Кнопка назад для вложенных меню
def back_button_kb(back_to: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_{back_to}")
            ]
        ]
    )


def get_main_message(user_id: int) -> str:
    """Формирует главное сообщение со статистикой."""
    greeting = greet_user(user_id)

    if "Доступ ограничен" in greeting:
        return greeting

    refresh_all_tasks_statuses()
    user_tasks = get_involved_tasks(user_id)
    active_tasks = [task for task in user_tasks if task.status == TaskStatus.ACTIVE]
    overdue_tasks = [task for task in user_tasks if task.status == TaskStatus.OVERDUE]
    completed_tasks = [task for task in user_tasks if task.status == TaskStatus.COMPLETED]
    pending_tasks = [task for task in user_tasks if task.status != TaskStatus.COMPLETED]
    new_tasks = [
        task
        for task in user_tasks
        if task.status in {TaskStatus.NEW, TaskStatus.PAUSED}
    ]

    stats_text = (
        f"{greeting}\n\n"
        "📊 <b>Краткая статистика:</b>\n"
        f"📋 Задачи на сегодня: {len(pending_tasks)}\n"
        f"📈 Всего задач: {len(TASKS)}\n"
        f"⏰ Просрочено: {len(overdue_tasks)}\n"
        f"🔄 В работе: {len(active_tasks)}\n"
        f"✅ Завершено: {len(completed_tasks)}\n"
        f"🆕 Новых задач: {len(new_tasks)}"
    )
    return stats_text


def get_help_text(user_id: int) -> str:
    """Формирует текст помощи в зависимости от роли пользователя."""
    
    if is_admin(user_id):
        # Помощь для администратора
        return (
            "🤖 <b>Помощь для администратора</b>\n\n"
            "📋 <b>Основные функции:</b>\n"
            "• Просмотр всех задач системы\n"
            "• Управление задачами пользователей\n"
            "• Добавление и редактирование задач\n\n"
            
            "⚙️ <b>Админские команды:</b>\n"
            "• /stats - Статистика системы\n"
            "• /users - Список пользователей\n" 
            "• /broadcast - Рассылка сообщений\n"
            "• /logs - Просмотр логов\n"
            "• /restart - Перезапуск бота\n"
            "• /backup - Резервное копирование\n\n"
            
            "👥 <b>Управление доступом:</b>\n"
            "• Доступ ко всем задачам системы\n"
            "• Возможность назначать задачи\n"
            "• Просмотр статистики всех пользователей"
        )
    else:
        # Помощь для обычного пользователя
        return (
            "🤖 <b>Помощь по боту задач</b>\n\n"
            "Выберите раздел помощи в меню ниже:"
        )


def get_help_section_text(section: str, user_id: int) -> str:
    """Возвращает текст для конкретного раздела помощи."""
    
    texts = {
        "help_tasks": (
            "📋 <b>Помощь по задачам</b>\n\n"
            "Выберите подраздел:"
        ),
        "help_add_tasks": (
            "➕ <b>Добавление задач - как правильно добавлять задачи</b>\n\n"
            "• Используйте кнопку '➕ Добавить задачу' в главном меню\n"
            "• Укажите название задачи (обязательно)\n"
            "• Добавьте описание (опционально)\n"
            "• Установите срок выполнения\n"
            "• Выберите приоритет и ответственного\n"
            "• Подтвердите создание задачи"
        ),
        "help_filter": (
            "🔍 <b>Фильтрация задач</b>\n\n"
            "• <b>Активные</b> - задачи в работе\n"
            "• <b>Завершенные</b> - выполненные задачи\n"
            "• <b>Все задачи</b> - полный список\n"
            "• Используйте фильтры для быстрого поиска"
        ),
        "help_statuses": (
            "🟢 <b>Статусы задач</b>\n\n"
            "Выберите тип фильтрации:"
        ),
        "help_by_status": (
            "📊 <b>Фильтрация по статусу</b>\n\n"
            "• <b>Новые</b> - ожидают назначения\n"
            "• <b>В работе</b> - выполняются\n"
            "• <b>На паузе</b> - временно приостановлены\n"
            "• <b>На проверке</b> - ожидают подтверждения автора\n"
            "• <b>Завершено</b> - выполнены\n"
            "• <b>Просрочено</b> - не выполнены в срок"
        ),
        "help_by_priority": (
            "⚡ <b>Фильтрация по приоритету</b>\n\n"
            "• <b>Критический</b> - максимальный приоритет\n"
            "• <b>Высокий</b> - срочные важные задачи\n"
            "• <b>Средний</b> - стандартные задачи\n"
            "• <b>Низкий</b> - задачи без срочности"
        )
    }
    
    return texts.get(section, "Раздел помощи не найден")


def create_dispatcher() -> Dispatcher:
    """Создаёт диспетчер aiogram и регистрирует хендлеры."""

    dispatcher = Dispatcher()

    # Хранилище данных для создания задачи
    task_data = {}
    task_updates: dict[int, dict] = {}

    async def safe_edit_message(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
        """Безопасно редактирует сообщение, игнорируя отсутствие изменений."""

        try:
            await message.edit_text(text=text, reply_markup=reply_markup)
        except TelegramBadRequest as error:
            if "message is not modified" in error.message:
                return
            raise

    async def safe_edit_message_by_id(
        bot: Bot,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        """Редактирует сообщение по идентификатору с защитой от повторного текста."""

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest as error:
            if "message is not modified" in error.message:
                return
            raise

    def build_creation_header(data: dict) -> str:
        """Формирует заголовок с текущими параметрами создаваемой задачи."""

        lines: list[str] = ["📝 <b>Создание новой задачи</b>"]

        title = data.get("title")
        if title:
            lines.append(f"📌 Название: {title}")

        if "description" in data:
            description = data.get("description") or "Не указано"
            lines.append(f"📄 Описание: {description}")

        if "due_date" in data:
            due_date = data.get("due_date")
            if isinstance(due_date, datetime):
                lines.append(f"📅 Срок: {due_date.strftime('%d.%m.%Y')}")
            else:
                lines.append("📅 Срок: Не указан")

        priority = data.get("priority")
        if priority:
            lines.append(f"⚡ Приоритет: {priority.value}")

        project = data.get("project")
        if project:
            project_name = PROJECTS.get(project, project)
            lines.append(f"🏢 Проект: {project_name}")

        direction = data.get("direction")
        if direction:
            lines.append(f"🎯 Направление: {get_direction_label(direction)}")

        responsible_users = data.get("responsible_users")
        if responsible_users:
            names = [
                get_user_full_name(user_id)
                for user_id in responsible_users
                if user_id in USERS
            ]
            if names:
                lines.append(f"👤 Ответственный: {', '.join(names)}")

        workgroup_users = data.get("workgroup_users")
        if workgroup_users:
            names = [
                get_user_full_name(user_id)
                for user_id in workgroup_users
                if user_id in USERS
            ]
            if names:
                lines.append(f"👥 Рабочая группа: {', '.join(names)}")

        if "is_private" in data:
            is_private = data.get("is_private")
            privacy_text = "Личная" if is_private else "Общая"
            lines.append(f"🔒 Приватность: {privacy_text}")

        return "\n".join(lines)

    @dispatcher.message(CommandStart())
    async def handle_start(message: Message, state: FSMContext) -> None:
        """Обрабатывает команду /start с главным меню."""
        await state.clear()
        user_id = message.from_user.id if message.from_user else 0
        text = get_main_message(user_id)
        
        if "Доступ ограничен" in text:
            await message.answer(text)
            return
        
        await message.answer(text, reply_markup=main_menu_kb())

    # Обработчики callback-кнопок
    @dispatcher.callback_query(F.data == "all_tasks")
    @dispatcher.callback_query(F.data == "my_tasks")
    async def handle_tasks_list(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает кнопки списка задач."""
        await state.clear()
        user_id = callback.from_user.id
        text = get_main_message(user_id)
        
        if "Доступ ограничен" in text:
            await callback.answer("Доступ ограничен")
            return
        
        list_type = "всех" if callback.data == "all_tasks" else "ваших"
        new_text = f"📊 Просмотр {list_type} задач. Выберите фильтр:"
        
        await safe_edit_message(
            callback.message,
            text=new_text,
            reply_markup=tasks_filter_kb(),
        )
        await callback.answer()

    @dispatcher.callback_query(F.data == "add_task")
    async def handle_add_task(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает кнопку добавления задачи."""
        user_id = callback.from_user.id
        text = get_main_message(user_id)

        if "Доступ ограничен" in text:
            await callback.answer("Доступ ограничен")
            return
        
        # Начинаем процесс создания задачи
        await state.set_state(TaskCreation.waiting_for_title)
        task_data[user_id] = {
            'author_id': user_id,
            'created_date': datetime.now(),
            'responsible_users': set(),
            'workgroup_users': set(),
            'message_id': callback.message.message_id,
        }

        header = build_creation_header(task_data[user_id])
        prompt = "Введите название задачи:"

        await safe_edit_message(
            callback.message,
            text=f"{header}\n\n{prompt}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task_creation")]]
            ),
        )
        await callback.answer()

    @dispatcher.callback_query(F.data == "cancel_task_creation")
    async def handle_cancel_task_creation(callback: CallbackQuery, state: FSMContext) -> None:
        """Отменяет создание задачи."""
        await state.clear()
        user_id = callback.from_user.id
        if user_id in task_data:
            del task_data[user_id]
        
        text = get_main_message(user_id)
        await safe_edit_message(
            callback.message,
            text=text,
            reply_markup=main_menu_kb(),
        )
        await callback.answer("Создание задачи отменено")

    @dispatcher.message(TaskCreation.waiting_for_title)
    async def process_task_title(message: Message, state: FSMContext) -> None:
        """Обрабатывает название задачи."""
        user_id = message.from_user.id
        if user_id not in task_data:
            await state.clear()
            await message.answer("Сессия создания задачи устарела. Начните заново.", reply_markup=main_menu_kb())
            return
        
        task_data[user_id]['title'] = message.text.strip()
        await state.set_state(TaskCreation.waiting_for_description)

        message_id = task_data[user_id].get('message_id')
        if message_id:
            header = build_creation_header(task_data[user_id])
            prompt = "📄 Теперь введите описание задачи (или отправьте '-' чтобы пропустить):"
            await safe_edit_message_by_id(
                message.bot,
                chat_id=message.chat.id,
                message_id=message_id,
                text=f"{header}\n\n{prompt}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_task_title")]]
                ),
            )
        await message.delete()

    @dispatcher.callback_query(F.data == "back_task_title")
    async def handle_back_title(callback: CallbackQuery, state: FSMContext) -> None:
        """Возврат к вводу названия."""
        user_id = callback.from_user.id
        await state.set_state(TaskCreation.waiting_for_title)
        
        task_info = task_data.get(user_id, {})
        task_info.pop('title', None)
        header = build_creation_header(task_info)
        prompt = "Введите название задачи:"

        await safe_edit_message(
            callback.message,
            text=f"{header}\n\n{prompt}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task_creation")]]
            ),
        )
        await callback.answer()

    @dispatcher.message(TaskCreation.waiting_for_description)
    async def process_task_description(message: Message, state: FSMContext) -> None:
        """Обрабатывает описание задачи."""
        user_id = message.from_user.id
        if user_id not in task_data:
            await state.clear()
            await message.answer("Сессия создания задачи устарела. Начните заново.", reply_markup=main_menu_kb())
            return
        
        description = message.text.strip() if message.text != '-' else ''
        task_data[user_id]['description'] = description
        await state.set_state(TaskCreation.waiting_for_due_date)

        message_id = task_data[user_id].get('message_id')
        if message_id:
            header = build_creation_header(task_data[user_id])
            prompt = "📅 Введите дату выполнения в формате ДД.ММ.ГГГГ (или отправьте '-' для автоматического расчета):"
            await safe_edit_message_by_id(
                message.bot,
                chat_id=message.chat.id,
                message_id=message_id,
                text=f"{header}\n\n{prompt}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_due_date")],
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_task_description")],
                    ]
                ),
            )
        await message.delete()

    @dispatcher.callback_query(F.data == "back_task_description")
    async def handle_back_description(callback: CallbackQuery, state: FSMContext) -> None:
        """Возврат к вводу описания."""
        user_id = callback.from_user.id
        await state.set_state(TaskCreation.waiting_for_description)
        
        task_info = task_data.get(user_id, {})
        header = build_creation_header(task_info)
        prompt = "📄 Введите описание задачи (или отправьте '-' чтобы пропустить):"

        await safe_edit_message(
            callback.message,
            text=f"{header}\n\n{prompt}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_task_title")]]
            ),
        )
        await callback.answer()

    @dispatcher.message(TaskCreation.waiting_for_due_date)
    async def process_task_due_date(message: Message, state: FSMContext) -> None:
        """Обрабатывает дату выполнения."""
        user_id = message.from_user.id
        if user_id not in task_data:
            await state.clear()
            await message.answer("Сессия создания задачи устарела. Начните заново.", reply_markup=main_menu_kb())
            return
        
        if message.text != '-':
            due_date = parse_date(message.text)
            if not due_date:
                await message.answer("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ или ДД-ММ-ГГГГ")
                return
            task_data[user_id]['due_date'] = due_date
        else:
            task_data[user_id]['due_date'] = None  # Будет рассчитано после выбора приоритета
        
        await state.set_state(TaskCreation.waiting_for_priority)
        message_id = task_data[user_id].get('message_id')
        if message_id:
            header = build_creation_header(task_data[user_id])
            prompt = "⚡ Выберите приоритет задачи:"
            await safe_edit_message_by_id(
                message.bot,
                chat_id=message.chat.id,
                message_id=message_id,
                text=f"{header}\n\n{prompt}",
                reply_markup=priority_kb(),
            )
        await message.delete()

    @dispatcher.callback_query(F.data == "skip_due_date")
    async def handle_skip_due_date(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает пропуск ввода даты выполнения."""
        user_id = callback.from_user.id
        if user_id not in task_data:
            await state.clear()
            await safe_edit_message(
                callback.message,
                text="Сессия создания задачи устарела. Начните заново.",
                reply_markup=main_menu_kb(),
            )
            await callback.answer()
            return

        task_data[user_id]['due_date'] = None
        await state.set_state(TaskCreation.waiting_for_priority)

        header = build_creation_header(task_data[user_id])
        prompt = "⚡ Выберите приоритет задачи:"

        await safe_edit_message(
            callback.message,
            text=f"{header}\n\n{prompt}",
            reply_markup=priority_kb(),
        )
        await callback.answer("Срок будет рассчитан автоматически")

    @dispatcher.callback_query(F.data.startswith("priority_"))
    async def handle_priority_selection(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает выбор приоритета."""
        user_id = callback.from_user.id
        if user_id not in task_data:
            await state.clear()
            await safe_edit_message(
                callback.message,
                text="Сессия создания задачи устарела. Начните заново.",
                reply_markup=main_menu_kb(),
            )
            return
        
        priority_key = callback.data.replace("priority_", "")
        try:
            priority = TaskPriority[priority_key.upper()]
        except KeyError:
            await callback.answer("❌ Неизвестный приоритет", show_alert=True)
            return

        task_data[user_id]['priority'] = priority

        # Если дата не была указана, рассчитываем автоматически
        if not task_data[user_id].get('due_date'):
            due_date = calculate_due_date(priority, task_data[user_id]['created_date'])
            task_data[user_id]['due_date'] = due_date
        
        await state.set_state(TaskCreation.waiting_for_project)
        header = build_creation_header(task_data[user_id])
        prompt = "🏢 Выберите проект:"

        await safe_edit_message(
            callback.message,
            text=f"{header}\n\n{prompt}",
            reply_markup=projects_kb(),
        )
        await callback.answer()

    @dispatcher.callback_query(F.data.startswith("project_"))
    async def handle_project_selection(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает выбор проекта."""
        user_id = callback.from_user.id
        if user_id not in task_data:
            await state.clear()
            await safe_edit_message(
                callback.message,
                text="Сессия создания задачи устарела. Начните заново.",
                reply_markup=main_menu_kb(),
            )
            return
        
        project_id = callback.data.replace("project_", "")
        task_data[user_id]['project'] = project_id
        
        await state.set_state(TaskCreation.waiting_for_direction)
        header = build_creation_header(task_data[user_id])
        prompt = "🎯 Выберите направление:"

        await safe_edit_message(
            callback.message,
            text=f"{header}\n\n{prompt}",
            reply_markup=directions_kb(),
        )
        await callback.answer()

    @dispatcher.callback_query(F.data.startswith("direction_"))
    async def handle_direction_selection(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает выбор направления."""
        user_id = callback.from_user.id
        if user_id not in task_data:
            await state.clear()
            await safe_edit_message(
                callback.message,
                text="Сессия создания задачи устарела. Начните заново.",
                reply_markup=main_menu_kb(),
            )
            return
        
        direction_id = callback.data.replace("direction_", "")
        task_data[user_id]['direction'] = direction_id
        
        # Получаем пользователей направления для выбора ответственного
        direction_name = direction_title(direction_id)
        users = get_users_by_direction(direction_id)
        
        await state.set_state(TaskCreation.waiting_for_responsible)
        header = build_creation_header(task_data[user_id])
        prompt = f"👤 Выберите ответственного за задачу (направление: {direction_name}):"

        await safe_edit_message(
            callback.message,
            text=f"{header}\n\n{prompt}",
            reply_markup=users_kb(users, set(), "responsible", "direction"),
        )
        await callback.answer()

    @dispatcher.callback_query(F.data.startswith("responsible_"))
    async def handle_responsible_selection(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает выбор ответственного."""
        user_id = callback.from_user.id
        if user_id not in task_data:
            await state.clear()
            await safe_edit_message(
                callback.message,
                text="Сессия создания задачи устарела. Начните заново.",
                reply_markup=main_menu_kb(),
            )
            return
        
        selected_user_id = int(callback.data.replace("responsible_", ""))
        selected_responsible = task_data[user_id]['responsible_users']
        
        if selected_user_id in selected_responsible:
            selected_responsible.remove(selected_user_id)
        else:
            selected_responsible.clear()
            selected_responsible.add(selected_user_id)
        
        direction_id = task_data[user_id]['direction']
        direction_name = direction_title(direction_id)
        users = get_users_by_direction(direction_id)
        
        header = build_creation_header(task_data[user_id])
        prompt = (
            f"👤 Выберите ответственного за задачу (направление: {direction_name}):\n"
            f"✅ Выбрано: {len(selected_responsible)}"
        )

        await safe_edit_message(
            callback.message,
            text=f"{header}\n\n{prompt}",
            reply_markup=users_kb(users, selected_responsible, "responsible", "direction"),
        )
        await callback.answer()

    @dispatcher.callback_query(F.data == "done_responsible")
    async def handle_done_responsible(callback: CallbackQuery, state: FSMContext) -> None:
        """Завершает выбор ответственного."""
        user_id = callback.from_user.id
        if user_id not in task_data:
            await state.clear()
            await safe_edit_message(
                callback.message,
                text="Сессия создания задачи устарела. Начните заново.",
                reply_markup=main_menu_kb(),
            )
            return
        
        if not task_data[user_id]['responsible_users']:
            await callback.answer("❌ Нужно выбрать хотя бы одного ответственного!")
            return
        
        direction_id = task_data[user_id]['direction']
        direction_name = direction_title(direction_id)
        users = get_users_by_direction(direction_id)
        
        await state.set_state(TaskCreation.waiting_for_workgroup)
        header = build_creation_header(task_data[user_id])
        prompt = "👥 Выберите рабочую группу (можно выбрать несколько):"

        await safe_edit_message(
            callback.message,
            text=f"{header}\n\n{prompt}",
            reply_markup=users_kb(users, task_data[user_id]['workgroup_users'], "workgroup", "responsible"),
        )
        await callback.answer()

    @dispatcher.callback_query(F.data.startswith("workgroup_"))
    async def handle_workgroup_selection(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает выбор рабочей группы."""
        user_id = callback.from_user.id
        if user_id not in task_data:
            await state.clear()
            await safe_edit_message(
                callback.message,
                text="Сессия создания задачи устарела. Начните заново.",
                reply_markup=main_menu_kb(),
            )
            return
        
        selected_user_id = int(callback.data.replace("workgroup_", ""))
        
        if selected_user_id in task_data[user_id]['workgroup_users']:
            task_data[user_id]['workgroup_users'].remove(selected_user_id)
        else:
            task_data[user_id]['workgroup_users'].add(selected_user_id)
        
        direction_id = task_data[user_id]['direction']
        direction_name = direction_title(direction_id)
        users = get_users_by_direction(direction_id)
        
        header = build_creation_header(task_data[user_id])
        prompt = (
            "👥 Выберите рабочую группу (можно выбрать несколько):\n"
            f"✅ Выбрано: {len(task_data[user_id]['workgroup_users'])}"
        )

        await safe_edit_message(
            callback.message,
            text=f"{header}\n\n{prompt}",
            reply_markup=users_kb(users, task_data[user_id]['workgroup_users'], "workgroup", "responsible"),
        )
        await callback.answer()

    @dispatcher.callback_query(F.data == "done_workgroup")
    async def handle_done_workgroup(callback: CallbackQuery, state: FSMContext) -> None:
        """Завершает выбор рабочей группы."""
        user_id = callback.from_user.id
        if user_id not in task_data:
            await state.clear()
            await safe_edit_message(
                callback.message,
                text="Сессия создания задачи устарела. Начните заново.",
                reply_markup=main_menu_kb(),
            )
            return
        
        await state.set_state(TaskCreation.waiting_for_privacy)
        header = build_creation_header(task_data[user_id])
        prompt = "🔒 Выберите уровень доступа к задаче:"

        await safe_edit_message(
            callback.message,
            text=f"{header}\n\n{prompt}",
            reply_markup=privacy_kb(),
        )
        await callback.answer()

    @dispatcher.callback_query(F.data.startswith("privacy_"))
    async def handle_privacy_selection(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает выбор уровня приватности."""
        user_id = callback.from_user.id
        if user_id not in task_data:
            await state.clear()
            await safe_edit_message(
                callback.message,
                text="Сессия создания задачи устарела. Начните заново.",
                reply_markup=main_menu_kb(),
            )
            return
        
        privacy = callback.data.replace("privacy_", "")
        task_data[user_id]['is_private'] = (privacy == 'private')
        
        # Создаем задачу
        task_info = task_data[user_id]
        try:
            responsible_user_id = next(iter(task_info['responsible_users']))
            workgroup_users = list(task_info['workgroup_users'])
            task = create_task(
                title=task_info['title'],
                description=task_info['description'],
                author_id=user_id,
                priority=task_info['priority'],
                due_date=task_info['due_date'],
                project=task_info['project'],
                direction=task_info['direction'],
                responsible_user_id=responsible_user_id,
                workgroup=workgroup_users,
                is_private=task_info['is_private']
            )
            record_task_action(task, user_id, "Создал задачу")

            # Отправляем уведомления
            bot = callback.bot
            all_notified_users = {responsible_user_id}
            all_notified_users.update(workgroup_users)

            responsible_name = get_user_full_name(responsible_user_id)

            for notified_user_id in all_notified_users:
                user = USERS.get(notified_user_id)
                if user is None:
                    continue
                try:
                    await bot.send_message(
                        chat_id=notified_user_id,
                        text=(
                            "🔔 <b>Новая задача назначена!</b>\n\n"
                            f"📝 <b>{task.title}</b>\n"
                            f"👤 Ответственный: {responsible_name}\n"
                            f"📅 Срок: {task.due_date.strftime('%d.%m.%Y') if task.due_date else 'Не указан'}\n"
                            f"⚡ Приоритет: {task.priority.value}"
                        ),
                        reply_markup=task_actions_kb(task, notified_user_id)
                    )
                except Exception as e:
                    LOGGER.error(f"Ошибка отправки уведомления пользователю {notified_user_id}: {e}")

            # Сообщение автору
            success_text = (
                "✅ <b>Задача успешно создана!</b>\n\n"
                f"📝 <b>{task.title}</b>\n"
                f"📄 Описание: {task.description or 'Не указано'}\n"
                f"📅 Срок: {task.due_date.strftime('%d.%m.%Y') if task.due_date else 'Не указан'}\n"
                f"⚡ Приоритет: {task.priority.value}\n"
                f"🏢 Проект: {PROJECTS[task.project]}\n"
                f"🎯 Направление: {get_direction_label(task.direction)}\n"
                f"👥 Участников: {len(all_notified_users)}"
            )
            await safe_edit_message(
                callback.message,
                text=success_text,
                reply_markup=main_menu_kb(),
            )


            # Очищаем данные
            del task_data[user_id]
            await state.clear()
            
        except Exception as e:
            LOGGER.error(f"Ошибка создания задачи: {e}")
            error_text = (
                "❌ <b>Ошибка создания задачи!</b>\n\n"
                f"Произошла ошибка: {str(e)}\n\n"
                "Попробуйте создать задачу заново."
            )
            await safe_edit_message(
                callback.message,
                text=error_text,
                reply_markup=main_menu_kb(),
            )
            if user_id in task_data:
                del task_data[user_id]
            await state.clear()
        
        await callback.answer()

    # Обработчики кнопок "Назад"
    @dispatcher.callback_query(F.data.startswith("back_"))
    async def handle_back_buttons(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает все кнопки возврата."""
        back_to = callback.data.replace("back_", "")
        user_id = callback.from_user.id
        
        if back_to == "main":
            await state.clear()
            task_updates.pop(user_id, None)
            text = get_main_message(user_id)
            await safe_edit_message(
                callback.message,
                text=text,
                reply_markup=main_menu_kb(),
            )

        elif back_to == "help":
            await safe_edit_message(
                callback.message,
                text=get_help_text(user_id),
                reply_markup=help_menu_kb(),
            )

        elif back_to == "help_tasks":
            await safe_edit_message(
                callback.message,
                text=get_help_section_text("help_tasks", user_id),
                reply_markup=help_tasks_kb(),
            )

        elif back_to == "help_statuses":
            await safe_edit_message(
                callback.message,
                text=get_help_section_text("help_statuses", user_id),
                reply_markup=help_statuses_kb(),
            )

        elif back_to == "task_creation":
            # Возврат к началу создания задачи
            task_data[user_id] = {
                'author_id': user_id,
                'created_date': datetime.now(),
                'responsible_users': set(),
                'workgroup_users': set(),
                'message_id': callback.message.message_id,
            }
            await state.set_state(TaskCreation.waiting_for_title)
            header = build_creation_header(task_data[user_id])
            prompt = "Введите название задачи:"
            await safe_edit_message(
                callback.message,
                text=f"{header}\n\n{prompt}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task_creation")]]
                ),
            )

        elif back_to in {"direction", "responsible", "workgroup"}:
            task_info = task_data.get(user_id)
            if not task_info:
                await state.clear()
                await safe_edit_message(
                    callback.message,
                    text="Сессия создания задачи устарела. Начните заново.",
                    reply_markup=main_menu_kb(),
                )
                await callback.answer("Сессия создания задачи устарела", show_alert=True)
                return

            if back_to == "direction":
                task_info.pop('direction', None)
                responsible = task_info.get('responsible_users')
                if isinstance(responsible, set):
                    responsible.clear()
                else:
                    task_info['responsible_users'] = set()
                workgroup = task_info.get('workgroup_users')
                if isinstance(workgroup, set):
                    workgroup.clear()
                else:
                    task_info['workgroup_users'] = set()

                await state.set_state(TaskCreation.waiting_for_direction)
                header = build_creation_header(task_info)
                prompt = "🎯 Выберите направление:"
                await safe_edit_message(
                    callback.message,
                    text=f"{header}\n\n{prompt}",
                    reply_markup=directions_kb(),
                )

            elif back_to == "responsible":
                direction_id = task_info.get('direction')
                if not direction_id:
                    await callback.answer("Сначала выберите направление", show_alert=True)
                    return

                workgroup = task_info.get('workgroup_users')
                if isinstance(workgroup, set):
                    workgroup.clear()
                else:
                    task_info['workgroup_users'] = set()

                await state.set_state(TaskCreation.waiting_for_responsible)
                header = build_creation_header(task_info)
                direction_name = direction_title(direction_id)
                prompt = f"👤 Выберите ответственного за задачу (направление: {direction_name}):"
                users = get_users_by_direction(direction_id)
                selected_responsible = task_info.get('responsible_users')
                if not isinstance(selected_responsible, set):
                    selected_responsible = set()
                    task_info['responsible_users'] = selected_responsible

                await safe_edit_message(
                    callback.message,
                    text=f"{header}\n\n{prompt}",
                    reply_markup=users_kb(users, selected_responsible, "responsible", "direction"),
                )

            else:  # back_to == "workgroup"
                direction_id = task_info.get('direction')
                responsible = task_info.get('responsible_users')
                if not direction_id or not responsible:
                    await callback.answer("Сначала выберите ответственного", show_alert=True)
                    return

                await state.set_state(TaskCreation.waiting_for_workgroup)
                header = build_creation_header(task_info)
                prompt = "👥 Выберите рабочую группу (можно выбрать несколько):"
                users = get_users_by_direction(direction_id)
                workgroup = task_info.get('workgroup_users')
                if not isinstance(workgroup, set):
                    workgroup = set()
                    task_info['workgroup_users'] = workgroup

                await safe_edit_message(
                    callback.message,
                    text=f"{header}\n\n{prompt}",
                    reply_markup=users_kb(users, workgroup, "workgroup", "responsible"),
                )

        await callback.answer()

    # Обработчики помощи
    @dispatcher.callback_query(F.data == "help")
    async def handle_help(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает кнопку помощи."""
        user_id = callback.from_user.id
        await safe_edit_message(
            callback.message,
            text=get_help_text(user_id),
            reply_markup=help_menu_kb(),
        )
        await callback.answer()

    @dispatcher.callback_query(F.data.startswith("help_"))
    async def handle_help_sections(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает разделы помощи."""
        section = callback.data
        user_id = callback.from_user.id
        
        if section in ["help_tasks", "help_statuses"]:
            text = get_help_section_text(section, user_id)
            if section == "help_tasks":
                await safe_edit_message(
                    callback.message,
                    text=text,
                    reply_markup=help_tasks_kb(),
                )
            else:
                await safe_edit_message(
                    callback.message,
                    text=text,
                    reply_markup=help_statuses_kb(),
                )
        else:
            text = get_help_section_text(section, user_id)
            if section == "help_add_tasks":
                await safe_edit_message(
                    callback.message,
                    text=text,
                    reply_markup=back_button_kb("help_tasks"),
                )
            elif section in ["help_filter", "help_by_status", "help_by_priority"]:
                await safe_edit_message(
                    callback.message,
                    text=text,
                    reply_markup=back_button_kb("help_tasks" if section == "help_filter" else "help_statuses"),
                )
            else:
                await safe_edit_message(
                    callback.message,
                    text=text,
                    reply_markup=back_button_kb("help"),
                )
        
        await callback.answer()

    def get_tasks_for_view(view: str, user_id: int) -> list[Task]:
        """Возвращает задачи в зависимости от выбранного режима просмотра."""

        refresh_all_tasks_statuses()

        if view == "my":
            return get_involved_tasks(user_id)
        return list(TASKS.values())

    def filter_tasks(tasks: list[Task], filter_type: str) -> tuple[list[Task], str]:
        """Применяет фильтр к списку задач и возвращает текст фильтра."""

        if filter_type == "active":
            return [task for task in tasks if task.status == TaskStatus.ACTIVE], "активные"
        if filter_type == "review":
            return [task for task in tasks if task.status == TaskStatus.IN_REVIEW], "на проверке"
        if filter_type == "completed":
            return [task for task in tasks if task.status == TaskStatus.COMPLETED], "завершенные"
        return tasks, "все"

    async def render_task_detail(
        message: Message,
        task: Task,
        viewer_id: int,
        view: str,
        filter_type: str,
        page: int,
    ) -> None:
        """Обновляет сообщение с карточкой задачи."""

        text = build_task_detail_text(task, viewer_id)
        keyboard = task_detail_kb(task, viewer_id, view, filter_type, page)

        await safe_edit_message(
            message,
            text=text,
            reply_markup=keyboard,
        )

    def extract_action_context(callback_data: str, prefix: str) -> tuple[int, str, str, int]:
        """Извлекает параметры из данных коллбэка."""

        default_context = (0, "notify", "all", 1)

        if callback_data.startswith(f"{prefix}:"):
            parts = callback_data.split(":", 4)
            if len(parts) == 5:
                _, task_id_str, view, filter_type, page_str = parts
                try:
                    task_id = int(task_id_str)
                    page = int(page_str)
                except ValueError:
                    return default_context
                return task_id, view, filter_type, page
            return default_context

        if callback_data.startswith(f"{prefix}_"):
            try:
                task_id = int(callback_data.replace(f"{prefix}_", ""))
            except ValueError:
                return default_context
            return task_id, "notify", "all", 1

        return default_context

    @dispatcher.callback_query(F.data.startswith("filter_"))
    async def handle_task_filters(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает фильтры списка задач."""
        filter_type = callback.data.replace("filter_", "")
        user_id = callback.from_user.id
        view = "my" if callback.message.text.startswith("📊 Просмотр ваших задач") else "all"

        tasks = get_tasks_for_view(view, user_id)
        tasks, filter_text = filter_tasks(tasks, filter_type)

        if not tasks:
            empty_text = (
                f"📋 <b>{filter_text.capitalize()} задачи</b>\n\n"
                "Задачи не найдены."
            )
            await safe_edit_message(
                callback.message,
                text=empty_text,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="📋 Фильтры", callback_data=f"tasks_filters:{view}")],
                        [InlineKeyboardButton(text="🏠 Главная", callback_data="back_main")],
                    ]
                ),
            )
            await callback.answer()
            return

        page = 1
        tasks_text = build_tasks_list_text(tasks, filter_text, page)
        keyboard = tasks_list_kb(tasks, view, filter_type, page)

        await safe_edit_message(
            callback.message,
            text=tasks_text,
            reply_markup=keyboard,
        )
        await callback.answer()

    @dispatcher.callback_query(F.data.startswith("tasks_page:"))
    async def handle_tasks_page(callback: CallbackQuery, state: FSMContext) -> None:
        """Переключает страницы списка задач."""
        _, view, filter_type, page_str = callback.data.split(":", 3)
        user_id = callback.from_user.id
        tasks = get_tasks_for_view(view, user_id)
        tasks, filter_text = filter_tasks(tasks, filter_type)

        if not tasks:
            await callback.answer("Задачи не найдены", show_alert=True)
            return

        total_pages = max(1, (len(tasks) + TASKS_PER_PAGE - 1) // TASKS_PER_PAGE)
        try:
            page = int(page_str)
        except ValueError:
            page = 1
        page = max(1, min(page, total_pages))

        tasks_text = build_tasks_list_text(tasks, filter_text, page)
        keyboard = tasks_list_kb(tasks, view, filter_type, page)

        await safe_edit_message(
            callback.message,
            text=tasks_text,
            reply_markup=keyboard,
        )
        await callback.answer()

    @dispatcher.callback_query(F.data.startswith("task_detail:"))
    async def handle_task_detail(callback: CallbackQuery, state: FSMContext) -> None:
        """Показывает подробную информацию о задаче."""
        parts = callback.data.split(":")
        if len(parts) != 5:
            await callback.answer("Некорректные данные", show_alert=True)
            return

        _, task_id_str, view, filter_type, page_str = parts
        try:
            task_id = int(task_id_str)
            page = int(page_str)
        except ValueError:
            await callback.answer("Некорректные данные", show_alert=True)
            return

        task = TASKS.get(task_id)
        if not task:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        await render_task_detail(
            callback.message,
            task,
            callback.from_user.id,
            view,
            filter_type,
            page,
        )
        await callback.answer()

    @dispatcher.callback_query(F.data.startswith("tasks_filters:"))
    async def handle_tasks_filters_menu(callback: CallbackQuery, state: FSMContext) -> None:
        """Возвращает пользователя к выбору фильтра."""
        _, view = callback.data.split(":", 1)
        list_type = "всех" if view == "all" else "ваших"
        text = f"📊 Просмотр {list_type} задач. Выберите фильтр:"

        await safe_edit_message(
            callback.message,
            text=text,
            reply_markup=tasks_filter_kb(),
        )
        await callback.answer()

    @dispatcher.callback_query(F.data.startswith("delete_task:"))
    async def handle_delete_task(callback: CallbackQuery, state: FSMContext) -> None:
        """Удаляет задачу, если это делает автор."""
        parts = callback.data.split(":")
        if len(parts) != 5:
            await callback.answer("Некорректные данные", show_alert=True)
            return

        _, task_id_str, view, filter_type, page_str = parts
        try:
            task_id = int(task_id_str)
            page = int(page_str)
        except ValueError:
            await callback.answer("Некорректные данные", show_alert=True)
            return

        user_id = callback.from_user.id
        task = TASKS.get(task_id)

        if not task:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        if task.author_id != user_id:
            await callback.answer("Удалить задачу может только автор", show_alert=True)
            return

        remove_task(task_id)

        tasks = get_tasks_for_view(view, user_id)
        tasks, filter_text = filter_tasks(tasks, filter_type)

        if not tasks:
            empty_text = (
                f"📋 <b>{filter_text.capitalize()} задачи</b>\n\n"
                "Задачи не найдены."
            )
            await safe_edit_message(
                callback.message,
                text=empty_text,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="📋 Фильтры", callback_data=f"tasks_filters:{view}")],
                        [InlineKeyboardButton(text="🏠 Главная", callback_data="back_main")],
                    ]
                ),
            )
            await callback.answer("Задача удалена")
            return

        total_pages = max(1, (len(tasks) + TASKS_PER_PAGE - 1) // TASKS_PER_PAGE)
        page = max(1, min(page, total_pages))
        tasks_text = build_tasks_list_text(tasks, filter_text, page)
        keyboard = tasks_list_kb(tasks, view, filter_type, page)

        await safe_edit_message(
            callback.message,
            text=tasks_text,
            reply_markup=keyboard,
        )
        await callback.answer("Задача удалена")


    # Обработчики действий с задачами
    @dispatcher.callback_query(F.data.startswith("back_task_detail:"))
    async def handle_back_task_detail(callback: CallbackQuery, state: FSMContext) -> None:
        """Возвращает пользователя к карточке задачи."""

        user_id = callback.from_user.id
        await state.clear()
        task_updates.pop(user_id, None)

        task_id, view, filter_type, page = extract_action_context(callback.data, "back_task_detail")
        task = TASKS.get(task_id)

        if not task:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        await render_task_detail(callback.message, task, user_id, view, filter_type, page)
        await callback.answer()

    async def ensure_task_for_action(
        callback: CallbackQuery,
        prefix: str,
        not_found_message: str = "Задача не найдена",
    ) -> tuple[Task | None, str, str, int]:
        """Возвращает задачу и параметры отображения для действия."""

        task_id, view, filter_type, page = extract_action_context(callback.data, prefix)
        task = TASKS.get(task_id)

        if not task:
            await callback.answer(not_found_message, show_alert=True)
            return None, view, filter_type, page

        return task, view, filter_type, page

    def extract_confirmation_context(callback_data: str) -> tuple[int, int, str, str, int]:
        """Получает параметры для подтверждения выполнения."""

        default_context = (0, 0, "notify", "all", 1)

        if callback_data.startswith("confirm_completion:"):
            parts = callback_data.split(":", 5)
            if len(parts) == 6:
                _, task_id_str, participant_id_str, view, filter_type, page_str = parts
                try:
                    task_id = int(task_id_str)
                    participant_id = int(participant_id_str)
                    page = int(page_str)
                except ValueError:
                    return default_context
                return task_id, participant_id, view, filter_type, page

        return default_context

    def extract_reminder_context(callback_data: str) -> tuple[int, int, str, str, int]:
        """Получает параметры для напоминания конкретному участнику."""

        default_context = (0, 0, "notify", "all", 1)

        if callback_data.startswith("remind_one:"):
            parts = callback_data.split(":", 5)
            if len(parts) == 6:
                _, task_id_str, participant_id_str, view, filter_type, page_str = parts
                try:
                    task_id = int(task_id_str)
                    participant_id = int(participant_id_str)
                    page = int(page_str)
                except ValueError:
                    return default_context
                return task_id, participant_id, view, filter_type, page

        return default_context

    def can_manage_task(task: Task, user_id: int) -> bool:
        """Проверяет, может ли пользователь управлять задачей."""

        return (
            task.current_executor_id == user_id
            or task.responsible_user_id == user_id
            or task.author_id == user_id
        )

    @dispatcher.callback_query(F.data.startswith("take_task"))
    async def handle_take_task(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает взятие задачи в работу."""

        task, view, filter_type, page = await ensure_task_for_action(
            callback,
            "take_task",
            "Задача уже завершена или удалена",
        )
        if task is None:
            return

        user_id = callback.from_user.id
        if not is_user_involved(task, user_id):
            await callback.answer("Эта задача вам недоступна", show_alert=True)
            return

        if user_id == task.author_id:
            await callback.answer("Автор не может брать задачу в работу", show_alert=True)
            return
        if task.awaiting_author_confirmation:
            await callback.answer("Ожидается подтверждение автора", show_alert=True)
            return

        if task.status == TaskStatus.COMPLETED:
            await callback.answer("Задача уже завершена или удалена", show_alert=True)
            return

        task.current_executor_id = user_id
        set_participant_status(task, user_id, TaskStatus.ACTIVE)
        remove_pending_confirmation(task, user_id)
        task.completed_date = None
        task.status_before_overdue = None
        recalc_task_status(task)
        record_task_action(task, user_id, "Взял задачу в работу")
        await notify_task_participants(
            callback.bot,
            task,
            user_id,
            "взял(а) задачу в работу.",
            keyboard_builder=lambda recipient: _build_take_notification_keyboard(
                task,
                user_id,
                recipient,
            ),
        )

        await render_task_detail(callback.message, task, user_id, view, filter_type, page)
        await callback.answer("Задача взята в работу")

    @dispatcher.callback_query(F.data.startswith("pause_task"))
    async def handle_pause_task(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает постановку задачи на паузу."""

        task, view, filter_type, page = await ensure_task_for_action(callback, "pause_task")
        if task is None:
            return

        user_id = callback.from_user.id
        if not can_manage_task(task, user_id):
            await callback.answer("Нет прав для изменения задачи", show_alert=True)
            return

        # Даже автор и ответственный ставят на паузу только себя, поэтому не
        # вызываем массовое обновление статусов участников.
        set_participant_status(task, user_id, TaskStatus.PAUSED)
        if task.current_executor_id == user_id:
            task.current_executor_id = None

        task.status_before_overdue = None
        recalc_task_status(task)
        record_task_action(task, user_id, "Поставил задачу на паузу")
        await notify_task_participants(
            callback.bot,
            task,
            user_id,
            "поставил(а) задачу на паузу.",
        )

        await render_task_detail(callback.message, task, user_id, view, filter_type, page)
        await callback.answer("Задача на паузе")

    @dispatcher.callback_query(F.data.startswith("complete_task"))
    async def handle_complete_task(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает завершение задачи."""

        task, view, filter_type, page = await ensure_task_for_action(callback, "complete_task")
        if task is None:
            return

        user_id = callback.from_user.id
        if not can_manage_task(task, user_id):
            await callback.answer("Нет прав для завершения", show_alert=True)
            return

        role = detect_user_role(task, user_id)
        if role == "author":
            await callback.answer("Автор подтверждает выполнение из карточки", show_alert=True)
            return

        set_participant_status(task, user_id, TaskStatus.COMPLETED)
        if task.current_executor_id == user_id:
            task.current_executor_id = None
        task.completed_date = None
        task.status_before_overdue = None

        add_pending_confirmation(task, user_id)

        if role == "responsible":
            action_note = "завершил(а) задачу и отправил(а) на подтверждение автору."
            answer_text = "Задача передана на подтверждение автору"
        else:
            action_note = "завершил(а) свою часть задачи и отправил(а) на проверку."
            answer_text = "Результат отправлен на проверку ответственному"

        record_task_action(task, user_id, "Завершил задачу для проверки")
        await notify_task_participants(
            callback.bot,
            task,
            user_id,
            action_note,
            keyboard_builder=(
                None
                if role != "workgroup"
                else lambda recipient: _build_review_notification_keyboard(
                    task,
                    user_id,
                    recipient,
                )
            ),
        )

        await render_task_detail(callback.message, task, user_id, view, filter_type, page)
        await callback.answer(answer_text)

    @dispatcher.callback_query(F.data.startswith("reset_task_request"))
    async def handle_reset_task_request(callback: CallbackQuery, state: FSMContext) -> None:
        """Запрашивает подтверждение сброса состояния задачи."""

        task, view, filter_type, page = await ensure_task_for_action(callback, "reset_task_request")
        if task is None:
            return

        user_id = callback.from_user.id
        if user_id != task.author_id:
            await callback.answer("Сброс состояния доступен только автору", show_alert=True)
            return

        warning_text = (
            f"{build_task_detail_text(task, user_id)}\n\n"
            "⚠️ Подтвердите сброс состояния задачи."
        )
        confirmation_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Подтвердить сброс",
                        callback_data=f"reset_task_confirm:{task.task_id}:{view}:{filter_type}:{page}",
                    ),
                    InlineKeyboardButton(
                        text="⬅️ Отмена",
                        callback_data=f"reset_task_cancel:{task.task_id}:{view}:{filter_type}:{page}",
                    ),
                ]
            ]
        )

        await safe_edit_message(callback.message, text=warning_text, reply_markup=confirmation_keyboard)
        await callback.answer()

    @dispatcher.callback_query(F.data.startswith("reset_task_cancel"))
    async def handle_reset_task_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        """Отменяет процедуру сброса состояния."""

        task, view, filter_type, page = await ensure_task_for_action(callback, "reset_task_cancel")
        if task is None:
            return

        user_id = callback.from_user.id
        if user_id != task.author_id:
            await callback.answer("Сброс состояния доступен только автору", show_alert=True)
            return

        await render_task_detail(callback.message, task, user_id, view, filter_type, page)
        await callback.answer("Сброс отменён")

    @dispatcher.callback_query(F.data.startswith("reset_task_confirm"))
    async def handle_reset_task_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        """Сбрасывает состояние задачи после подтверждения."""

        task, view, filter_type, page = await ensure_task_for_action(callback, "reset_task_confirm")
        if task is None:
            return

        user_id = callback.from_user.id
        if user_id != task.author_id:
            await callback.answer("Сброс состояния доступен только автору", show_alert=True)
            return

        set_all_participants_status(task, TaskStatus.NEW)
        task.current_executor_id = None
        task.completed_date = None
        task.status_before_overdue = None
        clear_pending_confirmations(task)

        record_task_action(task, user_id, "Сбросил состояние задачи")
        await notify_task_participants(
            callback.bot,
            task,
            user_id,
            "сбросил(а) состояние задачи.",
        )

        await render_task_detail(callback.message, task, user_id, view, filter_type, page)
        await callback.answer("Состояние сброшено")

    @dispatcher.callback_query(F.data.startswith("remind_all"))
    async def handle_remind_all(callback: CallbackQuery, state: FSMContext) -> None:
        """Отправляет напоминание всем доступным участникам."""

        task, view, filter_type, page = await ensure_task_for_action(callback, "remind_all")
        if task is None:
            return

        user_id = callback.from_user.id
        recipients = get_allowed_reminder_targets(task, user_id)
        if not recipients:
            await callback.answer("Нет участников для напоминания", show_alert=True)
            return

        await send_task_reminder(callback.bot, task, user_id, recipients)
        record_task_action(task, user_id, "Отправил напоминание всем участникам")

        await render_task_detail(callback.message, task, user_id, view, filter_type, page)
        await callback.answer("Напоминание отправлено")

    @dispatcher.callback_query(F.data.startswith("remind_one:"))
    async def handle_remind_one(callback: CallbackQuery, state: FSMContext) -> None:
        """Отправляет напоминание конкретному участнику."""

        task_id, participant_id, view, filter_type, page = extract_reminder_context(callback.data)
        task = TASKS.get(task_id)

        if not task:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        user_id = callback.from_user.id
        recipients = get_allowed_reminder_targets(task, user_id)
        if participant_id not in recipients:
            await callback.answer("Нельзя напоминать этому участнику", show_alert=True)
            return

        await send_task_reminder(callback.bot, task, user_id, [participant_id])
        participant_name = get_user_full_name(participant_id)
        record_task_action(
            task,
            user_id,
            f"Отправил напоминание участнику {participant_name}",
        )

        await render_task_detail(callback.message, task, user_id, view, filter_type, page)
        await callback.answer("Напоминание отправлено")

    @dispatcher.callback_query(F.data.startswith("complete_task_author"))
    async def handle_author_completion(callback: CallbackQuery, state: FSMContext) -> None:
        """Позволяет автору завершить задачу в любой момент."""

        task, view, filter_type, page = await ensure_task_for_action(callback, "complete_task_author")
        if task is None:
            return

        user_id = callback.from_user.id
        if user_id != task.author_id:
            await callback.answer("Завершить задачу может только автор", show_alert=True)
            return

        set_all_participants_status(task, TaskStatus.COMPLETED)
        task.completed_date = datetime.now()
        task.current_executor_id = None
        task.status_before_overdue = None
        clear_pending_confirmations(task)

        record_task_action(task, user_id, "Завершил задачу")
        await notify_task_participants(
            callback.bot,
            task,
            user_id,
            "завершил(а) задачу.",
        )

        await render_task_detail(callback.message, task, user_id, view, filter_type, page)
        await callback.answer("Задача завершена")

    @dispatcher.callback_query(F.data.startswith("postpone_task"))
    async def handle_postpone_task(callback: CallbackQuery, state: FSMContext) -> None:
        """Запрашивает новую дату сдачи задачи."""

        task, view, filter_type, page = await ensure_task_for_action(callback, "postpone_task")
        if task is None:
            return

        user_id = callback.from_user.id
        if not (can_manage_task(task, user_id) or user_id in task.workgroup):
            await callback.answer("Нет прав для изменения срока", show_alert=True)
            return

        await state.set_state(TaskUpdate.waiting_for_postpone_date)
        task_updates[user_id] = {
            "task_id": task.task_id,
            "view": view,
            "filter": filter_type,
            "page": page,
            "message_id": callback.message.message_id,
        }

        prompt = (
            "🕒 Введите новую дату завершения задачи в формате ДД.ММ.ГГГГ\n"
            "Или нажмите \"⬅️ Назад\" для отмены изменения"
        )

        await safe_edit_message(
            callback.message,
            text=prompt,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data=f"back_task_detail:{task.task_id}:{view}:{filter_type}:{page}",
                        )
                    ],
                    [InlineKeyboardButton(text="🏠 Главная", callback_data="back_main")],
                ]
            ),
        )

        await callback.answer()

    @dispatcher.message(TaskUpdate.waiting_for_postpone_date)
    async def process_postpone_date(message: Message, state: FSMContext) -> None:
        """Обрабатывает перенос срока задачи."""

        user_id = message.from_user.id
        update_info = task_updates.get(user_id)

        if not update_info:
            await state.clear()
            await message.answer("Данные об обновлении задачи не найдены", reply_markup=main_menu_kb())
            return

        new_due_date = parse_date(message.text)
        if not new_due_date:
            await message.answer("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ")
            await message.delete()
            return

        update_info["new_due_date"] = new_due_date
        await state.set_state(TaskUpdate.waiting_for_postpone_reason)

        prompt = (
            "🕒 Новый срок: "
            f"{new_due_date.strftime('%d.%m.%Y')}\n"
            "💬 Укажите причину переноса задачи:"
        )

        await safe_edit_message_by_id(
            message.bot,
            chat_id=message.chat.id,
            message_id=update_info["message_id"],
            text=prompt,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data=(
                                f"back_task_detail:{update_info['task_id']}:{update_info['view']}"
                                f":{update_info['filter']}:{update_info['page']}"
                            ),
                        )
                    ],
                    [InlineKeyboardButton(text="🏠 Главная", callback_data="back_main")],
                ]
            ),
        )

        await message.delete()

    @dispatcher.message(TaskUpdate.waiting_for_postpone_reason)
    async def process_postpone_reason(message: Message, state: FSMContext) -> None:
        """Обрабатывает причину переноса срока задачи."""

        user_id = message.from_user.id
        update_info = task_updates.get(user_id)

        if not update_info or "new_due_date" not in update_info:
            await state.clear()
            task_updates.pop(user_id, None)
            await message.answer("Данные об обновлении задачи не найдены", reply_markup=main_menu_kb())
            await message.delete()
            return

        reason = (message.text or "").strip()
        if not reason:
            await message.answer("❌ Укажите причину переноса")
            await message.delete()
            return

        task = TASKS.get(update_info["task_id"])
        if task is None:
            await state.clear()
            task_updates.pop(user_id, None)
            await message.answer("Задача не найдена", reply_markup=main_menu_kb())
            await message.delete()
            return

        new_due_date = update_info["new_due_date"]
        task.due_date = new_due_date
        task.status_before_overdue = None

        role = detect_user_role(task, user_id)
        if role in {"author", "responsible"}:
            recalc_task_status(task)
        else:
            set_participant_status(task, user_id, TaskStatus.PAUSED)
            if task.current_executor_id == user_id:
                task.current_executor_id = None
            recalc_task_status(task)

        record_task_action(
            task,
            user_id,
            (
                "Отложил задачу до "
                f"{new_due_date.strftime('%d.%m.%Y')} (причина: {reason})"
            ),
        )
        await notify_task_participants(
            message.bot,
            task,
            user_id,
            (
                "отложил(а) задачу до "
                f"{new_due_date.strftime('%d.%m.%Y')} (причина: {reason})."
            ),
        )

        await state.clear()
        task_updates.pop(user_id, None)

        await safe_edit_message_by_id(
            message.bot,
            chat_id=message.chat.id,
            message_id=update_info["message_id"],
            text=build_task_detail_text(task, user_id),
            reply_markup=task_detail_kb(
                task,
                user_id,
                update_info["view"],
                update_info["filter"],
                update_info["page"],
            ),
        )

        await message.delete()

    @dispatcher.callback_query(F.data.startswith("confirm_completion:"))
    async def handle_confirm_completion(callback: CallbackQuery, state: FSMContext) -> None:
        """Подтверждает выполнение задачи автором."""

        task_id, participant_id, view, filter_type, page = extract_confirmation_context(callback.data)
        task = TASKS.get(task_id)

        if not task:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        user_id = callback.from_user.id
        if user_id not in {task.author_id, task.responsible_user_id}:
            await callback.answer(
                "Подтверждать выполнение могут только автор и ответственный",
                show_alert=True,
            )
            return

        participant_name = get_user_full_name(participant_id)

        set_participant_status(task, participant_id, TaskStatus.COMPLETED)
        if task.current_executor_id == participant_id:
            task.current_executor_id = None

        remove_pending_confirmation(task, participant_id)

        participants = [
            member_id
            for member_id in get_task_participants(task)
            if member_id != task.author_id
        ]
        all_completed = all(
            get_participant_status(task, member_id) == TaskStatus.COMPLETED
            for member_id in participants
        )

        if all_completed and participants:
            task.completed_date = datetime.now()
            task.status_before_overdue = None
        elif not all_completed:
            task.completed_date = None

        record_task_action(
            task,
            user_id,
            f"Подтвердил выполнение участника {participant_name}",
        )

        await notify_task_participants(
            callback.bot,
            task,
            user_id,
            f"подтвердил(а) выполнение участника {participant_name}.",
        )

        await render_task_detail(callback.message, task, user_id, view, filter_type, page)
        await callback.answer(f"Подтверждено: {participant_name}")

    @dispatcher.callback_query(F.data.startswith("return_task"))
    async def handle_return_task(callback: CallbackQuery, state: FSMContext) -> None:
        """Возвращает задачу в работу по решению автора."""

        task, view, filter_type, page = await ensure_task_for_action(callback, "return_task")
        if task is None:
            return

        user_id = callback.from_user.id
        if user_id != task.author_id:
            await callback.answer("Вернуть задачу может только автор", show_alert=True)
            return

        set_all_participants_status(task, TaskStatus.NEW)
        task.current_executor_id = None
        task.completed_date = None
        task.status_before_overdue = None
        clear_pending_confirmations(task)

        record_task_action(task, user_id, "Вернул задачу в работу")
        await notify_task_participants(
            callback.bot,
            task,
            user_id,
            "вернул(а) задачу в работу.",
        )

        await render_task_detail(callback.message, task, user_id, view, filter_type, page)
        await callback.answer("Задача возвращена в работу")

    return dispatcher

    return dispatcher


def run_bot_sync(config: BotConfig) -> None:
    """Запускает бота синхронно."""
    
    # Импортируем DefaultBotProperties
    from aiogram.client.default import DefaultBotProperties
    
    # Создаем бота с правильными параметрами
    bot = Bot(
        token=config.token, 
        default=DefaultBotProperties(parse_mode="HTML")
    )
    dispatcher = create_dispatcher()

    # Запускаем бота
    asyncio.run(dispatcher.start_polling(
        bot, 
        drop_pending_updates=config.drop_pending_updates
    ))