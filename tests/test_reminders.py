import unittest
from datetime import datetime, timedelta

from appbot.reminders import ReminderWorker
from tests.helpers import NOW, OWNER, BotTestCase, Clock


class ReminderTests(BotTestCase):
    def worker(self):
        return ReminderWorker(self.api, self.repo, self.sched, [OWNER], self.clock)

    def test_sent_once_at_default_24h(self):
        a = self.add(date="2026-11-08", time="12:00")   # рівно через 24 години
        self.assertEqual(self.worker().run_once(), 1)
        self.assertEqual(len(self.api.sent), 1)
        text = self.api.sent[0][1]
        self.assertIn("Нагадування", text)
        self.assertIn("Манікюр", text)
        self.assertIn("500 грн", text)
        self.assertEqual(self.worker().run_once(), 0)  # вдруге — ні
        self.assertIsNotNone(self.repo.get_appointment(a.id).reminded_at)

    def test_not_sent_before_window(self):
        self.add(date="2026-11-09", time="12:00")
        self.assertEqual(self.worker().run_once(), 0)
        self.clock.dt = NOW + timedelta(hours=25)
        self.assertEqual(self.worker().run_once(), 1)

    def test_disabled(self):
        self.add(date="2026-11-08", time="12:00")
        self.sched.set_reminders_enabled(False)
        self.assertEqual(self.worker().run_once(), 0)
        self.assertEqual(self.api.sent, [])

    def test_custom_hours(self):
        self.add(date="2026-11-08", time="12:00")
        self.sched.set_reminder_hours(2)
        self.assertEqual(self.worker().run_once(), 0)
        self.clock.dt = NOW + timedelta(hours=22)
        self.assertEqual(self.worker().run_once(), 1)

    def test_cancelled_and_past_are_skipped(self):
        a = self.add(date="2026-11-08", time="12:00")
        self.sched.cancel(a.id)
        self.add(date="2026-11-06", time="10:00", client="Минуле")
        self.assertEqual(self.worker().run_once(), 0)

    def test_failed_delivery_is_retried(self):
        a = self.add(date="2026-11-08", time="12:00")
        self.api.fail_send = True
        self.assertEqual(self.worker().run_once(), 0)
        self.assertIsNone(self.repo.get_appointment(a.id).reminded_at)
        self.api.fail_send = False
        self.assertEqual(self.worker().run_once(), 1)

    def test_rescheduling_resets_reminder(self):
        a = self.add(date="2026-11-08", time="12:00")
        w = self.worker()
        w.run_once()
        self.sched.update(a.id, time="10:00")  # через 22 год: усередині вікна
        self.assertIsNotNone(self.repo.get_appointment(a.id).reminded_at)  # перенесено всередину вікна — пропуск
        self.sched.update(a.id, date="2026-11-20")
        self.assertIsNone(self.repo.get_appointment(a.id).reminded_at)
        self.clock.dt = datetime(2026, 11, 19, 12, 0, tzinfo=NOW.tzinfo)
        self.assertEqual(w.run_once(), 1)

    def test_reminder_survives_restart(self):
        self.add(date="2026-11-08", time="12:00")
        self.restart()
        self.assertEqual(self.worker().run_once(), 1)


if __name__ == "__main__":
    unittest.main()
