"""Перевірка введених користувачем даних. Повідомлення про помилки — українською."""
from __future__ import annotations

import re
from datetime import time
from decimal import Decimal, InvalidOperation


class ValidationError(ValueError):
    """Помилка введення; str(e) — готовий текст для користувача."""


MAX_PRICE_KOP = 100_000_000  # 1 000 000 грн
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_TIME_RE = re.compile(r"^\s*(\d{1,2})(?:\s*[:.\-]\s*|\s+)?(\d{2})?\s*$")


def parse_time(text: str) -> time:
    m = _TIME_RE.match(text or "")
    if not m:
        raise ValidationError("Невірний формат часу. Введіть, наприклад: 14:30 або 9:00.")
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    if hour > 23 or minute > 59:
        raise ValidationError("Такого часу не існує. Години — від 0 до 23, хвилини — від 0 до 59.")
    return time(hour, minute)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", _CONTROL.sub("", text or "")).strip()


def clean_procedure(text: str) -> str:
    value = _clean(text)
    if not value:
        raise ValidationError("Назва процедури не може бути порожньою.")
    if len(value) > 100:
        raise ValidationError("Назва процедури задовга: максимум 100 символів.")
    if not any(c.isalnum() for c in value):
        raise ValidationError("Назва процедури має містити літери або цифри.")
    return value


def clean_client_name(text: str) -> str:
    value = _clean(text)
    if not value:
        raise ValidationError("Ім’я клієнта не може бути порожнім.")
    if len(value) < 2:
        raise ValidationError("Ім’я клієнта має містити щонайменше 2 символи.")
    if len(value) > 100:
        raise ValidationError("Ім’я клієнта задовге: максимум 100 символів.")
    if not any(c.isalpha() for c in value):
        raise ValidationError("Ім’я клієнта має містити літери.")
    return value


def clean_notes(text: str) -> str:
    value = _CONTROL.sub("", text or "").strip()
    value = re.sub(r"\n{3,}", "\n\n", value)
    if not value:
        raise ValidationError("Нотатка порожня. Щоб прибрати нотатку, натисніть «Прибрати».")
    if len(value) > 500:
        raise ValidationError("Нотатка задовга: максимум 500 символів.")
    return value


def normalize_phone(text: str) -> str:
    raw = (text or "").strip()
    err = ValidationError("Невірний номер телефону. Приклад: +380501234567 або 0501234567.")
    if not re.fullmatch(r"\+?[\d\s\-().]+", raw):
        raise err
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        if 8 <= len(digits) <= 15:
            return "+" + digits
        raise err
    if len(digits) == 10 and digits.startswith("0"):
        return "+38" + digits
    if len(digits) == 12 and digits.startswith("380"):
        return "+" + digits
    raise err


def parse_price(text: str) -> int:
    """Повертає ціну в копійках. Приймає: 500, 500 грн, 500грн, 500,50, 1 500, ₴500."""
    raw = (text or "").strip().lower()
    raw = re.sub(r"(грн\.?|гривень|гривні|гривня|uah|₴)", "", raw)
    raw = re.sub(r"[\s\u00a0]", "", raw).replace(",", ".")
    if not raw:
        raise ValidationError("Вкажіть ціну числом, наприклад: 500 або 500 грн.")
    if raw.startswith("-"):
        raise ValidationError("Ціна не може бути від’ємною.")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", raw):
        raise ValidationError(
            "Невірний формат ціни. Введіть число в гривнях, наприклад: 500 або 750,50."
        )
    try:
        kop = int((Decimal(raw) * 100).to_integral_value())
    except InvalidOperation:
        raise ValidationError("Невірний формат ціни.") from None
    if kop > MAX_PRICE_KOP:
        raise ValidationError("Ціна завелика: максимум 1 000 000 грн.")
    return kop


def parse_reminder_hours(text: str) -> int:
    raw = re.sub(r"(годин[аиу]?|год\.?|h)", "", (text or "").strip().lower()).strip()
    if not raw.isdigit():
        raise ValidationError("Введіть ціле число годин від 1 до 168, наприклад: 24.")
    hours = int(raw)
    if not 1 <= hours <= 168:
        raise ValidationError("Кількість годин має бути від 1 до 168 (тиждень).")
    return hours
