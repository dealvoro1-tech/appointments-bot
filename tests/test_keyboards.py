import unittest
from datetime import date

from appbot import keyboards as K
from appbot.formatting import WEEKDAYS_SHORT
from tests.helpers import BotTestCase

TODAY = date(2026, 11, 7)


def all_buttons(kb):
    return [b for row in kb["inline_keyboard"] for b in row]


class KeyboardTests(BotTestCase):
    def test_all_callbacks_fit_telegram_limit(self):
        a = self.add(client="Дуже довге імʼя клієнта " * 3, procedure="Процедура " * 10)
        kbs = [
            K.main_menu(True), K.year_picker("n", TODAY, {2026: 3}), K.year_picker("v", TODAY, {2025: 1}),
            K.year_picker("e12", TODAY, {}), K.month_picker("n", 2026, TODAY, {11: 2}),
            K.day_grid("n", 2026, 11, TODAY, {10: 1}), K.day_grid("v", 2026, 12, TODAY, {}, "l"),
            K.day_grid("e12", 2026, 11, TODAY, {}, "l"), K.day_view(date(2026, 11, 10), [a], True),
            K.upcoming_view([a]), K.appointment_actions(a), K.edit_menu(a), K.cancel_confirm(a),
            K.saved_view(a), K.settings_menu(True, 24), K.confirm_keyboard(), K.duplicate_keyboard(),
            K.step_keyboard(["a", "b"], 2, "keep", True), K.draft_exists_keyboard(),
        ]
        for kb in kbs:
            for b in all_buttons(kb):
                self.assertTrue(b["text"], b)
                self.assertLessEqual(len(b["callback_data"].encode()), 64, b)

    def test_month_grid_shows_ukrainian_weekdays_and_marks_days(self):
        kb = K.day_grid("v", 2026, 11, TODAY, {10: 2})
        rows = kb["inline_keyboard"]
        self.assertEqual([b["text"] for b in rows[1]], list(WEEKDAYS_SHORT))
        texts = [b["text"] for b in all_buttons(kb)]
        self.assertIn("10•", texts)       # день із записами
        self.assertIn("[7]", texts)       # сьогодні
        # 1 листопада 2026 — неділя: останній стовпець першого тижня
        self.assertEqual(rows[2][6]["text"], "1")
        self.assertTrue(all(r[i]["text"] == " " for r in rows[2:3] for i in range(6)))

    def test_list_view_shows_weekday_for_every_date(self):
        kb = K.day_grid("v", 2026, 11, TODAY, {}, "l")
        texts = [b["text"] for b in all_buttons(kb)]
        self.assertIn("1 нд", texts)
        self.assertIn("2 пн", texts)
        self.assertIn("[7 сб]", texts)
        self.assertIn("30 пн", texts)
        self.assertEqual(sum(1 for t in texts if t.strip("[]•").split(" ")[-1] in WEEKDAYS_SHORT), 30)

    def test_past_days_are_blocked_when_creating_but_open_in_view(self):
        new = {b["text"]: b["callback_data"] for b in all_buttons(K.day_grid("n", 2026, 11, TODAY, {}))}
        self.assertEqual(new["6"], K.PAST)
        self.assertTrue(new["8"].startswith("p:n:"))
        view = {b["text"]: b["callback_data"] for b in all_buttons(K.day_grid("v", 2026, 11, TODAY, {}))}
        self.assertTrue(view["6"].startswith("p:v:"))

    def test_past_months_blocked_when_creating(self):
        new = {b["text"]: b["callback_data"] for b in all_buttons(K.month_picker("n", 2026, TODAY, {}))}
        self.assertEqual(new["жовтень"], K.PAST)
        self.assertTrue(new["листопад"].startswith("d:n:"))

    def test_year_picker_new_starts_from_current_year(self):
        texts = [b["text"] for b in all_buttons(K.year_picker("n", TODAY, {}))]
        self.assertIn("2026", texts)
        self.assertNotIn("2025", texts)


if __name__ == "__main__":
    unittest.main()
