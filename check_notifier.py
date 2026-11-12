"""Проверка notifier.py (фаза 1.4): HTML-экранирование и 429.

Реальные вызовы send_message выполняются против httpx.MockTransport —
подменяется только сетевой транспорт, вся логика нотифаера настоящая.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from article import Article
from notifier import build_article_message, escape_html, send_message

failures: list[str] = []
sleeps: list[float] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name} {detail}")
    if not cond:
        failures.append(name)


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def fake_sleep(seconds: float) -> None:
    sleeps.append(seconds)


# 1. Экранирование HTML
check("escape_html: <,>,&", escape_html("<a>&b") == "&lt;a&gt;&amp;b")
msg = build_article_message(Article(url="https://x.y/?a=1&b=2", title="<T1> & T2"))
check("build_article_message: title экранирован", "&lt;T1&gt; &amp; T2" in msg, msg)
check("build_article_message: url экранирован", "https://x.y/?a=1&amp;b=2" in msg)

# 2. Успешная отправка 200, проверка payload
captured: dict = {}

def handler_200(request: httpx.Request) -> httpx.Response:
    captured["url"] = str(request.url)
    captured["json"] = request.read().decode()
    return httpx.Response(200, json={"ok": True, "result": {}})

ok = send_message("TOK", 123, "hello", client=make_client(handler_200), sleep=fake_sleep)
check("200: отправлено", ok is True)
check("200: URL содержит токен", "/botTOK/sendMessage" in captured["url"])
import json as _json

check("200: payload parse_mode=HTML",
      _json.loads(captured["json"]).get("parse_mode") == "HTML")

# 3. 429 с retry_after=2: пауза, затем успех
state = {"n": 0}

def handler_429(request: httpx.Request) -> httpx.Response:
    state["n"] += 1
    if state["n"] == 1:
        return httpx.Response(429, json={"ok": False,
                                         "parameters": {"retry_after": 2}})
    return httpx.Response(200, json={"ok": True})

ok = send_message("TOK", 123, "hi", client=make_client(handler_429), sleep=fake_sleep)
check("429: вторая попытка успешна", ok is True)
check("429: пауза = retry_after + буфер", sleeps[-1:] == [3.0], str(sleeps[-1:]))

# 4. Стойкий 429: max_attempts исчерпаны, False
state["n"] = 0
def handler_429_forever(request: httpx.Request) -> httpx.Response:
    state["n"] += 1
    return httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 1}})

before = len(sleeps)
ok = send_message("TOK", 123, "hi", client=make_client(handler_429_forever),
                  sleep=fake_sleep, max_attempts=2)
check("429 навсегда: False", ok is False)
check("429 навсегда: было 2 запроса", state["n"] == 2)
check("429 навсегда: пауз было max_attempts-1", len(sleeps) - before == 1)

# 5. 400 — без пауз, сразу False
def handler_400(request: httpx.Request) -> httpx.Response:
    return httpx.Response(400, json={"ok": False, "description": "Bad Request"})

before = len(sleeps)
ok = send_message("TOK", 123, "hi", client=make_client(handler_400), sleep=fake_sleep)
check("400: False без пауз", ok is False and len(sleeps) == before)

# 6. 500: пауза и повтор, затем успех
state["n"] = 0
def handler_500(request: httpx.Request) -> httpx.Response:
    state["n"] += 1
    if state["n"] == 1:
        return httpx.Response(500, json={"ok": False})
    return httpx.Response(200, json={"ok": True})

ok = send_message("TOK", 123, "hi", client=make_client(handler_500), sleep=fake_sleep)
check("500: повтор и успех", ok is True and state["n"] == 2)

# 7. Число без retry_after в теле → значение по умолчанию
def handler_429_noparams(request: httpx.Request) -> httpx.Response:
    return httpx.Response(429, json={"ok": False})

send_message("TOK", 123, "hi", client=make_client(handler_429_noparams),
             sleep=fake_sleep, max_attempts=1)
check("429 без parameters: дефолтная пауза 1+буфер", sleeps[-1] == 2.0)

print()
print("ИТОГ:", "ПРОВАЛ: " + ", ".join(failures) if failures else "все проверки пройдены")
sys.exit(1 if failures else 0)
