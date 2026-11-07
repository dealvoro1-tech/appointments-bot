import unittest

from appbot.validators import (
    ValidationError, clean_client_name, clean_notes, clean_procedure, normalize_phone,
    parse_price, parse_reminder_hours, parse_time,
)


class TimeTests(unittest.TestCase):
    def test_valid_formats(self):
        for text, expected in [("14:30", "14:30"), ("9:05", "09:05"), ("14.30", "14:30"),
                               ("1430", "14:30"), ("930", "09:30"), ("14", "14:00"),
                               ("14 30", "14:30"), (" 8:00 ", "08:00"), ("00:00", "00:00")]:
            self.assertEqual(parse_time(text).strftime("%H:%M"), expected, text)

    def test_invalid(self):
        for text in ["", "abc", "24:00", "12:60", "25", "12:5", "12:300", "1:2:3", "-5"]:
            with self.assertRaises(ValidationError, msg=text):
                parse_time(text)

    def test_error_is_ukrainian(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_time("abc")
        self.assertIn("Невірний формат часу", str(ctx.exception))


class PriceTests(unittest.TestCase):
    def test_valid(self):
        cases = {"500": 50000, "500 грн": 50000, "500грн": 50000, "₴500": 50000,
                 "750,50": 75050, "750.5": 75050, "1 500": 150000, "0": 0, "1000000": 100_000_000,
                 "500 UAH": 50000, "1\u00a0500 грн": 150000}
        for text, kop in cases.items():
            self.assertEqual(parse_price(text), kop, text)

    def test_invalid(self):
        for text in ["", "abc", "-5", "5.555", "1e3", "грн", "1000000.01", "12,3,4", "500 usd"]:
            with self.assertRaises(ValidationError, msg=text):
                parse_price(text)


class TextFieldTests(unittest.TestCase):
    def test_procedure(self):
        self.assertEqual(clean_procedure("  Манікюр   класичний "), "Манікюр класичний")
        for bad in ["", "   ", "!!!", "x" * 101]:
            with self.assertRaises(ValidationError):
                clean_procedure(bad)

    def test_client(self):
        self.assertEqual(clean_client_name(" Олена  П. "), "Олена П.")
        for bad in ["", "О", "123", "я" * 101]:
            with self.assertRaises(ValidationError):
                clean_client_name(bad)

    def test_notes(self):
        self.assertEqual(clean_notes("алергія\n\n\n\nна лак"), "алергія\n\nна лак")
        for bad in ["", "   ", "я" * 501]:
            with self.assertRaises(ValidationError):
                clean_notes(bad)


class PhoneTests(unittest.TestCase):
    def test_valid(self):
        cases = {"0501234567": "+380501234567", "+380501234567": "+380501234567",
                 "380501234567": "+380501234567", "(050) 123-45-67": "+380501234567",
                 "+48 600 100 200": "+48600100200"}
        for text, expected in cases.items():
            self.assertEqual(normalize_phone(text), expected, text)

    def test_invalid(self):
        for text in ["", "abc", "12345", "+12", "05012345", "050123456789012345"]:
            with self.assertRaises(ValidationError, msg=text):
                normalize_phone(text)


class HoursTests(unittest.TestCase):
    def test_hours(self):
        self.assertEqual(parse_reminder_hours("24"), 24)
        self.assertEqual(parse_reminder_hours("3 год"), 3)
        for bad in ["0", "169", "abc", "", "1.5", "-2"]:
            with self.assertRaises(ValidationError):
                parse_reminder_hours(bad)


if __name__ == "__main__":
    unittest.main()
