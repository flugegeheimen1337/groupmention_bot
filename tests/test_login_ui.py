import unittest

from app.login_ui import is_login_code, mask_phone, normalize_login_code, user_can_connect
from app.login_web import code_sent_text


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

    def test_expected_username_can_connect_without_numeric_id(self):
        self.assertTrue(user_can_connect(5, "MaxM_DM", None, "maxm_dm"))
        self.assertFalse(user_can_connect(5, "Assistant_Polina", None, "maxm_dm"))

    def test_numeric_owner_can_connect(self):
        self.assertTrue(user_can_connect(5, None, 5, "maxm_dm"))

    def test_code_instructions_keep_the_code_out_of_telegram(self):
        text = code_sent_text("+971***75", "http://example.test/abc")
        self.assertIn("сразу отменяет код", text)
        self.assertIn("http://example.test/abc", text)


if __name__ == "__main__":
    unittest.main()
