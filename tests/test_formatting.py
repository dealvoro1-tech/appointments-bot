import unittest
from datetime import date, time

from appbot.formatting import (
    WEEKDAYS_SHORT, format_date_long, format_date_short, format_duration, format_price, format_time,
    weekday_short,
)


class FormattingTests(unittest.TestCase):
    def test_weekday_abbreviations(self):
        self.assertEqual(WEEKDAYS_SHORT, ("пн", "вт", "ср", "чт", "пт", "сб", "нд"))
        # 2026-11-02 — понеділок
        got = [weekday_short(date(2026, 11, 2 + i)) for i in range(7)]
        self.assertEqual(got, ["пн", "вт", "ср", "чт", "пт", "сб", "нд"])

    def test_long_date(self):
        self.assertEqual(format_date_long(date(2026, 11, 7)), "субота, 7 листопада 2026")
        self.assertEqual(format_date_long(date(2026, 11, 13)), "п’ятниця, 13 листопада 2026")

    def test_short_date_and_time(self):
        self.assertEqual(format_date_short(date(2026, 11, 7)), "07.11.2026 (сб)")
        self.assertEqual(format_time(time(9, 5)), "09:05")

    def test_price(self):
        self.assertEqual(format_price(50000), "500 грн")
        self.assertEqual(format_price(50050), "500,50 грн")
        self.assertEqual(format_price(150000), "1\u00a0500 грн")
        self.assertEqual(format_price(0), "0 грн")

    def test_duration(self):
        self.assertEqual(format_duration(45 * 60), "45 хв")
        self.assertEqual(format_duration(2 * 3600 + 15 * 60), "2 год 15 хв")
        self.assertEqual(format_duration(26 * 3600), "1 д 2 год")


if __name__ == "__main__":
    unittest.main()
