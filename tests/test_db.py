import tempfile
import unittest
from pathlib import Path

from app.db import Store


class StoreTests(unittest.TestCase):
    def test_sent_messages_are_remembered(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "mentions.sqlite3")
            self.assertFalse(store.was_sent(1, 2))
            store.mark_sent(1, 2)
            self.assertTrue(store.was_sent(1, 2))
            store.mark_sent(1, 2)
            self.assertIsNone(store.get_notify_chat())
            store.set_notify_chat(42)
            self.assertEqual(store.get_notify_chat(), 42)
            store.set_notify_chat(43)
            self.assertEqual(store.get_notify_chat(), 43)
            store.close()


if __name__ == "__main__":
    unittest.main()
