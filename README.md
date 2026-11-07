# Бот для запису клієнтів

Приватний Telegram-бот із меню українською мовою та київським часовим поясом. Записи зберігаються у SQLite.

## Функції

- Створення запису через календар: рік, місяць і день тижня.
- Час, послуга, ім’я клієнта, ціна, а також необов’язкові телефон і нотатки.
- Перегляд календаря, найближчих записів, редагування й скасування.
- Підсумок цін записів за кожен місяць і рік.
- Нагадування та перевірка доступу за Telegram ID.

## Налаштування

Скопіюйте `.env.example` до `.env` і задайте:

- `BOT_TOKEN` — токен від BotFather.
- `ALLOWED_USER_IDS` — Telegram ID власника; кілька ID можна розділити комами.
- `DATABASE_PATH` — шлях до SQLite-файлу (типово `data/appointments.db`).

## Запуск

Залежності: Python 3.10 або новіший.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m appbot
```

На macOS за потреби використовується системний файл сертифікатів `/etc/ssl/cert.pem`.

## Veltramon

- Runtime: Python.
- Start command: `python -m appbot`.
- Додайте `BOT_TOKEN` і `ALLOWED_USER_IDS` у змінні середовища платформи.
- `requirements.txt` містить залежності проєкту.

## Перевірка

```bash
python -m unittest discover -s tests -t . -v
```
