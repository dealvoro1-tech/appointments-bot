"""Запуск бота: конфігурація, БД, опитування Telegram, потік нагадувань."""
from __future__ import annotations

import logging
import signal
import sys
import threading

from .bot import Bot
from .config import ConfigError, load_config
from .db import Repository
from .reminders import ReminderWorker
from .scheduling import Scheduler
from .telegram_api import TelegramAPI, TelegramError, TelegramNetworkError, backoff_sleep

log = logging.getLogger("appbot")

COMMANDS = [
    {"command": "menu", "description": "Головне меню"},
    {"command": "new", "description": "Новий запис"},
    {"command": "cancel", "description": "Скасувати поточну дію"},
    {"command": "help", "description": "Довідка"},
]


def poll(api, bot: Bot, repo: Repository, stop: threading.Event) -> None:
    offset = int(repo.get_setting("update_offset", "0") or 0)
    failures = 0
    while not stop.is_set():
        try:
            updates = api.get_updates(offset)
            failures = 0
        except TelegramNetworkError as exc:
            failures += 1
            log.warning("Мережева помилка: %s. Повтор…", exc)
            backoff_sleep(failures)
            continue
        except TelegramError as exc:
            failures += 1
            log.error("Помилка Telegram: %s", exc.description)
            if exc.code == 401:
                log.critical("Невірний BOT_TOKEN. Зупинка.")
                stop.set()
                return
            stop.wait(max(exc.retry_after, 3))
            continue
        for update in updates:
            bot.handle_update(update)
            offset = update["update_id"] + 1
            repo.set_setting("update_offset", str(offset))


def main() -> None:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Помилка конфігурації: {exc}", file=sys.stderr)
        raise SystemExit(2)

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    repo = Repository(config.db_path)
    repo.init_schema()
    api = TelegramAPI(config.token)
    scheduler = Scheduler(repo, config.default_reminder_hours)
    bot = Bot(api, repo, scheduler, config.allowed_user_ids)
    worker = ReminderWorker(api, repo, scheduler, config.allowed_user_ids)

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    try:
        api.set_commands(COMMANDS)
    except (TelegramError, TelegramNetworkError) as exc:
        log.warning("Не вдалося встановити команди: %s", type(exc).__name__)

    thread = threading.Thread(
        target=worker.run_forever, args=(stop, config.reminder_check_seconds), daemon=True, name="reminders"
    )
    thread.start()
    log.info("Бот запущено. Дозволених користувачів: %d", len(config.allowed_user_ids))
    try:
        poll(api, bot, repo, stop)
    finally:
        stop.set()
        thread.join(timeout=5)
        log.info("Бот зупинено.")
