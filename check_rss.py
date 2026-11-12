"""Проверка collectors/rss.py (фаза 1.2)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collectors.rss import collect_rss

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name} {detail}")
    if not cond:
        failures.append(name)


# 1. Реальный фид Хабра
arts = collect_rss("https://habr.com/ru/rss/hubs/python/articles/?fl=ru", "habr-python")
check("реальный фид: статьи получены", len(arts) > 0, f"n={len(arts)}")
first = arts[0]
check("реальный фид: url/title заполнены", first.url.startswith("https://habr.com/") and bool(first.title))
check("реальный фид: source подставлен", first.source == "habr-python")
check("реальный фид: published_at распарсена", first.published_at is not None,
      str(first.published_at))

# 2. Несуществующий хост — не исключение, пустой список
bad = collect_rss("https://nonexistent-host-12345.invalid/feed.xml", "bad-host")
check("битый хост: пустой список, без исключения", bad == [])

# 3. HTTP 404
not_found = collect_rss("https://habr.com/ru/rss/bestsellers/daily/?fl=ru", "404")
check("HTTP 404: пустой список, без исключения", not_found == [])

# 4. Локальный фид с записью без ссылки (детерминированный разбор)
fixture = Path(__file__).resolve().parent / "tmp_check_rss_fixture.xml"
fixture.write_text(
    """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
  <title>T</title>
  <item><title>With link</title><link>https://example.com/1</link>
    <description>desc 1</description><pubDate>Tue, 10 Nov 2026 08:00:00 GMT</pubDate></item>
  <item><title>No link</title><description>desc 2</description></item>
</channel></rss>""", encoding="utf-8")
local = collect_rss(str(fixture), "fixture")
check("локальный фид: только записи со ссылкой", [a.url for a in local] == ["https://example.com/1"])
check("локальный фид: поля статьи",
      local[0].title == "With link" and local[0].text == "desc 1"
      and local[0].published_at is not None and local[0].published_at.day == 10
      and local[0].source == "fixture")
fixture.unlink()

print()
print("ИТОГ:", "ПРОВАЛ: " + ", ".join(failures) if failures else "все проверки пройдены")
sys.exit(1 if failures else 0)
