import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_sent_table()
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def _ensure_sent_table(self) -> None:
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'sent'"
        ).fetchone()
        if row is not None:
            columns = [item[1] for item in self.conn.execute("PRAGMA table_info(sent)")]
            if "user_id" not in columns:
                self.conn.execute("ALTER TABLE sent RENAME TO sent_old")
                self.conn.execute("DROP TABLE sent_old")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sent (
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, chat_id, message_id)
            )
            """
        )

    def was_sent(self, user_id: int, chat_id: int, message_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sent WHERE user_id = ? AND chat_id = ? AND message_id = ?",
            (user_id, chat_id, message_id),
        ).fetchone()
        return row is not None

    def mark_sent(self, user_id: int, chat_id: int, message_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO sent (user_id, chat_id, message_id) VALUES (?, ?, ?)",
            (user_id, chat_id, message_id),
        )
        self.conn.commit()

    def set_notify_chat_for(self, account_id: int, chat_id: int) -> None:
        self.conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (f"notify:{account_id}", str(chat_id)),
        )
        self.conn.commit()

    def get_notify_chat_for(self, account_id: int) -> int | None:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (f"notify:{account_id}",),
        ).fetchone()
        if row is None:
            return None
        return int(row[0])

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
