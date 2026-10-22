import unittest

from app.login_ui import is_login_code, mask_phone, normalize_login_code


class LoginUiTests(unittest.TestCase):
    def test_mask_phone_keeps_ends(self):
        self.assertEqual(mask_phone("+79055553041"), "+790***41")

    def test_login_code_ignores_spaces(self):
        self.assertTrue(is_login_code("11 497"))
        self.assertEqual(normalize_login_code("11 497"), "11497")

    def test_rejects_other_text(self):
        self.assertFalse(is_login_code("код 11497"))
        self.assertFalse(is_login_code("1234"))
        self.assertFalse(is_login_code("123456"))


if __name__ == "__main__":
    unittest.main()
