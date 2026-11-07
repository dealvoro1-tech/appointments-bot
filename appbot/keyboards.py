"""Інлайн-клавіатури. callback_data ≤ 64 байти (обмеження Telegram)."""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Optional

from . import texts as T
from .formatting import MONTHS_NOMINATIVE, WEEKDAYS_SHORT, weekday_short
from .models import Appointment

NOOP = "noop"
PAST = "pst"


def btn(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def markup(rows: list) -> dict:
    return {"inline_keyboard": [r for r in rows if r]}


def nav(back: Optional[str] = None, cancel: Optional[str] = None, menu: bool = True) -> list:
    rows = []
    top = []
    if back:
        top.append(btn(T.BTN_BACK, back))
    if cancel:
        top.append(btn(T.BTN_CANCEL, cancel))
    rows.append(top)
    if menu:
        rows.append([btn(T.BTN_MENU, "menu")])
    return rows


def short(text: str, limit: int = 28) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def parse_mode(mode: str) -> tuple:
    """'n' — новий запис, 'v' — перегляд, 'e<id>' — перенесення запису."""
    if mode.startswith("e"):
        return "e", int(mode[1:])
    return mode, None


# -- головне меню -------------------------------------------------------
def main_menu(has_draft: bool) -> dict:
    rows = []
    if has_draft:
        rows.append([btn("▶️ Продовжити незавершений запис", "s:resume")])
    rows += [
        [btn("➕ Новий запис", "new")],
        [btn("📅 Календар", "cal"), btn("🕑 Найближчі", "up")],
        [btn("💰 Дохід за місяцями", "income")],
        [btn("🔔 Нагадування", "set")],
    ]
    return markup(rows)


def income_year_picker(years: list[int], current_year: int) -> dict:
    selected = sorted(set(years) | {current_year}, reverse=True)
    rows = [[btn(str(year), f"iy:{year}")] for year in selected]
    rows += nav(menu=True)
    return markup(rows)


def income_month_picker(year: int, monthly: dict[int, tuple[int, int]]) -> dict:
    from .formatting import MONTHS_NOMINATIVE, format_price
    rows = []
    for month, name in enumerate(MONTHS_NOMINATIVE, 1):
        amount, count = monthly.get(month, (0, 0))
        label = f"{name.capitalize()}: {format_price(amount)}"
        if count:
            label += f" ({count})"
        rows.append([btn(label, f"im:{year}:{month}")])
    rows += nav(back="income", menu=True)
    return markup(rows)


def income_month_view(year: int, month: int) -> dict:
    previous_year, previous_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    rows = [[
        btn("⬅️ Попередній", f"im:{previous_year}:{previous_month}"),
        btn("Наступний ➡️", f"im:{next_year}:{next_month}"),
    ]]
    rows += nav(back=f"iy:{year}", menu=True)
    return markup(rows)


def only_nav(back: Optional[str] = None, cancel: Optional[str] = None) -> dict:
    return markup(nav(back, cancel))


# -- календар -------------------------------------------------------------
def _flow_nav(mode: str, back: Optional[str]) -> list:
    kind, appt_id = parse_mode(mode)
    cancel = None
    if kind == "n":
        cancel = "s:abort"
    elif kind == "e":
        cancel = f"a:{appt_id}"
    return nav(back, cancel)


def year_picker(mode: str, today: date, counts: dict) -> dict:
    kind, appt_id = parse_mode(mode)
    if kind == "v":
        years = sorted(set(range(today.year - 1, today.year + 3)) | set(counts))
    else:
        years = list(range(today.year, today.year + 3))
    rows = []
    tomorrow = today + timedelta(days=1)
    if kind == "n":
        rows.append([
            btn("Сьогодні", f"p:n:{today:%Y%m%d}"),
            btn("Завтра", f"p:n:{tomorrow:%Y%m%d}"),
        ])
    elif kind == "v":
        rows.append([btn("Сьогодні", f"p:v:{today:%Y%m%d}")])
    year_buttons = [
        btn(f"{y} ({counts[y]})" if counts.get(y) else str(y), f"m:{mode}:{y}") for y in years
    ]
    for i in range(0, len(year_buttons), 2):
        rows.append(year_buttons[i:i + 2])
    back = f"e:{appt_id}" if kind == "e" else None
    return markup(rows + _flow_nav(mode, back))


def month_picker(mode: str, year: int, today: date, counts: dict) -> dict:
    kind, _ = parse_mode(mode)
    buttons = []
    for m in range(1, 13):
        name = MONTHS_NOMINATIVE[m - 1]
        label = f"{name} ({counts[m]})" if counts.get(m) else name
        past = kind != "v" and (year, m) < (today.year, today.month)
        buttons.append(btn(label, PAST if past else f"d:{mode}:{year}:{m}:g"))
    rows = [buttons[i:i + 2] for i in range(0, 12, 2)]
    return markup(rows + _flow_nav(mode, f"y:{mode}"))


def _shift(year: int, month: int, delta: int) -> tuple:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def day_grid(mode: str, year: int, month: int, today: date, counts: dict, view: str = "g") -> dict:
    kind, _ = parse_mode(mode)
    prev_y, prev_m = _shift(year, month, -1)
    next_y, next_m = _shift(year, month, 1)
    can_prev = kind == "v" or (prev_y, prev_m) >= (today.year, today.month)
    rows = [[
        btn("◀️", f"d:{mode}:{prev_y}:{prev_m}:{view}") if can_prev else btn(" ", NOOP),
        btn(f"{MONTHS_NOMINATIVE[month - 1]} {year}", f"m:{mode}:{year}"),
        btn("▶️", f"d:{mode}:{next_y}:{next_m}:{view}"),
    ]]

    def label(d: date, with_weekday: bool) -> str:
        text = f"{d.day} {weekday_short(d)}" if with_weekday else str(d.day)
        if d == today:
            text = f"[{text}]"
        if counts.get(d.day):
            text += "•"
        return text

    def day_btn(d: date, with_weekday: bool) -> dict:
        past = kind != "v" and d < today
        return btn(label(d, with_weekday), PAST if past else f"p:{mode}:{d:%Y%m%d}")

    if view == "g":
        rows.append([btn(w, NOOP) for w in WEEKDAYS_SHORT])
        for week in calendar.Calendar(0).monthdayscalendar(year, month):
            rows.append([
                day_btn(date(year, month, n), False) if n else btn(" ", NOOP) for n in week
            ])
        rows.append([btn("📋 Списком із днями тижня", f"d:{mode}:{year}:{month}:l")])
    else:
        days = [date(year, month, n) for n in range(1, calendar.monthrange(year, month)[1] + 1)]
        buttons = [day_btn(d, True) for d in days]
        for i in range(0, len(buttons), 4):
            rows.append(buttons[i:i + 4])
        rows.append([btn("🗓 Сіткою", f"d:{mode}:{year}:{month}:g")])
    return markup(rows + _flow_nav(mode, f"m:{mode}:{year}"))


# -- перегляд дня / запису ---------------------------------------------
def day_view(d: date, appts: list, can_add: bool) -> dict:
    rows = []
    for a in appts:
        rows.append([btn(short(f"{a.time} · {a.client_name} · {a.procedure}", 40), f"a:{a.id}")])
    if can_add:
        rows.append([btn("➕ Додати запис на цей день", f"p:n:{d:%Y%m%d}")])
    return markup(rows + nav(f"d:v:{d.year}:{d.month}:g"))


def upcoming_view(appts: list) -> dict:
    rows = [[btn(short(f"{a.date[8:10]}.{a.date[5:7]} {a.time} · {a.client_name}", 40), f"a:{a.id}")] for a in appts]
    return markup(rows + nav())


def appointment_actions(a: Appointment) -> dict:
    day_back = f"p:v:{a.date.replace('-', '')}"
    if not a.is_active:
        return markup(nav(day_back))
    rows = [
        [btn("✏️ Редагувати", f"e:{a.id}"), btn("❌ Скасувати запис", f"x:{a.id}")],
    ]
    return markup(rows + nav(day_back))


def edit_menu(a: Appointment) -> dict:
    f = lambda name, key: btn(name, f"ef:{a.id}:{key}")
    rows = [
        [f("📅 Дата", "date"), f("🕒 Час", "time")],
        [f("💼 Процедура", "procedure"), f("👤 Клієнт", "client")],
        [f("💰 Ціна", "price"), f("📞 Телефон", "phone")],
        [f("🗒 Нотатки", "notes")],
    ]
    return markup(rows + nav(f"a:{a.id}"))


def cancel_confirm(a: Appointment) -> dict:
    return markup([
        [btn("✅ Так, скасувати запис", f"xy:{a.id}")],
        [btn("⬅️ Ні, залишити", f"a:{a.id}")],
        [btn(T.BTN_MENU, "menu")],
    ])


def saved_view(a: Appointment) -> dict:
    return markup([
        [btn("📌 Відкрити запис", f"a:{a.id}")],
        [btn("➕ Ще один запис", "new")],
        [btn(T.BTN_MENU, "menu")],
    ])


# -- налаштування нагадувань -------------------------------------------
def settings_menu(enabled: bool, hours: int) -> dict:
    toggle = btn("🔕 Вимкнути", "rt") if enabled else btn("🔔 Увімкнути", "rt")
    presets = [1, 2, 12, 24, 48]
    row = [btn(("✅ " if h == hours else "") + f"{h} год", f"rh:{h}") for h in presets]
    return markup([
        [toggle],
        row[:3],
        row[3:],
        [btn("✏️ Інше значення", "rh:c")],
        [btn(T.BTN_MENU, "menu")],
    ])


def reminder_view(a: Appointment) -> dict:
    return markup([[btn("📌 Відкрити запис", f"a:{a.id}")]])


# -- кроки введення ----------------------------------------------------
def suggestion_rows(labels: list, per_row: int) -> list:
    buttons = [btn(label, f"sg:{i}") for i, label in enumerate(labels)]
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def step_keyboard(
    labels: Optional[list] = None,
    per_row: int = 2,
    keep_label: Optional[str] = None,
    clear: bool = False,
    back: str = "s:back",
    cancel: str = "s:abort",
) -> dict:
    rows = suggestion_rows(labels or [], per_row)
    if keep_label:
        rows.append([btn(keep_label, "s:keep")])
    if clear:
        rows.append([btn("🗑 Прибрати", "s:clr")])
    return markup(rows + nav(back, cancel))


def confirm_keyboard() -> dict:
    return markup([
        [btn("✅ Зберегти", "s:save")],
        [btn("🕒 Час", "df:time"), btn("💼 Процедура", "df:procedure")],
        [btn("👤 Клієнт", "df:client"), btn("💰 Ціна", "df:price")],
        [btn("📞 Телефон", "df:phone"), btn("🗒 Нотатки", "df:notes")],
        *nav("s:back", "s:abort"),
    ])


def duplicate_keyboard(back_label: str = "🕒 Змінити час", cancel: str = "s:abort") -> dict:
    return markup([
        [btn("✅ Так, створити", "s:dup")],
        [btn(back_label, "s:back")],
        *nav(None, cancel),
    ])


def draft_exists_keyboard() -> dict:
    return markup([
        [btn("▶️ Продовжити незавершений", "s:resume")],
        [btn("🗑 Почати новий", "new!")],
        [btn(T.BTN_MENU, "menu")],
    ])
