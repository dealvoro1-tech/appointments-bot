"""Правила планування: минулі дати, дублі, нагадування."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Callable, Optional

from .db import Repository
from .models import Appointment
from .timeutil import NonexistentLocalTime, now_local, to_epoch
from .validators import ValidationError


class Scheduler:
    def __init__(
        self,
        repo: Repository,
        default_reminder_hours: int = 24,
        now_fn: Callable[[], datetime] = now_local,
    ):
        self.repo = repo
        self.default_hours = default_reminder_hours
        self.now = now_fn

    # -- перевірки -----------------------------------------------------
    def check_date_allowed(self, d: date) -> None:
        if d < self.now().date():
            raise ValidationError("Цю дату вже минуло. Оберіть сьогоднішню або майбутню дату.")

    def check_slot(self, d: date, t: time) -> int:
        """Перевіряє, що дата+час існують і ще не минули. Повертає UTC epoch."""
        self.check_date_allowed(d)
        try:
            starts_at = to_epoch(d, t)
        except NonexistentLocalTime:
            raise ValidationError(
                "Цього часу не існує через перехід на літній час. Оберіть інший час."
            ) from None
        if starts_at <= int(self.now().timestamp()):
            raise ValidationError("Цей час уже минув. Введіть майбутній час.")
        return starts_at

    def conflicts(self, d: date, t: time, exclude_id: Optional[int] = None) -> list:
        """Активні записи на ту саму дату й годину."""
        return self.repo.find_conflicts(d.isoformat(), t.strftime("%H:%M"), exclude_id)

    # -- операції ------------------------------------------------------
    def create(self, draft: dict, user_id: Optional[int] = None) -> Appointment:
        appt = self.repo.create_appointment(
            date=draft["date"],
            time=draft["time"],
            procedure=draft["procedure"],
            client_name=draft["client"],
            price_kop=draft["price_kop"],
            phone=draft.get("phone"),
            notes=draft.get("notes"),
            reset_session_for=user_id,
        )
        self._skip_reminder_if_inside_window(appt)
        return appt

    def update(self, appt_id: int, **fields) -> Optional[Appointment]:
        appt = self.repo.update_appointment(appt_id, **fields)
        if appt is not None and ("date" in fields or "time" in fields):
            self._skip_reminder_if_inside_window(appt)
        return appt

    def cancel(self, appt_id: int) -> Optional[Appointment]:
        return self.repo.cancel_appointment(appt_id)

    # -- нагадування ---------------------------------------------------
    def reminder_settings(self) -> tuple:
        enabled = self.repo.get_setting("reminders_enabled", "1") == "1"
        try:
            hours = int(self.repo.get_setting("reminder_hours", str(self.default_hours)))
        except (TypeError, ValueError):
            hours = self.default_hours
        return enabled, hours

    def set_reminders_enabled(self, enabled: bool) -> None:
        self.repo.set_setting("reminders_enabled", "1" if enabled else "0")

    def set_reminder_hours(self, hours: int) -> None:
        if not 1 <= hours <= 168:
            raise ValidationError("Кількість годин має бути від 1 до 168 (тиждень).")
        self.repo.set_setting("reminder_hours", str(hours))

    def _skip_reminder_if_inside_window(self, appt: Appointment) -> None:
        """Запис створено вже всередині вікна нагадування — не нагадуємо про щойно створене."""
        enabled, hours = self.reminder_settings()
        now_ts = int(self.now().timestamp())
        if enabled and appt.starts_at - hours * 3600 <= now_ts:
            self.repo.mark_reminded(appt.id)
