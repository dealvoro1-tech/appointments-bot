"""Українські назви днів/місяців та форматування дат, часу й цін."""
from __future__ import annotations

from datetime import date, time

WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "нд")
WEEKDAYS_FULL = ("понеділок", "вівторок", "середа", "четвер", "п’ятниця", "субота", "неділя")
MONTHS_NOMINATIVE = (
    "січень", "лютий", "березень", "квітень", "травень", "червень",
    "липень", "серпень", "вересень", "жовтень", "листопад", "грудень",
)
MONTHS_GENITIVE = (
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
)


def weekday_short(d: date) -> str:
    return WEEKDAYS_SHORT[d.weekday()]


def format_date_long(d: date) -> str:
    """субота, 7 листопада 2026"""
    return f"{WEEKDAYS_FULL[d.weekday()]}, {d.day} {MONTHS_GENITIVE[d.month - 1]} {d.year}"


def format_date_short(d: date) -> str:
    """07.11.2026 (сб)"""
    return f"{d.day:02d}.{d.month:02d}.{d.year} ({weekday_short(d)})"


def format_time(t: time) -> str:
    return t.strftime("%H:%M")


def format_price(kop: int) -> str:
    """50000 -> '500 грн'; 50050 -> '500,50 грн'; 150000 -> '1 500 грн'."""
    hryvnias, rest = divmod(int(kop), 100)
    whole = f"{hryvnias:,}".replace(",", "\u00a0")
    if rest:
        return f"{whole},{rest:02d} грн"
    return f"{whole} грн"


def format_duration(seconds: int) -> str:
    minutes = max(0, int(seconds) // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if days:
        parts.append(f"{days} д")
    if hours:
        parts.append(f"{hours} год")
    if minutes and not days:
        parts.append(f"{minutes} хв")
    return " ".join(parts) or "менше хвилини"
