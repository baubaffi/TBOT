"""CLI-скрипт для запуска телеграм-бота TBOT."""

from __future__ import annotations

import argparse
import os
from typing import Optional

from tbot.bot import BotConfig, run_bot_sync

# Добавьте загрузку .env файла
from dotenv import load_dotenv
load_dotenv()


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Разбирает аргументы командной строки."""

    parser = argparse.ArgumentParser(description="Запуск телеграм-бота TBOT")
    parser.add_argument(
        "--token",
        help="Токен телеграм-бота. Если не указан, будет использована переменная окружения TBOT_TOKEN.",
    )
    parser.add_argument(
        "--keep-updates",
        action="store_true",
        help="Не отбрасывать накопившиеся апдейты при запуске.",
    )
    return parser.parse_args(argv)


def resolve_token(cli_token: Optional[str]) -> str:
    """Определяет токен бота из аргументов или переменных окружения."""

    token = cli_token or os.getenv("TBOT_TOKEN")
    if not token:
        raise RuntimeError(
            "Токен телеграм-бота не передан. Укажите его аргументом --token или через переменную окружения TBOT_TOKEN."
        )
    return token


def main(argv: Optional[list[str]] = None) -> None:
    """Точка входа CLI."""

    args = parse_args(argv)
    token = resolve_token(args.token)

    config = BotConfig(token=token, drop_pending_updates=not args.keep_updates)
    run_bot_sync(config)


if __name__ == "__main__":
    main()