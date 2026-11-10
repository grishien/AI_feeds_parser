"""Настройка логирования (roadmap, фаза 0.3): файл с ротацией + stdout.

Логи пишутся в каталог из переменной окружения ``LOG_DIR``
(по умолчанию ``./logs``).
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> Path:
    """Настроить root-логгер: RotatingFileHandler + StreamHandler(stdout)."""
    log_dir = Path(os.environ.get("LOG_DIR", "./logs")).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "digest.log"

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    return log_file
