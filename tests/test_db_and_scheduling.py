import sqlite3
import unittest
from datetime import date, datetime, time

from appbot.models import Session
from appbot.scheduling import Scheduler
from appbot.timeutil import TZ, to_epoch
from appbot.validators import ValidationError
from tests.helpers import NOW, BotTestCase, Clock


class PersistenceTests(BotTestCase):
    def test_appointments_survive_restart(self):
        a = self.add(phone="+380501234567", notes="алергія")
        self.restart()
        b = self.repo.get_appointment(a.id)
        self.assertEqual((b.client_name, b.procedure, b.price_kop, b.phone, b.notes),
                         ("Олена", "Манікюр", 50000, "+380501234567", "алергія"))
        self.assertEqual(self.repo.list_for_date("2026-11-10")[0].id, a.id)

    def test_init_schema_is_idempotent_and_keeps_data(self):
        self.add()
        self.repo.init_schema()
        self.repo.init_schema()
        self.assertEqual(len(self.repo.list_for_date("2026-11-10")), 1)

    def test_optional_fields_not_required(self):
        a = self.add()
        self.assertIsNone(a.phone)
        self.assertIsNone(a.notes)
        self.assertTrue(a.created_at.endswith("Z"))

    def test_chronological_order(self):
        self.add(time="16:00", client="Б")
        self.add(time="09:15", client="А")
        self.add(time="12:00", client="В")
        self.assertEqual([a.time for a in self.repo.list_for_date("2026-11-10")], ["09:15", "12:00", "16:00"])

    def test_cancel_is_soft_and_hides_from_lists(self):
        a = self.add()
        self.assertIsNotNone(self.repo.cancel_appointment(a.id))
        self.assertEqual(self.repo.list_for_date("2026-11-10"), [])
        self.assertEqual(self.repo.get_appointment(a.id).status, "cancelled")
        self.assertIsNone(self.repo.cancel_appointment(a.id))  # повторно — ні
        self.assertIsNone(self.repo.update_appointment(a.id, procedure="Х"))

    def test_update_recomputes_start_and_resets_reminder(self):
        a = self.add()
        self.repo.mark_reminded(a.id)
        b = self.repo.update_appointment(a.id, time="15:00")
        self.assertEqual(b.starts_at, to_epoch(date(2026, 11, 10), time(15, 0)))
        self.assertIsNone(b.reminded_at)

    def test_update_rejects_unknown_field(self):
        a = self.add()
        with self.assertRaises(ValueError):
            self.repo.update_appointment(a.id, status="cancelled")

    def test_calendar_counts(self):
        self.add(date="2026-11-10")
        self.add(date="2026-11-10", time="10:00")
        self.add(date="2026-12-01")
        c = self.add(date="2027-01-05")
        self.repo.cancel_appointment(c.id)
        self.assertEqual(self.repo.day_counts(2026, 11), {10: 2})
        self.assertEqual(self.repo.month_counts(2026), {11: 2, 12: 1})
        self.assertEqual(self.repo.year_counts(), {2026: 3})

    def test_session_roundtrip_and_atomic_reset_on_create(self):
        self.repo.save_session(OWNER := 111, Session("new_client", {"draft": {"date": "2026-11-10"}}))
        self.restart()
        s = self.repo.get_session(111)
        self.assertEqual((s.state, s.draft), ("new_client", {"date": "2026-11-10"}))
        self.repo.create_appointment(date="2026-11-10", time="10:00", procedure="П", client_name="Кл",
                                     price_kop=100, reset_session_for=111)
        self.assertEqual(self.repo.get_session(111).state, "idle")

    def test_corrupt_session_json_is_ignored(self):
        self.repo.save_session(1, Session("idle", {}))
        with sqlite3.connect(self.db_path) as c:
            c.execute("UPDATE sessions SET data='{broken' WHERE user_id=1")
        self.assertEqual(self.repo.get_session(1).data, {})

    def test_suggestions(self):
        self.add(procedure="Манікюр", client="Олена", price=50000)
        self.add(procedure="Манікюр", client="Ірина", price=60000, time="11:00")
        self.add(procedure="Педикюр", client="Олена", price=70000, time="12:00")
        self.assertEqual(self.repo.frequent_values("procedure")[0], "Манікюр")
        self.assertEqual(self.repo.frequent_values("client_name")[0], "Олена")
        self.assertEqual(self.repo.last_price_for("Манікюр"), 60000)
        self.assertIsNone(self.repo.last_price_for("Невідома"))


class SchedulerTests(BotTestCase):
    def test_rejects_past_date(self):
        with self.assertRaises(ValidationError) as ctx:
            self.sched.check_date_allowed(date(2026, 11, 6))
        self.assertIn("минуло", str(ctx.exception))
        self.sched.check_date_allowed(date(2026, 11, 7))  # сьогодні — ок

    def test_rejects_past_time_today_but_not_future(self):
        with self.assertRaises(ValidationError):
            self.sched.check_slot(date(2026, 11, 7), time(11, 59))
        with self.assertRaises(ValidationError):
            self.sched.check_slot(date(2026, 11, 7), time(12, 0))
        self.sched.check_slot(date(2026, 11, 7), time(12, 1))
        self.sched.check_slot(date(2026, 11, 8), time(0, 0))

    def test_dst_gap_time_rejected(self):
        # 29.03.2026 о 03:00 годинники переводять на 04:00 — 03:30 не існує
        sched = Scheduler(self.repo, 24, Clock(datetime(2026, 3, 1, 12, 0, tzinfo=TZ)))
        with self.assertRaises(ValidationError) as ctx:
            sched.check_slot(date(2026, 3, 29), time(3, 30))
        self.assertIn("літній час", str(ctx.exception))
        sched.check_slot(date(2026, 3, 29), time(4, 30))

    def test_timestamps_use_kyiv_time(self):
        # у листопаді Київ = UTC+2, у липні = UTC+3
        self.assertEqual(to_epoch(date(2026, 11, 10), time(14, 30)),
                         int(datetime(2026, 11, 10, 12, 30, tzinfo=__import__("datetime").timezone.utc).timestamp()))
        self.assertEqual(to_epoch(date(2026, 7, 10), time(14, 30)),
                         int(datetime(2026, 7, 10, 11, 30, tzinfo=__import__("datetime").timezone.utc).timestamp()))

    def test_conflict_detection(self):
        a = self.add(time="14:30")
        self.assertEqual([c.id for c in self.sched.conflicts(date(2026, 11, 10), time(14, 30))], [a.id])
        self.assertEqual(self.sched.conflicts(date(2026, 11, 10), time(14, 31)), [])
        self.assertEqual(self.sched.conflicts(date(2026, 11, 11), time(14, 30)), [])
        self.assertEqual(self.sched.conflicts(date(2026, 11, 10), time(14, 30), exclude_id=a.id), [])

    def test_cancelled_do_not_conflict(self):
        a = self.add(time="14:30")
        self.sched.cancel(a.id)
        self.assertEqual(self.sched.conflicts(date(2026, 11, 10), time(14, 30)), [])

    def test_reminder_settings_default_and_change(self):
        self.assertEqual(self.sched.reminder_settings(), (True, 24))
        self.sched.set_reminder_hours(3)
        self.sched.set_reminders_enabled(False)
        self.restart()
        self.assertEqual(self.sched.reminder_settings(), (False, 3))
        with self.assertRaises(ValidationError):
            self.sched.set_reminder_hours(0)

    def test_created_inside_reminder_window_is_not_reminded(self):
        draft = {"date": "2026-11-07", "time": "18:00", "procedure": "П", "client": "Кл", "price_kop": 100}
        soon = self.sched.create(draft)
        self.assertIsNotNone(self.repo.get_appointment(soon.id).reminded_at)
        draft["date"], draft["time"] = "2026-11-20", "10:00"
        later = self.sched.create(draft)
        self.assertIsNone(self.repo.get_appointment(later.id).reminded_at)


if __name__ == "__main__":
    unittest.main()
