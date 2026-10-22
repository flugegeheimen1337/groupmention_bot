import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sent (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                PRIMARY KEY (chat_id, message_id)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def was_sent(self, chat_id: int, message_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sent WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        ).fetchone()
        return row is not None

    def mark_sent(self, chat_id: int, message_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO sent (chat_id, message_id) VALUES (?, ?)",
            (chat_id, message_id),
        )
        self.conn.commit()

    def get_notify_chat(self) -> int | None:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = 'notify_chat_id'"
        ).fetchone()
        if row is None:
            return None
        return int(row[0])

    def set_notify_chat(self, chat_id: int) -> None:
        self.conn.execute(
            """
            INSERT INTO settings (key, value) VALUES ('notify_chat_id', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(chat_id),),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
