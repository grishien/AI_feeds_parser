"""Работа с SQLite (roadmap, фаза 1.1).

Каждая статья идентифицируется уникальным URL (PRIMARY KEY) и имеет
статус обработки: ``new``, ``scored``, ``sent``, ``error``.

Жизненный цикл (см. roadmap):
- повторное обнаружение URL не создаёт дубликат;
- ошибка не приводит к потере статьи (``error`` + ``error_stage``);
- ``sent`` ставится только после успешной отправки.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from article import Article

log = logging.getLogger("db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    url           TEXT PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT '',
    text          TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT '',
    published_at  TEXT,
    status        TEXT NOT NULL DEFAULT 'new',
    score         REAL,
    reason        TEXT,
    project       TEXT,
    error_stage   TEXT,
    last_error    TEXT,
    retry_count   INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    sent_at       TEXT,
    created_at    TEXT NOT NULL
);
"""

VALID_STATUSES = ("new", "scored", "sent", "error")
VALID_ERROR_STAGES = ("fetch", "score", "send")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _iso_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class Database:
    """Обёртка над SQLite: подключение по ленивой схеме и операции статей."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------
    # Внутренние утилиты
    # ------------------------------------------------------------------

    def _row_to_article(self, row: sqlite3.Row) -> Article:
        return Article(
            url=row["url"],
            title=row["title"],
            text=row["text"],
            source=row["source"],
            published_at=_iso_dt(row["published_at"]),
        )

    # ------------------------------------------------------------------
    # Публичный API (roadmap 1.1)
    # ------------------------------------------------------------------

    def is_seen(self, url: str) -> bool:
        """True, если статья с таким URL уже есть в БД (дедупликация)."""
        row = self.conn.execute(
            "SELECT 1 FROM articles WHERE url = ?", (url,)
        ).fetchone()
        return row is not None

    def save(self, article: Article) -> bool:
        """Сохранить статью со статусом ``new``.

        Возвращает True, если статья добавлена, False — если URL уже
        известен (дубликат не создаётся, существующая запись не трогается).
        """
        if self.is_seen(article.url):
            return False
        self.conn.execute(
            """
            INSERT INTO articles
                (url, title, text, source, published_at, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'new', ?)
            """,
            (
                article.url,
                article.title,
                article.text,
                article.source,
                _dt_iso(article.published_at),
                _now_iso(),
            ),
        )
        self.conn.commit()
        return True

    def update_status(
        self,
        url: str,
        status: str,
        *,
        score: Optional[float] = None,
        reason: Optional[str] = None,
        project: Optional[str] = None,
        error_stage: Optional[str] = None,
        last_error: Optional[str] = None,
        increment_retry: bool = False,
        next_retry_at: Optional[datetime] = None,
    ) -> None:
        """Обновить статус статьи и связанные поля.

        ``status='error'`` требует указания ``error_stage``
        (``fetch``, ``score`` или ``send``).
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"Неизвестный статус: {status!r}")
        if error_stage is not None and error_stage not in VALID_ERROR_STAGES:
            raise ValueError(f"Неизвестный error_stage: {error_stage!r}")
        if status == "error" and error_stage is None:
            raise ValueError("Статус 'error' требует указания error_stage")

        fields: list[str] = ["status = ?"]
        params: list[object] = [status]

        for name, value in (
            ("score", score),
            ("reason", reason),
            ("project", project),
            ("error_stage", error_stage),
            ("last_error", last_error),
        ):
            if value is not None:
                fields.append(f"{name} = ?")
                params.append(value)

        if increment_retry:
            fields.append("retry_count = retry_count + 1")

        if next_retry_at is not None:
            fields.append("next_retry_at = ?")
            params.append(_dt_iso(next_retry_at))

        params.append(url)
        self.conn.execute(
            f"UPDATE articles SET {', '.join(fields)} WHERE url = ?", params
        )
        self.conn.commit()

    def mark_sent(self, url: str) -> None:
        """Отметить статью отправленной (только после успешной отправки)."""
        self.conn.execute(
            "UPDATE articles SET status = 'sent', sent_at = ? WHERE url = ?",
            (_now_iso(), url),
        )
        self.conn.commit()

    def get_pending(self, limit: Optional[int] = None) -> List[Article]:
        """Статьи со статусом ``new``, ожидающие обработки.

        Возвращаются вместе с полями БД через атрибут ``db_fields``
        (score/reason/project/status) — нужно фазам оценки и отправки.
        """
        sql = "SELECT * FROM articles WHERE status = 'new' ORDER BY created_at"
        if limit is not None:
            sql += " LIMIT ?"
            rows = self.conn.execute(sql, (limit,)).fetchall()
        else:
            rows = self.conn.execute(sql).fetchall()
        return [self._row_to_article(row) for row in rows]

    def get_retryable(self, limit: Optional[int] = None) -> List[Article]:
        """Ошибочные статьи, готовые к повторной попытке.

        Условия: ``status = 'error'`` и (``next_retry_at`` пуст или уже
        наступил). Ошибки отправки (``error_stage='send'``) повторяются
        неограниченно; для прочих этапов ограничения попыток задаются
        вызывающей стороной через ``retry_count``.
        """
        now_iso = _now_iso()
        sql = """
            SELECT * FROM articles
            WHERE status = 'error'
              AND (next_retry_at IS NULL OR next_retry_at <= ?)
            ORDER BY created_at
        """
        if limit is not None:
            sql += " LIMIT ?"
            rows = self.conn.execute(sql, (now_iso, limit)).fetchall()
        else:
            rows = self.conn.execute(sql, (now_iso,)).fetchall()
        return [self._row_to_article(row) for row in rows]


