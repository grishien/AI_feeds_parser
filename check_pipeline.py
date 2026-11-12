"""Проверка связки фазы 1.5 на реальных данных.

Сбор — настоящий (реальные фиды Хабра, реальная SQLite во временной
папке). Отправка — настоящая логика notifier.py поверх
httpx.MockTransport (подменён только сетевой транспорт Telegram),
поскольку .env с реальным токеном ещё нет — реальный прогон выполняет
пользователь.

Проверяем:
- новые статьи сохраняются и «отправляются»;
- повторный запуск не создаёт дубликатов и не отправляет повторно;
- ошибка отправки не теряет статью (error/send) и повторяется в следующем
  запуске.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from db import Database
from main import collect_and_save, deliver

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name} {detail}")
    if not cond:
        failures.append(name)


class TelegramMock:
    """Счётчик отправленных сообщений (транспорт для notifier)."""

    def __init__(self, fail_urls: set[str] | None = None):
        self.sent: list[str] = []
        self.fail_urls = fail_urls or set()

    def client(self) -> httpx.Client:
        outer = self

        def handler(request: httpx.Request) -> httpx.Response:
            import json
            payload = json.loads(request.read())
            text = payload["text"]
            url_line = text.rsplit("\n", 1)[-1].replace("&amp;", "&")
            if any(f in url_line for f in outer.fail_urls):
                return httpx.Response(500, json={"ok": False})
            outer.sent.append(url_line)
            return httpx.Response(200, json={"ok": True, "result": {}})

        return httpx.Client(transport=httpx.MockTransport(handler))


tmp = Path(__file__).resolve().parent / "tmp_check_pipeline"
tmp.mkdir(exist_ok=True)
db_path = tmp / "check.db"
if db_path.exists():
    db_path.unlink()

sources = config.load_sources().sources
check("источники из sources.yaml", len(sources) >= 1, f"n={len(sources)}")
# ограничиваем объём для проверки: первый источник
sources = sources[:1]

tg = TelegramMock()
db = Database(db_path)

# --- Запуск 1: сбор + отправка ---
added = collect_and_save(db, sources)
check("запуск 1: статьи добавлены", added > 0, f"added={added}")
sent, failed = deliver(db, "TOK", "123", client=tg.client())
check("запуск 1: отправлено всё новое", sent == added and failed == 0,
      f"sent={sent} failed={failed}")
check("запуск 1: в БД нет незавершённых",
      db.conn.execute("SELECT count(*) FROM articles WHERE status != 'sent'").fetchone()[0] == 0)

# --- Запуск 2: те же фиды, дубликатов быть не должно ---
urls_run1 = {r[0] for r in db.conn.execute("SELECT url FROM articles")}
added2 = collect_and_save(db, sources)
sent2, failed2 = deliver(db, "TOK", "123", client=tg.client())
urls_run2 = {r[0] for r in db.conn.execute("SELECT url FROM articles")}
new_urls = urls_run2 - urls_run1
check("запуск 2: новые URL не пересекаются с уже виденными (дедупликация)",
      not (new_urls & urls_run1), f"new={len(new_urls)}")
total_rows = db.conn.execute("SELECT count(*) FROM articles").fetchone()[0]
check("запуск 2: в БД ровно столько строк, сколько добавлено за оба запуска",
      total_rows == len(urls_run2) == len(urls_run1) + len(new_urls),
      f"rows={total_rows} run1={len(urls_run1)} new={len(new_urls)}")
check("запуск 2: отправлены только новые", sent2 == len(new_urls),
      f"sent2={sent2}")

# --- Запуск 3: сбой Telegram не теряет статью, повтор в следующем запуске ---
# Искусственная ситуация: статья с уникальным URL, отправка на неё падает
art = type(db.get_pending()[0]) if db.get_pending() else None
from article import Article
art = Article(url="https://habr.com/ru/fake/send-fail/", title="Send fail test",
              source="test")
db.save(art)
tg_fail = TelegramMock(fail_urls={"send-fail"})
sent3, failed3 = deliver(db, "TOK", "123", client=tg_fail.client())
check("запуск 3: сбойная статья не отправлена", failed3 == 1 and sent3 == 0)
row = db.conn.execute(
    "SELECT * FROM articles WHERE url='https://habr.com/ru/fake/send-fail/'").fetchone()
check("запуск 3: статус error + error_stage=send + last_error",
      row["status"] == "error" and row["error_stage"] == "send"
      and row["last_error"] and row["retry_count"] == 1)
check("запуск 3: статья сохранена (не потеряна)", row["url"] is not None)

# Запуск 4: Telegram работает — ошибочная статья повторно отправляется
tg_ok = TelegramMock()
sent4, failed4 = deliver(db, "TOK", "123", client=tg_ok.client())
check("запуск 4: повторная отправка успешна", sent4 == 1 and failed4 == 0)
row = db.conn.execute(
    "SELECT * FROM articles WHERE url='https://habr.com/ru/fake/send-fail/'").fetchone()
check("запуск 4: статус sent, sent_at проставлен",
      row["status"] == "sent" and row["sent_at"] is not None)

db.close()

# очистка временной БД
if db_path.exists():
    db_path.unlink()
tmp.rmdir()

print()
print("ИТОГ:", "ПРОВАЛ: " + ", ".join(failures) if failures else "все проверки пройдены")
sys.exit(1 if failures else 0)
