"""Проверка db.py (фаза 1.1) на реальной SQLite-БД во временном каталоге."""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from article import Article
from db import Database

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name} {detail}")
    if not cond:
        failures.append(name)


tmp = Path(__file__).resolve().parent / "tmp_check_db"
tmp.mkdir(exist_ok=True)
db_path = tmp / "check.db"
if db_path.exists():
    db_path.unlink()

db = Database(db_path)

# Схема
cols = {r[1] for r in db.conn.execute("PRAGMA table_info(articles)")}
expected = {
    "url", "title", "text", "source", "published_at", "status",
    "score", "reason", "project", "error_stage", "last_error",
    "retry_count", "next_retry_at", "sent_at", "created_at",
}
check("schema: все поля", expected <= cols, f"missing={expected - cols}")
pk = [r[1] for r in db.conn.execute("PRAGMA table_info(articles)") if r[5]]
check("schema: url = PRIMARY KEY", pk == ["url"])

dt = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
a1 = Article(url="https://example.com/a1", title="A1", text="text a1",
             source="test", published_at=dt)

# save / is_seen / дубликаты
check("save: новая статья", db.save(a1) is True)
check("save: дубликат отклонён", db.save(a1) is False)
check("is_seen: true", db.is_seen("https://example.com/a1") is True)
check("is_seen: false", db.is_seen("https://example.com/other") is False)

# published_at корректно сохранился
row = db.conn.execute("SELECT * FROM articles WHERE url='https://example.com/a1'").fetchone()
check("save: статус new", row["status"] == "new")
check("save: published_at", row["published_at"] == dt.isoformat())
check("save: retry_count=0", row["retry_count"] == 0)

# get_pending
a2 = Article(url="https://example.com/a2", title="A2", source="test")
db.save(a2)
pending = db.get_pending()
check("get_pending: обе новые", [p.url for p in pending] == ["https://example.com/a1", "https://example.com/a2"])
check("get_pending: Article восстановлена",
      pending[0].title == "A1" and pending[0].source == "test"
      and pending[0].published_at == dt and pending[0].text == "text a1")

# update_status -> scored с оценкой
db.update_status("https://example.com/a1", "scored", score=8, reason="r", project="p")
row = db.conn.execute("SELECT * FROM articles WHERE url='https://example.com/a1'").fetchone()
check("update_status: scored", row["status"] == "scored" and row["score"] == 8
      and row["reason"] == "r" and row["project"] == "p")
check("get_pending: исключает scored", [p.url for p in db.get_pending()] == ["https://example.com/a2"])

# mark_sent
db.mark_sent("https://example.com/a1")
row = db.conn.execute("SELECT * FROM articles WHERE url='https://example.com/a1'").fetchone()
check("mark_sent: sent + sent_at", row["status"] == "sent" and row["sent_at"] is not None)

# error + retry
db.update_status("https://example.com/a2", "error", error_stage="send",
                 last_error="boom", increment_retry=True,
                 next_retry_at=datetime.now(timezone.utc) - timedelta(minutes=1))
row = db.conn.execute("SELECT * FROM articles WHERE url='https://example.com/a2'").fetchone()
check("update_status: error", row["status"] == "error" and row["error_stage"] == "send"
      and row["last_error"] == "boom" and row["retry_count"] == 1)

retryable = db.get_retryable()
check("get_retryable: просроченная доступна", [r.url for r in retryable] == ["https://example.com/a2"])

db.update_status("https://example.com/a2", "error", error_stage="send",
                 next_retry_at=datetime.now(timezone.utc) + timedelta(hours=1))
check("get_retryable: будущая отложена", db.get_retryable() == [])

# валидация статусов
try:
    db.update_status("https://example.com/a2", "bogus")
    check("update_status: invalid rejected", False)
except ValueError:
    check("update_status: invalid rejected", True)
try:
    db.update_status("https://example.com/a2", "error")
    check("error требует error_stage", False, "не упало")
except ValueError:
    check("error требует error_stage", True, "ValueError без error_stage")

db.close()

# очистка временной БД
if db_path.exists():
    db_path.unlink()
tmp.rmdir()

print()
print("ИТОГ:", "ПРОВАЛ: " + ", ".join(failures) if failures else "все проверки пройдены")
sys.exit(1 if failures else 0)
