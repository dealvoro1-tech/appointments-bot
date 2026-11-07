import unittest

from appbot.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_ok(self):
        c = load_config({"BOT_TOKEN": "t", "ALLOWED_USER_IDS": "1, 2;3"})
        self.assertEqual(c.allowed_user_ids, frozenset({1, 2, 3}))
        self.assertEqual(c.default_reminder_hours, 24)

    def test_missing_or_bad(self):
        bad = [
            {},
            {"BOT_TOKEN": "t"},
            {"BOT_TOKEN": "t", "ALLOWED_USER_IDS": "abc"},
            {"BOT_TOKEN": "t", "ALLOWED_USER_IDS": "1", "DEFAULT_REMINDER_HOURS": "0"},
            {"ALLOWED_USER_IDS": "1"},
        ]
        for env in bad:
            with self.assertRaises(ConfigError, msg=env):
                load_config(env)


if __name__ == "__main__":
    unittest.main()
