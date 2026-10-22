import tempfile
import unittest
from pathlib import Path

from app.db import Store


class StoreTests(unittest.TestCase):
    def test_sent_messages_are_remembered(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "mentions.sqlite3")
            self.assertFalse(store.was_sent(7, 1, 2))
            store.mark_sent(7, 1, 2)
            self.assertTrue(store.was_sent(7, 1, 2))
            self.assertFalse(store.was_sent(8, 1, 2))
            store.mark_sent(7, 1, 2)
            store.set_login_phone(7, "+79055553041")
            self.assertEqual(store.get_login_phone(7), "+79055553041")
            self.assertIsNone(store.get_login_phone(8))
            store.set_notify_chat_for(7, 70)
            self.assertEqual(store.get_notify_chat_for(7), 70)
            self.assertIsNone(store.get_notify_chat_for(8))
            self.assertIsNone(store.get_notify_chat())
            store.set_notify_chat(42)
            self.assertEqual(store.get_notify_chat(), 42)
            store.set_notify_chat(43)
            self.assertEqual(store.get_notify_chat(), 43)
            store.save_alert(7, -100, 5, 70, 900, "<b>Группа</b>", "https://t.me/c/1/5", False)
            store.save_alert(7, -100, 9, 70, 901, "<b>Группа</b>", None, False)
            store.save_alert(8, -100, 5, 80, 902, "<b>Группа</b>", None, False)
            self.assertEqual(store.unread_chat_ids(7), [-100])
            pending = store.unread_up_to(7, -100, 5)
            self.assertEqual([item.message_id for item in pending], [5])
            self.assertEqual(pending[0].bot_message_id, 900)
            self.assertEqual(pending[0].url, "https://t.me/c/1/5")
            store.mark_alert_read(7, -100, 5)
            self.assertEqual([item.message_id for item in store.unread_up_to(7, -100, 9)], [9])
            self.assertEqual(store.unread_chat_ids(7), [-100])
            self.assertEqual(store.unread_chat_ids(8), [-100])
            store.close()


if __name__ == "__main__":
    unittest.main()
