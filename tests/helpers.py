"""Спільні допоміжні засоби для тестів: підроблений Telegram API, годинник, «чат»."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime

from appbot.bot import Bot
from appbot.db import Repository
from appbot.scheduling import Scheduler
from appbot.telegram_api import TelegramError
from appbot.timeutil import TZ

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=TZ)  # субота
OWNER = 111


class Clock:
    def __init__(self, dt=NOW):
        self.dt = dt

    def __call__(self):
        return self.dt


class FakeAPI:
    def __init__(self):
        self.messages = {}
        self.order = []        # id повідомлень у порядку останнього оновлення
        self.sent = []         # усі надіслані тексти
        self.answers = []      # (текст, alert)
        self.removed = []
        self._next = 100
        self.fail_send = False

    def _touch(self, mid):
        if mid in self.order:
            self.order.remove(mid)
        self.order.append(mid)

    def send_message(self, chat_id, text, reply_markup=None):
        from appbot.telegram_api import TelegramNetworkError
        if self.fail_send:
            raise TelegramNetworkError("down")
        self._next += 1
        self.messages[self._next] = {"chat_id": chat_id, "text": text, "markup": reply_markup}
        self.sent.append((chat_id, text))
        self._touch(self._next)
        return {"message_id": self._next}

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        if message_id not in self.messages:
            raise TelegramError("Bad Request: message to edit not found", 400)
        self.messages[message_id].update(text=text, markup=reply_markup)
        self._touch(message_id)
        return True

    def remove_keyboard(self, chat_id, message_id):
        self.removed.append(message_id)
        if message_id in self.messages:
            self.messages[message_id]["markup"] = None

    def answer_callback(self, callback_id, text=None, alert=False):
        self.answers.append((text, alert))

    @property
    def last_id(self):
        return self.order[-1]

    @property
    def last(self):
        return self.messages[self.last_id]

    @property
    def last_text(self):
        return self.last["text"]

    def buttons(self, mid=None):
        markup = self.messages[mid or self.last_id]["markup"] or {"inline_keyboard": []}
        return [b for row in markup["inline_keyboard"] for b in row]

    def callbacks(self, mid=None):
        return [b["callback_data"] for b in self.buttons(mid)]


class Chat:
    """Імітує користувача: надсилає текст і натискає кнопки останнього екрана."""

    def __init__(self, bot, api, user_id=OWNER):
        self.bot, self.api, self.user_id = bot, api, user_id
        self._update_id = 0

    def _uid(self):
        self._update_id += 1
        return self._update_id

    def send(self, text):
        self.bot.handle_update({
            "update_id": self._uid(),
            "message": {"message_id": self._uid(), "from": {"id": self.user_id},
                        "chat": {"id": self.user_id, "type": "private"}, "text": text},
        })

    def press(self, data, check=True):
        mid = self.api.last_id
        if check:
            assert data in self.api.callbacks(mid), f"Кнопки {data!r} немає на екрані: {self.api.callbacks(mid)}"
        self.bot.handle_update({
            "update_id": self._uid(),
            "callback_query": {
                "id": str(self._uid()), "from": {"id": self.user_id}, "data": data,
                "message": {"message_id": mid, "chat": {"id": self.user_id, "type": "private"}},
            },
        })

    def last_alert(self):
        return self.api.answers[-1][0] if self.api.answers else None


class BotTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "test.db")
        self.clock = Clock()
        self.repo = self.make_repo()
        self.api = FakeAPI()
        self.sched = Scheduler(self.repo, 24, self.clock)
        self.bot = Bot(self.api, self.repo, self.sched, {OWNER}, self.clock)
        self.chat = Chat(self.bot, self.api)

    def tearDown(self):
        self._tmp.cleanup()

    def make_repo(self):
        repo = Repository(self.db_path, clock=self.clock)
        repo.init_schema()
        return repo

    def add(self, date="2026-11-10", time="14:30", procedure="Манікюр", client="Олена", price=50000, **kw):
        return self.repo.create_appointment(
            date=date, time=time, procedure=procedure, client_name=client, price_kop=price, **kw
        )

    def restart(self):
        """Імітація перезапуску бота: нові об'єкти над тим самим файлом БД."""
        self.repo = self.make_repo()
        self.sched = Scheduler(self.repo, 24, self.clock)
        self.bot = Bot(self.api, self.repo, self.sched, {OWNER}, self.clock)
        self.chat = Chat(self.bot, self.api)
