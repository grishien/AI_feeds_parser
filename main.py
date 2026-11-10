"""Точка входа News Digest Bot (roadmap, фаза 0).

``python main.py --dry-run`` — стартует, читает конфиг (CONFIG_DIR,
sources.yaml), пишет лог в файл с ротацией и в stdout, ничего не
отправляет.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional, Sequence

import config
from logging_setup import setup_logging


def _bool_arg(text: str) -> str:
    """Строка с пометкой ok/missing для безопасного логирования."""
    return "есть" if text else "нет"


def run(dry_run: bool = False) -> int:
    log_file = setup_logging()
    log = logging.getLogger("main")

    log.info("Старт News Digest Bot%s", " (dry-run)" if dry_run else "")
    log.info("Файл лога: %s", log_file)

    settings = config.load_settings()
    log.info("CONFIG_DIR: %s (.env %s)", settings.config_dir,
             "найден" if settings.env_found else "НЕ найден")
    log.info("DB_PATH: %s", settings.db_path)
    log.info(
        "Переменные окружения: TELEGRAM_BOT_TOKEN=%s, TELEGRAM_CHAT_ID=%s, "
        "LLM_BASE_URL=%s, LLM_API_KEY=%s, LLM_MODEL=%s, SCORE_THRESHOLD=%s",
        _bool_arg(settings.telegram_bot_token),
        _bool_arg(settings.telegram_chat_id),
        _bool_arg(settings.llm_base_url),
        _bool_arg(settings.llm_api_key),
        _bool_arg(settings.llm_model),
        settings.score_threshold,
    )

    try:
        sources_cfg = config.load_sources(settings.config_dir)
    except (FileNotFoundError, ValueError) as exc:
        log.error("Ошибка чтения sources.yaml: %s", exc)
        return 1

    log.info("sources.yaml: %s (источников: %d)", sources_cfg.path,
             len(sources_cfg.sources))

    profile = config.profile_path(settings.config_dir)
    log.info("profile.md: %s (%s)", profile, "есть" if profile.is_file() else "нет")

    if dry_run:
        log.info("Режим dry-run: сбор, оценка и отправка не выполняются")
        return 0

    log.warning("Реальные сбор/оценка/отправка будут добавлены в следующих фазах")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="News Digest Bot")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="только прочитать конфиг и залогировать, ничего не отправлять",
    )
    args = parser.parse_args(argv)
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
