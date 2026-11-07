"""Сховище SQLite: записи, налаштування, стан діалогу.

Кожна операція відкриває власне з'єднання (безпечно для потоку нагадувань).
Файл БД має бути на диску (":memory:" не підтримується).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional

from .models import Appointment, Session
from .timeutil import to_epoch, utc_iso

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS appointments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT    NOT NULL,
    time         TEXT    NOT NULL,
    starts_at    INTEGER NOT NULL,
    procedure    TEXT    NOT NULL,
    client_name  TEXT    NOT NULL,
    price_kop    INTEGER NOT NULL CHECK (price_kop >= 0),
    phone        TEXT,
    notes        TEXT,
    status       TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    cancelled_at TEXT,
    reminded_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_appointments_date   ON appointments (date, time);
CREATE INDEX IF NOT EXISTS idx_appointments_starts ON appointments (starts_at);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    user_id    INTEGER PRIMARY KEY,
    state      TEXT NOT NULL,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
PRAGMA user_version = 1;
"""

_EDITABLE = {"date", "time", "procedure", "client_name", "price_kop", "phone", "notes"}


class Repository:
    def __init__(self, path: str, clock: Optional[Callable[[], datetime]] = None):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("Використовуйте файл БД на диску")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)

    # -- інфраструктура ------------------------------------------------
    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # commit / rollback
                yield conn
        finally:
            conn.close()

    def _now(self) -> str:
        return utc_iso(self._clock())

    def init_schema(self) -> None:
        """Створює таблиці (ідемпотентно). Наявні дані не чіпає."""
        with self._conn() as c:
            version = c.execute("PRAGMA user_version").fetchone()[0]
            if version < 1:
                c.executescript(SCHEMA_V1)

    @staticmethod
    def _appt(row: Optional[sqlite3.Row]) -> Optional[Appointment]:
        if row is None:
            return None
        return Appointment(**{k: row[k] for k in row.keys()})

    # -- записи --------------------------------------------------------
    def create_appointment(
        self,
        *,
        date: str,
        time: str,
        procedure: str,
        client_name: str,
        price_kop: int,
        phone: Optional[str] = None,
        notes: Optional[str] = None,
        reset_session_for: Optional[int] = None,
    ) -> Appointment:
        starts_at = to_epoch(_date.fromisoformat(date), _time.fromisoformat(time))
        now = self._now()
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO appointments (date, time, starts_at, procedure, client_name,"
                " price_kop, phone, notes, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                (date, time, starts_at, procedure, client_name, price_kop, phone, notes, now, now),
            )
            if reset_session_for is not None:  # одна транзакція: запис + очищення чернетки
                c.execute("DELETE FROM sessions WHERE user_id = ?", (reset_session_for,))
            row = c.execute("SELECT * FROM appointments WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._appt(row)

    def get_appointment(self, appt_id: int) -> Optional[Appointment]:
        with self._conn() as c:
            return self._appt(c.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone())

    def update_appointment(self, appt_id: int, **fields) -> Optional[Appointment]:
        """Оновлює активний запис. Зміна дати/часу скидає статус нагадування."""
        unknown = set(fields) - _EDITABLE
        if unknown:
            raise ValueError(f"Поля не можна редагувати: {sorted(unknown)}")
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM appointments WHERE id = ? AND status = 'active'", (appt_id,)
            ).fetchone()
            if row is None:
                return None
            sets = dict(fields)
            if "date" in sets or "time" in sets:
                new_date = sets.get("date", row["date"])
                new_time = sets.get("time", row["time"])
                sets["starts_at"] = to_epoch(_date.fromisoformat(new_date), _time.fromisoformat(new_time))
                sets["reminded_at"] = None
            sets["updated_at"] = self._now()
            assignments = ", ".join(f"{k} = ?" for k in sets)  # ключі — з білого списку
            c.execute(f"UPDATE appointments SET {assignments} WHERE id = ?", (*sets.values(), appt_id))
            return self._appt(c.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone())

    def cancel_appointment(self, appt_id: int) -> Optional[Appointment]:
        now = self._now()
        with self._conn() as c:
            cur = c.execute(
                "UPDATE appointments SET status = 'cancelled', cancelled_at = ?, updated_at = ?"
                " WHERE id = ? AND status = 'active'",
                (now, now, appt_id),
            )
            if cur.rowcount == 0:
                return None
            return self._appt(c.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone())

    def list_for_date(self, date_iso: str) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM appointments WHERE date = ? AND status = 'active' ORDER BY time, id",
                (date_iso,),
            ).fetchall()
        return [self._appt(r) for r in rows]

    def find_conflicts(self, date_iso: str, time_str: str, exclude_id: Optional[int] = None) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM appointments WHERE date = ? AND time = ? AND status = 'active'"
                " AND id != ? ORDER BY id",
                (date_iso, time_str, exclude_id if exclude_id is not None else -1),
            ).fetchall()
        return [self._appt(r) for r in rows]

    def day_counts(self, year: int, month: int) -> dict:
        lo, hi = f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-31"
        with self._conn() as c:
            rows = c.execute(
                "SELECT date, COUNT(*) n FROM appointments WHERE status = 'active'"
                " AND date BETWEEN ? AND ? GROUP BY date",
                (lo, hi),
            ).fetchall()
        return {int(r["date"][8:10]): r["n"] for r in rows}

    def month_counts(self, year: int) -> dict:
        with self._conn() as c:
            rows = c.execute(
                "SELECT substr(date, 6, 2) m, COUNT(*) n FROM appointments"
                " WHERE status = 'active' AND substr(date, 1, 4) = ? GROUP BY m",
                (f"{year:04d}",),
            ).fetchall()
        return {int(r["m"]): r["n"] for r in rows}

    def year_counts(self) -> dict:
        with self._conn() as c:
            rows = c.execute(
                "SELECT substr(date, 1, 4) y, COUNT(*) n FROM appointments"
                " WHERE status = 'active' GROUP BY y"
            ).fetchall()
        return {int(r["y"]): r["n"] for r in rows}

    def revenue_by_month(self, year: int) -> dict:
        """Повертає суми та кількість активних записів по місяцях року."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT CAST(substr(date, 6, 2) AS INTEGER) m,"
                " COALESCE(SUM(price_kop), 0) amount, COUNT(*) n"
                " FROM appointments WHERE status = 'active' AND substr(date, 1, 4) = ?"
                " GROUP BY m ORDER BY m",
                (f"{year:04d}",),
            ).fetchall()
        return {int(r["m"]): (int(r["amount"]), int(r["n"])) for r in rows}

    def revenue_for_month(self, year: int, month: int) -> tuple[int, int]:
        """Повертає суму у копійках і кількість активних записів за місяць."""
        with self._conn() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(price_kop), 0) amount, COUNT(*) n FROM appointments"
                " WHERE status = 'active' AND date >= ? AND date < ?",
                (f"{year:04d}-{month:02d}-01", f"{year + (month == 12):04d}-{month % 12 + 1:02d}-01"),
            ).fetchone()
        return int(row["amount"]), int(row["n"])

    def upcoming(self, now_ts: int, limit: int = 10) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM appointments WHERE status = 'active' AND starts_at >= ?"
                " ORDER BY starts_at, id LIMIT ?",
                (now_ts, limit),
            ).fetchall()
        return [self._appt(r) for r in rows]

    def due_reminders(self, now_ts: int, hours: int) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM appointments WHERE status = 'active' AND reminded_at IS NULL"
                " AND starts_at > ? AND starts_at - ? <= ? ORDER BY starts_at, id",
                (now_ts, hours * 3600, now_ts),
            ).fetchall()
        return [self._appt(r) for r in rows]

    def mark_reminded(self, appt_id: int) -> None:
        with self._conn() as c:
            c.execute("UPDATE appointments SET reminded_at = ? WHERE id = ?", (self._now(), appt_id))

    # -- підказки для швидкого введення --------------------------------
    def frequent_values(self, column: str, limit: int = 6) -> list:
        if column not in ("procedure", "client_name"):
            raise ValueError(column)
        with self._conn() as c:
            rows = c.execute(
                f"SELECT {column} v FROM appointments GROUP BY {column}"
                " ORDER BY COUNT(*) DESC, MAX(id) DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [r["v"] for r in rows]

    def last_price_for(self, procedure: str) -> Optional[int]:
        with self._conn() as c:
            row = c.execute(
                "SELECT price_kop FROM appointments WHERE procedure = ? ORDER BY id DESC LIMIT 1",
                (procedure,),
            ).fetchone()
        return row["price_kop"] if row else None

    # -- налаштування --------------------------------------------------
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._conn() as c:
            row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # -- стан діалогу --------------------------------------------------
    def get_session(self, user_id: int) -> Session:
        with self._conn() as c:
            row = c.execute("SELECT state, data FROM sessions WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return Session()
        try:
            data = json.loads(row["data"])
        except ValueError:
            data = {}
        return Session(state=row["state"], data=data if isinstance(data, dict) else {})

    def save_session(self, user_id: int, session: Session) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO sessions (user_id, state, data, updated_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(user_id) DO UPDATE SET state = excluded.state,"
                " data = excluded.data, updated_at = excluded.updated_at",
                (user_id, session.state, json.dumps(session.data, ensure_ascii=False), self._now()),
            )

    def clear_session(self, user_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


_date = date
_time = time
