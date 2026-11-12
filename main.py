"""Точка входа News Digest Bot (roadmap).

``python main.py --dry-run`` — стартует, читает конфиг (CONFIG_DIR,
sources.yaml), пишет лог в файл с ротацией и в stdout, ничего не
отправляет (фаза 0).

Обычный запуск (фаза 1.5): сбор статей из RSS-источников → сохранение
новых в SQLite (дедупликация по URL) → отправка «название + ссылка» в
Telegram → mark_sent. Ошибка одного фида не роняет запуск. Ошибка
отправки не теряет статью: статус error (error_stage=send), повторная
попытка при следующих запусках.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional, Sequence

import httpx

import config
import notifier
from article import Article
from db import Database
from logging_setup import setup_logging

log = logging.getLogger("main")


def _bool_arg(text: str) -> str:
    """Строка с пометкой ok/missing для безопасного логирования."""
    return "есть" if text else "нет"


def collect_and_save(db: Database, sources: List[dict]) -> int:
    """Собрать статьи из всех источников и сохранить новые в БД.

    Возвращает число реально добавленных статей. Ошибка одного фида
    не влияет на остальные (коллектор возвращает пустой список).
    """
    added = 0
    for source in sources:
        name = str(source.get("name") or "unnamed")
        url = str(source.get("url") or "").strip()
        if not url:
            log.warning("Источник %s: пустой url, пропущен", name)
            continue
        articles = collect_feed(url, name)
        for article in articles:
            if db.save(article):
                added += 1
    log.info("Сбор завершён: новых статей %d", added)
    return added


def collect_feed(feed_url: str, name: str) -> List[Article]:
    """Обёртка для тестируемости; сами фиды обрабатывает collectors."""
    from collectors.rss import collect_rss
    return collect_rss(feed_url, name)


def deliver(db: Database, token: str, chat_id: str,
            client: Optional[httpx.Client] = None) -> tuple[int, int]:
    """Отправить неотправленные статьи в Telegram.

    Порядок: сначала статьи, ожидающие повторной отправки после ошибки
    (error + error_stage=send, roadmap: жизненный цикл), затем новые
    (status=new). После успешной отправки — mark_sent; при ошибке
    статус error (error_stage=send), статья остаётся в БД и будет
    повторена при следующем запуске.

    Возвращает (отправлено, осталось неотправленными).
    """
    sent = failed = 0

    targets = db.get_retryable()
    for article in targets:
        message = notifier.build_article_message(article)
        if notifier.send_message(token, str(chat_id), message, client=client):
            db.mark_sent(article.url)
            log.info("Повторная отправка успешна: %s", article.url)
            sent += 1
        else:
            db.update_status(article.url, "error", error_stage="send",
                             last_error="telegram send failed (retry)",
                             increment_retry=True)
            log.error("Повторная отправка не удалась: %s", article.url)
            failed += 1

    for article in db.get_pending():
        message = notifier.build_article_message(article)
        if notifier.send_message(token, str(chat_id), message, client=client):
            db.mark_sent(article.url)
            log.info("Отправлено: %s", article.url)
            sent += 1
        else:
            db.update_status(article.url, "error", error_stage="send",
                             last_error="telegram send failed",
                             increment_retry=True)
            log.error("Не отправлено (error/send): %s", article.url)
            failed += 1

    log.info("Отправка завершена: отправлено %d, не удалось %d", sent, failed)
    return sent, failed


def retryable_send_rows(db: Database):
    """Ошибки отправки, готовые к повтору (строки БД)."""
    return db.get_retryable()


def run(dry_run: bool = False) -> int:
    log_file = setup_logging()

    log.info("Старт News Digest Bot%s", " (dry-run)" if dry_run else "")
    log.info("Файл лога: %s", log_file)

    settings = config.load_settings()
    log.info("CONFIG_DIR: %s (.env %s)", settings.config_dir,
             "найден" if settings.env_found else "НЕ найден")
    log.info("DB_PATH: %s", settings.db_path)
    log.info(
        "Переменные окружения: TELEGRAM_BOT_TOKEN=%s, TELEGRAM_CHAT_ID=%s",
        _bool_arg(settings.telegram_bot_token),
        _bool_arg(settings.telegram_chat_id),
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

    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        log.error("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы "
                  "(.env в %s) — отправка невозможна", settings.config_dir)
        return 1

    db = Database(settings.db_path)
    try:
        collect_and_save(db, sources_cfg.sources)
        sent, failed = deliver(db, settings.telegram_bot_token,
                               str(settings.telegram_chat_id))
    finally:
        db.close()

    log.info("Завершено: отправлено %d, с ошибкой %d", sent, failed)
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
