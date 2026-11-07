"""Робота з часом: усі дати й години записів — за київським часом."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

TZ_NAME = "Europe/Kyiv"
TZ = ZoneInfo(TZ_NAME)


class NonexistentLocalTime(ValueError):
    """Локального часу не існує (перехід на літній час)."""


def now_local() -> datetime:
    return datetime.now(TZ)


def to_epoch(d: date, t: time) -> int:
    """Київська дата+година -> UTC epoch. Відхиляє неіснуючий час."""
    naive = datetime.combine(d, t)
    aware = naive.replace(tzinfo=TZ)
    roundtrip = aware.astimezone(timezone.utc).astimezone(TZ).replace(tzinfo=None)
    if roundtrip != naive:
        raise NonexistentLocalTime(naive.isoformat())
    return int(aware.timestamp())


def from_epoch(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, TZ)


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_to_local(value: str) -> datetime:
    dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ)
