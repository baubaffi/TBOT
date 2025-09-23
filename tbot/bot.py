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
from .greeting import greet_user
from .users import USERS, User, get_direction_label, get_users_by_direction
from .tasks import Task, TaskPriority, TaskStatus, create_task, TASKS, delete_task as remove_task

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
                InlineKeyboardButton(text="Завершенные", callback_data="filter_completed")
            ],
            [
                InlineKeyboardButton(text="Все задачи", callback_data="filter_all")
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_{back_to}")
            ]
        ]
    )


# Сопоставления для отображения статусов и приоритетов
STATUS_ICONS = {
    TaskStatus.NEW: "🆕",
    TaskStatus.ACTIVE: "🔄",
    TaskStatus.PAUSED: "⏸️",
    TaskStatus.COMPLETED: "✅",
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
                text=f"{selected}{user.first_name}", 
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
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back_task_creation"),
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
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def task_detail_kb(task_id: int, is_author: bool, view: str, filter_type: str, page: int):
    """Создает клавиатуру действий на экране деталей задачи."""

    buttons: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="🔄 Взять в работу", callback_data=f"take_task_{task_id}"),
            InlineKeyboardButton(text="⏸️ Отложить", callback_data=f"pause_task_{task_id}"),
        ]
    ]

    if is_author:
        buttons.append([
            InlineKeyboardButton(
                text="🗑️ Удалить/Отменить задачу",
                callback_data=f"delete_task:{task_id}:{view}:{filter_type}:{page}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="◀️ К списку", callback_data=f"tasks_page:{view}:{filter_type}:{page}"),
    ])
    buttons.append([
        InlineKeyboardButton(text="📋 Главное меню", callback_data="back_main"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_tasks_list_text(tasks: list[Task], filter_text: str, page: int) -> str:
    """Формирует текстовое представление списка задач с нумерацией."""

    total_pages = max(1, (len(tasks) + TASKS_PER_PAGE - 1) // TASKS_PER_PAGE)
    start_index = (page - 1) * TASKS_PER_PAGE
    page_tasks = tasks[start_index:start_index + TASKS_PER_PAGE]

    lines: list[str] = [f"📋 <b>{filter_text.capitalize()} задачи</b>"]
    lines.append("")

    for idx, task in enumerate(page_tasks, start=start_index + 1):
        status_icon = STATUS_ICONS.get(task.status, "❓")
        priority_icon = PRIORITY_ICONS.get(task.priority, "⚪")
        overdue_icon = "⏰ " if task.due_date and task.due_date < datetime.now() and task.status != TaskStatus.COMPLETED else ""
        responsible_name = USERS[task.responsible_user_id].first_name if task.responsible_user_id in USERS else "Неизвестный"
        due_date = task.due_date.strftime('%d.%m.%Y') if task.due_date else "Без срока"

        lines.extend([
            f"{idx}. {status_icon} {priority_icon} {overdue_icon}<b>{task.title}</b>",
            f"   👤 {responsible_name}",
            f"   📅 {due_date}",
            "",
        ])

    lines.append(f"Страница {page} из {total_pages}")
    return "\n".join(lines)


def build_task_detail_text(task: Task) -> str:
    """Формирует подробное описание задачи."""

    responsible_name = USERS[task.responsible_user_id].first_name if task.responsible_user_id in USERS else "Неизвестный"
    author_name = USERS[task.author_id].first_name if task.author_id in USERS else "Неизвестный"
    due_date = task.due_date.strftime('%d.%m.%Y') if task.due_date else "Не указан"
    created = task.created_date.strftime('%d.%m.%Y')
    workgroup_names = [
        USERS[user_id].first_name
        for user_id in task.workgroup
        if user_id in USERS
    ]
    workgroup_text = ", ".join(workgroup_names) if workgroup_names else "Не указана"
    description = task.description or "Не указано"
    project_name = PROJECTS.get(task.project, "Не указан")
    direction_name = get_direction_label(task.direction) if task.direction else "Не указано"
    status_icon = STATUS_ICONS.get(task.status, "❓")
    priority_icon = PRIORITY_ICONS.get(task.priority, "⚪")

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

    if task.completed_date:
        lines.append(f"🏁 Завершена: {task.completed_date.strftime('%d.%m.%Y')}")

    return "\n".join(lines)


# Кнопки действий с задачей
def task_actions_kb(task_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Взять в работу", callback_data=f"take_task_{task_id}"),
                InlineKeyboardButton(text="⏸️ Отложить", callback_data=f"pause_task_{task_id}"),
            ],
            [
                InlineKeyboardButton(text="📋 Главное меню", callback_data="back_main"),
            ]
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
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")
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
    
    # Краткая статистика
    user_tasks = [task for task in TASKS.values() if user_id in task.workgroup or task.responsible_user_id == user_id]
    active_tasks = [task for task in user_tasks if task.status == TaskStatus.ACTIVE]
    overdue_tasks = [task for task in user_tasks if task.due_date and task.due_date < datetime.now() and task.status != TaskStatus.COMPLETED]
    
    stats_text = (
        f"{greeting}\n\n"
        "📊 <b>Краткая статистика:</b>\n"
        f"📋 Задачи на сегодня: {len([t for t in active_tasks if t.due_date and t.due_date.date() == datetime.now().date()])}\n"
        f"📈 Всего задач: {len(user_tasks)}\n"
        f"⏰ Просрочено: {len(overdue_tasks)}\n"
        f"🔄 В работе: {len(active_tasks)}\n"
        f"✅ Завершено: {len([t for t in user_tasks if t.status == TaskStatus.COMPLETED])}\n"
        f"🆕 Новых задач: {len([t for t in user_tasks if t.status == TaskStatus.NEW])}"
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
                USERS[user_id].first_name
                for user_id in responsible_users
                if user_id in USERS
            ]
            if names:
                lines.append(f"👤 Ответственный: {', '.join(names)}")

        workgroup_users = data.get("workgroup_users")
        if workgroup_users:
            names = [
                USERS[user_id].first_name
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

            # Отправляем уведомления
            bot = callback.bot
            all_notified_users = {responsible_user_id}
            all_notified_users.update(workgroup_users)

            responsible_user = USERS.get(responsible_user_id)
            responsible_name = responsible_user.first_name if responsible_user else "Неизвестный"

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
                        reply_markup=task_actions_kb(task.task_id)
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

        if view == "my":
            return [task for task in TASKS.values() if user_id in task.workgroup or task.responsible_user_id == user_id]
        return list(TASKS.values())

    def filter_tasks(tasks: list[Task], filter_type: str) -> tuple[list[Task], str]:
        """Применяет фильтр к списку задач и возвращает текст фильтра."""

        if filter_type == "active":
            return [task for task in tasks if task.status == TaskStatus.ACTIVE], "активные"
        if filter_type == "completed":
            return [task for task in tasks if task.status == TaskStatus.COMPLETED], "завершенные"
        return tasks, "все"

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
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")],
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

        text = build_task_detail_text(task)
        keyboard = task_detail_kb(task.task_id, callback.from_user.id == task.author_id, view, filter_type, page)

        await safe_edit_message(
            callback.message,
            text=text,
            reply_markup=keyboard,
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
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")],
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
    @dispatcher.callback_query(F.data.startswith("take_task_"))
    async def handle_take_task(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает взятие задачи в работу."""
        task_id = int(callback.data.replace("take_task_", ""))
        
        if task_id in TASKS:
            task = TASKS[task_id]
            task.status = TaskStatus.ACTIVE

            taken_text = (
                "✅ <b>Задача взята в работу!</b>\n\n"
                f"📝 <b>{task.title}</b>\n"
                "🔄 Статус: В работе\n"
                f"👤 Ответственный: {USERS[task.responsible_user_id].first_name if task.responsible_user_id in USERS else 'Неизвестный'}"
            )
            await safe_edit_message(
                callback.message,
                text=taken_text,
                reply_markup=main_menu_kb(),
            )
        else:
            await callback.answer("❌ Задача не найдена!")
        
        await callback.answer()

    @dispatcher.callback_query(F.data.startswith("pause_task_"))
    async def handle_pause_task(callback: CallbackQuery, state: FSMContext) -> None:
        """Обрабатывает приостановку задачи."""
        task_id = int(callback.data.replace("pause_task_", ""))
        
        if task_id in TASKS:
            task = TASKS[task_id]
            task.status = TaskStatus.PAUSED

            paused_text = (
                "⏸️ <b>Задача приостановлена</b>\n\n"
                f"📝 <b>{task.title}</b>\n"
                "⏸️ Статус: На паузе\n"
                f"👤 Ответственный: {USERS[task.responsible_user_id].first_name if task.responsible_user_id in USERS else 'Неизвестный'}"
            )
            await safe_edit_message(
                callback.message,
                text=paused_text,
                reply_markup=main_menu_kb(),
            )
        else:
            await callback.answer("❌ Задача не найдена!")
        
        await callback.answer()

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