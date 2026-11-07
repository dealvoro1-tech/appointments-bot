"""Побудова тексту повідомлень (HTML) із записів. Весь користувацький текст екранується."""
from __future__ import annotations

from datetime import date, datetime
from html import escape
from typing import Optional

from . import texts as T
from .formatting import (
    format_date_long,
    format_duration,
    format_price,
    format_time,
)
from .models import Appointment
from .timeutil import iso_to_local, from_epoch


def e(value: Optional[str]) -> str:
    return escape(value or "", quote=False)


def appointment_card(a: Appointment, title: Optional[str] = None) -> str:
    lines = []
    if title:
        lines += [title, ""]
    lines += [
        f"📅 <b>Дата:</b> {format_date_long(a.date_obj)}",
        f"🕒 <b>Час:</b> {a.time}",
        f"💼 <b>Процедура:</b> {e(a.procedure)}",
        f"👤 <b>Клієнт:</b> {e(a.client_name)}",
        f"💰 <b>Ціна:</b> {format_price(a.price_kop)}",
        f"📞 <b>Телефон:</b> {e(a.phone) if a.phone else '—'}",
        f"🗒 <b>Нотатки:</b> {e(a.notes) if a.notes else '—'}",
    ]
    created = iso_to_local(a.created_at)
    lines.append(f"🧾 <i>Створено: {created:%d.%m.%Y %H:%M}</i>")
    if not a.is_active:
        lines.append("❌ <b>Статус:</b> скасовано")
    return "\n".join(lines)


def draft_card(draft: dict) -> str:
    d = date.fromisoformat(draft["date"])
    lines = [
        f"📅 <b>Дата:</b> {format_date_long(d)}",
        f"🕒 <b>Час:</b> {draft['time']}",
        f"💼 <b>Процедура:</b> {e(draft['procedure'])}",
        f"👤 <b>Клієнт:</b> {e(draft['client'])}",
        f"💰 <b>Ціна:</b> {format_price(draft['price_kop'])}",
    ]
    if draft.get("phone"):
        lines.append(f"📞 <b>Телефон:</b> {e(draft['phone'])}")
    if draft.get("notes"):
        lines.append(f"🗒 <b>Нотатки:</b> {e(draft['notes'])}")
    return "\n".join(lines)


def day_text(d: date, appts: list) -> str:
    head = f"📅 <b>{format_date_long(d)}</b>"
    if not appts:
        return f"{head}\n\n{T.NO_APPOINTMENTS_DAY}"
    total = sum(a.price_kop for a in appts)
    lines = [head, ""]
    for a in appts:  # список уже відсортований за часом
        lines.append(f"🕒 <b>{a.time}</b> — {e(a.procedure)}, {e(a.client_name)}, {format_price(a.price_kop)}")
    lines += ["", f"Записів: {len(appts)} · Разом: {format_price(total)}"]
    return "\n".join(lines)


def upcoming_text(appts: list) -> str:
    if not appts:
        return f"🕑 <b>Найближчі записи</b>\n\n{T.NO_UPCOMING}"
    lines = ["🕑 <b>Найближчі записи</b>", ""]
    for a in appts:
        from .formatting import format_date_short
        lines.append(
            f"{format_date_short(a.date_obj)} <b>{a.time}</b> — {e(a.procedure)}, {e(a.client_name)}"
        )
    return "\n".join(lines)


def conflict_text(conflicts: list) -> str:
    lines = ["⚠️ <b>На цей час уже є запис:</b>"]
    for a in conflicts[:3]:
        lines.append(f"• {a.time} — {e(a.client_name)}, {e(a.procedure)}")
    lines += ["", "Все одно створити запис на цей самий час?"]
    return "\n".join(lines)


def settings_text(enabled: bool, hours: int) -> str:
    if enabled:
        status = f"🔔 Нагадування <b>увімкнено</b>: за {hours} год до запису."
    else:
        status = "🔕 Нагадування <b>вимкнено</b>."
    return f"⚙️ <b>Нагадування</b>\n\n{status}\nОберіть час нагадування або змініть стан:"


def reminder_text(a: Appointment, now_ts: int) -> str:
    left = format_duration(a.starts_at - now_ts)
    return (
        "🔔 <b>Нагадування про запис</b>\n"
        f"До початку: {left}\n\n"
        f"📅 {format_date_long(a.date_obj)}, {a.time}\n"
        f"💼 {e(a.procedure)}\n"
        f"👤 {e(a.client_name)}\n"
        f"💰 {format_price(a.price_kop)}"
        + (f"\n📞 {e(a.phone)}" if a.phone else "")
    )
