"""Article — единый формат статьи для всего конвейера (roadmap, фаза 0.4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Article:
    """Единый формат материала, получаемого из источников.

    Каждая статья идентифицируется уникальным URL (это же поле будет
    PRIMARY KEY в SQLite, см. roadmap).
    """

    url: str
    title: str = ""
    text: str = ""
    source: str = ""
    published_at: Optional[datetime] = field(default=None)
