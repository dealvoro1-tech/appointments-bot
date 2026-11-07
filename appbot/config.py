"""Конфігурація з змінних оточення (та необов'язкового файлу .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    token: str
    allowed_user_ids: frozenset
    db_path: str = "data/appointments.db"
    default_reminder_hours: int = 24
    reminder_check_seconds: int = 30
    log_level: str = "INFO"


def read_dotenv(path: str = ".env") -> dict:
    result: dict = {}
    p = Path(path)
    if not p.is_file():
        return result
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        result[key.strip()] = value
    return result


def _int(env: Mapping, key: str, default: int, lo: int, hi: int) -> int:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{key} має бути цілим числом") from None
    if not lo <= value <= hi:
        raise ConfigError(f"{key} має бути в межах {lo}-{hi}")
    return value


def load_config(env: Mapping | None = None, dotenv_path: str = ".env") -> Config:
    if env is None:
        merged = dict(read_dotenv(dotenv_path))
        merged.update(os.environ)  # справжні змінні оточення мають пріоритет
        env = merged

    token = (env.get("BOT_TOKEN") or "").strip()
    if not token:
        raise ConfigError("Не задано BOT_TOKEN (див. .env.example)")

    raw_ids = (env.get("ALLOWED_USER_IDS") or "").replace(";", ",")
    ids = set()
    for part in raw_ids.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ConfigError("ALLOWED_USER_IDS має містити лише числові Telegram ID")
        ids.add(int(part))
    if not ids:
        raise ConfigError("Не задано ALLOWED_USER_IDS: бот без списку доступу не запускається")

    return Config(
        token=token,
        allowed_user_ids=frozenset(ids),
        db_path=(env.get("DATABASE_PATH") or "data/appointments.db").strip(),
        default_reminder_hours=_int(env, "DEFAULT_REMINDER_HOURS", 24, 1, 168),
        reminder_check_seconds=_int(env, "REMINDER_CHECK_SECONDS", 30, 5, 3600),
        log_level=(env.get("LOG_LEVEL") or "INFO").strip().upper(),
    )
