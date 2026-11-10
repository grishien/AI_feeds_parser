"""Конфигурация проекта (roadmap, фазы 0.2 и 0.5).

Пути задаются переменными окружения:
- ``CONFIG_DIR`` — каталог конфигов (по умолчанию ``./config``).
  ``sources.yaml``, ``profile.md`` и ``.env`` читаются ТОЛЬКО из него.
- ``DB_PATH``    — путь к базе SQLite (по умолчанию ``./data/digest.db``).

В коде нет упоминаний конкретных источников и проектов: их перечень
хранится только в ``sources.yaml``.

Секреты попадают в окружение из ``.env`` (каталог CONFIG_DIR) и в git
не коммитятся.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from dotenv import load_dotenv

SOURCES_FILE = "sources.yaml"
PROFILE_FILE = "profile.md"
ENV_FILE = ".env"

ENV_VARS = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "SCORE_THRESHOLD",
)


def _default_config_dir() -> Path:
    return Path(os.environ.get("CONFIG_DIR", "./config")).resolve()


def _default_db_path() -> Path:
    return Path(os.environ.get("DB_PATH", "./data/digest.db")).resolve()


@dataclass
class Settings:
    """Снимок настроек, прочитанных из .env и переменных окружения."""

    config_dir: Path
    db_path: Path
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    score_threshold: int = 7
    env_found: bool = False


def load_settings(config_dir: Optional[Path] = None) -> Settings:
    """Прочитать .env из CONFIG_DIR и переменные окружения.

    Значения из .env затирают значения по умолчанию, но не приоритетнее
    уже установленных переменных окружения (load_dotenv(override=False)).
    """
    cfg_dir = Path(config_dir) if config_dir is not None else _default_config_dir()
    env_path = cfg_dir / ENV_FILE
    env_found = False
    if env_path.is_file():
        load_dotenv(env_path, override=False)
        env_found = True

    raw_threshold = os.environ.get("SCORE_THRESHOLD", "").strip()
    threshold = 7
    if raw_threshold:
        try:
            threshold = int(raw_threshold)
        except ValueError:
            threshold = 7

    return Settings(
        config_dir=cfg_dir,
        db_path=_default_db_path(),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID") or None,
        llm_base_url=os.environ.get("LLM_BASE_URL") or None,
        llm_api_key=os.environ.get("LLM_API_KEY") or None,
        llm_model=os.environ.get("LLM_MODEL") or None,
        score_threshold=threshold,
        env_found=env_found,
    )


@dataclass
class SourcesConfig:
    """Содержимое sources.yaml из CONFIG_DIR."""

    raw: dict[str, Any] = field(default_factory=dict)
    sources: List[dict[str, Any]] = field(default_factory=list)
    path: Optional[Path] = None


def load_sources(config_dir: Optional[Path] = None) -> SourcesConfig:
    """Прочитать sources.yaml только из CONFIG_DIR.

    Конкретные источники не зашиты в код: YAML — единственный их источник.
    """
    import yaml

    cfg_dir = Path(config_dir) if config_dir is not None else _default_config_dir()
    path = cfg_dir / SOURCES_FILE
    if not path.is_file():
        raise FileNotFoundError(f"Файл источников не найден: {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"{path}: ожидается YAML-словарь со списком 'sources'")
    sources = raw.get("sources") or []
    if not isinstance(sources, list):
        raise ValueError(f"{path}: 'sources' должен быть списком")

    return SourcesConfig(raw=raw, sources=sources, path=path)


def profile_path(config_dir: Optional[Path] = None) -> Path:
    """Путь к profile.md — читается только из CONFIG_DIR."""
    cfg_dir = Path(config_dir) if config_dir is not None else _default_config_dir()
    return cfg_dir / PROFILE_FILE
