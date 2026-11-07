from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from typing import Optional


@dataclass(frozen=True)
class Appointment:
    id: int
    date: str            # YYYY-MM-DD, Europe/Kyiv
    time: str            # HH:MM, Europe/Kyiv
    starts_at: int       # UTC epoch
    procedure: str
    client_name: str
    price_kop: int
    phone: Optional[str]
    notes: Optional[str]
    status: str          # active | cancelled
    created_at: str      # UTC ISO
    updated_at: str
    cancelled_at: Optional[str]
    reminded_at: Optional[str]

    @property
    def date_obj(self) -> date:
        return date.fromisoformat(self.date)

    @property
    def time_obj(self) -> time:
        return time.fromisoformat(self.time)

    @property
    def is_active(self) -> bool:
        return self.status == "active"


@dataclass
class Session:
    """Стан діалогу користувача (зберігається в БД, щоб пережити перезапуск)."""
    state: str = "idle"
    data: dict = field(default_factory=dict)

    @property
    def draft(self) -> Optional[dict]:
        return self.data.get("draft")
