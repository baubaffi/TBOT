"""Пакет с логикой телеграм‑бота."""

from .greeting import greet_user
from .bot import BotConfig, run_bot_sync

__all__ = ["greet_user", "BotConfig", "run_bot_sync"]
