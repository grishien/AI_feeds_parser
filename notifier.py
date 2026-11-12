"""Отправка сообщений в Telegram Bot API (roadmap, фаза 1.4).

``sendMessage`` с ``parse_mode=HTML``: весь пользовательский текст
экранируется, обработка 429 — пауза по ``retry_after`` и повтор.
"""

from __future__ import annotations

import html
import logging
import time
from typing import Optional

import httpx

from article import Article

log = logging.getLogger("notifier")

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
# 429 может прийти несколько раз подряд; после max_attempts сдаёмся
MAX_ATTEMPTS = 3
# Небольшой запас сверх retry_after, чтобы не попасть в следующее окно
RETRY_BUFFER_S = 1.0


def escape_html(text: str) -> str:
    """Экранирование текста для parse_mode=HTML."""
    return html.escape(text or "", quote=False)


def build_article_message(article: Article) -> str:
    """Сообщение фазы 1: название + ссылка (HTML, текст экранирован)."""
    title = escape_html(article.title) or escape_html(article.url)
    return f"{title}\n{escape_html(article.url)}"


def send_message(
    token: str,
    chat_id: str,
    text: str,
    *,
    client: Optional[httpx.Client] = None,
    sleep: callable = time.sleep,
    max_attempts: int = MAX_ATTEMPTS,
) -> bool:
    """Отправить текст в Telegram. True — успех, False — не удалось.

    429: пауза по ``parameters.retry_after`` (из тела ответа) и повтор.
    ``client`` и ``sleep`` заменяемы — так тестируется логика 429 без
    реальных запросов.
    """
    owned_client = client is None
    if owned_client:
        client = httpx.Client(timeout=30)
    try:
        url = API_URL.format(token=token)
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        for attempt in range(1, max_attempts + 1):
            try:
                resp = client.post(url, json=payload)
            except httpx.HTTPError as exc:
                log.error("Telegram: сетевая ошибка (попытка %d/%d): %s",
                          attempt, max_attempts, exc)
                continue

            if resp.status_code == 200:
                log.info("Telegram: сообщение отправлено")
                return True

            if resp.status_code == 429:
                retry_after = _extract_retry_after(resp)
                log.warning(
                    "Telegram: 429, пауза %s c (попытка %d/%d)",
                    retry_after, attempt, max_attempts,
                )
                if attempt < max_attempts:
                    sleep(retry_after + RETRY_BUFFER_S)
                    continue
                return False

            # прочие 4xx/5xx — повторять бессмысленно, кроме 5xx
            detail = _extract_description(resp)
            if resp.status_code >= 500 and attempt < max_attempts:
                log.warning("Telegram: %s (попытка %d/%d): %s",
                            resp.status_code, attempt, max_attempts, detail)
                sleep(2.0)
                continue
            log.error("Telegram: отправка не удалась: HTTP %s: %s",
                      resp.status_code, detail)
            return False

        return False
    finally:
        if owned_client:
            client.close()


def _extract_retry_after(resp: httpx.Response) -> float:
    try:
        params = (resp.json() or {}).get("parameters") or {}
        return float(params.get("retry_after", 1.0))
    except ValueError:
        return 1.0


def _extract_description(resp: httpx.Response) -> str:
    try:
        return str((resp.json() or {}).get("description", resp.text))
    except ValueError:
        return resp.text[:200]
