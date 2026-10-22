import unittest

from app.format import notification_html, sender_label
from app.links import build_message_link
from app.mentions import is_explicit_mention, is_group_chat
from app.textutil import utf16_slice


def mention(offset: int, length: int):
    return type("MessageEntityMention", (), {"offset": offset, "length": length})()


def mention_name(user_id: int):
    return type("MessageEntityMentionName", (), {"user_id": user_id})()


class TextTests(unittest.TestCase):
    def test_utf16_offset_skips_emoji(self):
        text = "🙂 @name"
        self.assertEqual(utf16_slice(text, 3, 5), "@name")
        self.assertNotEqual(text[3:8], "@name")


class MentionTests(unittest.TestCase):
    def test_username_mention_is_case_insensitive(self):
        self.assertTrue(
            is_explicit_mention("see @Owner", [mention(4, 6)], 7, "owner", False)
        )

    def test_emoji_before_mention(self):
        self.assertTrue(
            is_explicit_mention("🙂 @name", [mention(3, 5)], 7, "name", False)
        )

    def test_other_username_is_ignored(self):
        self.assertFalse(
            is_explicit_mention("@other", [mention(0, 6)], 7, "owner", False)
        )

    def test_text_mention_matches_user_id(self):
        self.assertTrue(
            is_explicit_mention("Иван", [mention_name(7)], 7, "owner", False)
        )

    def test_text_mention_of_someone_else_is_ignored(self):
        self.assertFalse(
            is_explicit_mention("Иван", [mention_name(8)], 7, "owner", False)
        )

    def test_outgoing_message_is_ignored(self):
        self.assertFalse(
            is_explicit_mention("@owner", [mention(0, 6)], 7, "owner", True)
        )

    def test_reply_without_mention_is_ignored(self):
        self.assertFalse(is_explicit_mention("просто ответ", [], 7, "owner", False))

    def test_account_without_username_still_matches_text_mention(self):
        self.assertTrue(is_explicit_mention("Иван", [mention_name(7)], 7, None, False))
        self.assertFalse(is_explicit_mention("@owner", [mention(0, 6)], 7, None, False))


class ChatTests(unittest.TestCase):
    def test_basic_group(self):
        self.assertTrue(is_group_chat(type("Chat", (), {"title": "Работа"})()))

    def test_supergroup(self):
        chat = type("Channel", (), {"title": "Работа", "megagroup": True, "broadcast": False})()
        self.assertTrue(is_group_chat(chat))

    def test_broadcast_channel(self):
        chat = type("Channel", (), {"title": "Новости", "megagroup": False, "broadcast": True})()
        self.assertFalse(is_group_chat(chat))

    def test_private_chat(self):
        user = type("User", (), {"first_name": "Иван", "title": None})()
        self.assertFalse(is_group_chat(user))


class LinkTests(unittest.TestCase):
    def test_public_group(self):
        self.assertEqual(
            build_message_link(-100123, 15, "work"),
            "https://t.me/work/15",
        )

    def test_private_supergroup(self):
        self.assertEqual(
            build_message_link(-1001234567890, 15, None),
            "https://t.me/c/1234567890/15",
        )

    def test_basic_group_has_no_direct_link(self):
        self.assertIsNone(build_message_link(-456, 15, None))


class FormatTests(unittest.TestCase):
    def test_sender_with_username(self):
        sender = type("User", (), {"first_name": "Иван", "last_name": "Петров", "username": "ivan"})()
        self.assertEqual(sender_label(sender), "Иван Петров (@ivan)")

    def test_anonymous_group(self):
        sender = type("Channel", (), {"title": "Работа", "first_name": None})()
        self.assertEqual(sender_label(sender, "Анна"), "Работа (Анна)")

    def test_notification_escapes_html_and_keeps_title(self):
        text = notification_html("A & B", "Иван", "<b>привет</b>")
        self.assertIn("<b>A &amp; B</b>", text)
        self.assertIn("&lt;b&gt;привет&lt;/b&gt;", text)

    def test_empty_message(self):
        self.assertIn("Сообщение без текста", notification_html("Группа", "Иван", "  "))


if __name__ == "__main__":
    unittest.main()
