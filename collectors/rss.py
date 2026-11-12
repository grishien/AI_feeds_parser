"""RSS-коллектор на feedparser (roadmap, фаза 1.2).

Принимает URL фида, возвращает список ``Article``. Ошибка одного фида
(сеть, невалидный XML, 4xx/5xx) не роняет весь запуск: возвращается
пустой список, ошибка логируется.
"""

from __future__ import annotations

import calendar
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import feedparser

from article import Article

log = logging.getLogger("collectors.rss")

USER_AGENT = "NewsDigestBot/0.1 (+feedparser)"


def _entry_datetime(entry: object) -> Optional[datetime]:
    """Дата публикации записи: published_parsed или updated_parsed."""
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                ts = calendar.timegm(parsed)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (OverflowError, ValueError, TypeError):
                continue
    return None


def collect_rss(feed_url: str, source_name: str = "") -> List[Article]:
    """Скачать и разобрать RSS/Atom-фид.

    Возвращает список статей с непустым URL (link). Записи без ссылки
    пропускаются. Любая ошибка фида логируется и приводит к пустому
    списку, а не к исключению — сбой одного фида не влияет на остальные.
    """
    try:
        feed = feedparser.parse(feed_url, agent=USER_AGENT)
    except Exception as exc:  # защита всего запуска от одного фида
        log.error("Фид %s (%s): ошибка разбора: %s", feed_url, source_name, exc)
        return []

    status = feed.get("status")
    if status is not None and status >= 400:
        log.error("Фид %s (%s): HTTP %s, записей не получено",
                  feed_url, source_name, status)
        return []

    if feed.bozo and not feed.entries:
        # bozo при валидном, но нестрогом XML допустим; фид без записей — нет
        log.error("Фид %s (%s): невалидный документ: %s",
                  feed_url, source_name, feed.get("bozo_exception"))
        return []

    if feed.bozo:
        log.warning("Фид %s (%s): нестрогий XML: %s",
                    feed_url, source_name, feed.get("bozo_exception"))

    articles: List[Article] = []
    for entry in feed.entries:
        url = (entry.get("link") or "").strip()
        if not url:
            log.warning("Фид %s (%s): запись без ссылки пропущена: %r",
                        feed_url, source_name, entry.get("title"))
            continue
        articles.append(Article(
            url=url,
            title=(entry.get("title") or "").strip(),
            text=(entry.get("summary") or entry.get("description") or "").strip(),
            source=source_name,
            published_at=_entry_datetime(entry),
        ))

    log.info("Фид %s (%s): получено статей %d", feed_url, source_name, len(articles))
    return articles
