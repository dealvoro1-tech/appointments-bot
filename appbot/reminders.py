"""Фонові нагадування про записи."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Callable, Iterable

from . import keyboards as K
from . import views as V
from .db import Repository
from .scheduling import Scheduler
from .telegram_api import TelegramError, TelegramNetworkError
from .timeutil import now_local

log = logging.getLogger(__name__)


class ReminderWorker:
    def __init__(
        self,
        api,
        repo: Repository,
        scheduler: Scheduler,
        chat_ids: Iterable[int],
        now_fn: Callable[[], datetime] = now_local,
    ):
        self.api = api
        self.repo = repo
        self.sched = scheduler
        self.chat_ids = list(chat_ids)  # у приватних чатах chat_id == user_id
        self.now = now_fn
        self._warned: set = set()

    def run_once(self) -> int:
        """Надсилає всі нагадування, що настали. Повертає кількість позначених як надіслані."""
        enabled, hours = self.sched.reminder_settings()
        if not enabled:
            return 0
        now_ts = int(self.now().timestamp())
        done = 0
        for appt in self.repo.due_reminders(now_ts, hours):
            text = V.reminder_text(appt, now_ts)
            delivered = False
            for chat_id in self.chat_ids:
                try:
                    self.api.send_message(chat_id, text, K.reminder_view(appt))
                    delivered = True
                except (TelegramError, TelegramNetworkError) as exc:
                    if (appt.id, chat_id) not in self._warned:
                        self._warned.add((appt.id, chat_id))
                        log.warning("Не вдалося надіслати нагадування (запис #%s): %s", appt.id, type(exc).__name__)
            if delivered:
                self.repo.mark_reminded(appt.id)
                done += 1
        return done

    def run_forever(self, stop: threading.Event, interval: int = 30) -> None:
        while not stop.is_set():
            try:
                self.run_once()
            except Exception as exc:  # потік не повинен падати
                log.error("Помилка перевірки нагадувань: %s", type(exc).__name__)
            stop.wait(interval)
