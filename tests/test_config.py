import unittest

from app.config import normalize_phone, normalize_username


class ConfigTests(unittest.TestCase):
    def test_phone_spaces_are_removed(self):
        self.assertEqual(normalize_phone("+7 905 555 3041"), "+79055553041")

    def test_russian_8_prefix_becomes_country_code(self):
        self.assertEqual(normalize_phone("8 905 555 3041"), "+79055553041")

    def test_username_without_at(self):
        self.assertEqual(normalize_username("@Assistant_Polina"), "Assistant_Polina")

    def test_empty_values(self):
        self.assertIsNone(normalize_phone("   "))
        self.assertIsNone(normalize_username(""))


if __name__ == "__main__":
    unittest.main()
