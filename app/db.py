import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Alert:
    user_id: int
    chat_id: int
    message_id: int
    bot_chat_id: int
    bot_message_id: int
    body: str
    url: str | None


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_sent_table()
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                bot_chat_id INTEGER NOT NULL,
                bot_message_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                url TEXT,
                read INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, chat_id, message_id)
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

    def save_alert(
        self,
        user_id: int,
        chat_id: int,
        message_id: int,
        bot_chat_id: int,
        bot_message_id: int,
        body: str,
        url: str | None,
        read: bool,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO alerts (
                user_id, chat_id, message_id, bot_chat_id, bot_message_id, body, url, read
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, chat_id, message_id) DO UPDATE SET
                bot_chat_id = excluded.bot_chat_id,
                bot_message_id = excluded.bot_message_id,
                body = excluded.body,
                url = excluded.url,
                read = excluded.read
            """,
            (user_id, chat_id, message_id, bot_chat_id, bot_message_id, body, url, int(read)),
        )
        self.conn.commit()

    def unread_chat_ids(self, user_id: int) -> list[int]:
        rows = self.conn.execute(
            "SELECT DISTINCT chat_id FROM alerts WHERE user_id = ? AND read = 0",
            (user_id,),
        ).fetchall()
        return [row[0] for row in rows]

    def unread_up_to(self, user_id: int, chat_id: int, max_id: int) -> list[Alert]:
        rows = self.conn.execute(
            """
            SELECT user_id, chat_id, message_id, bot_chat_id, bot_message_id, body, url
            FROM alerts
            WHERE user_id = ? AND chat_id = ? AND message_id <= ? AND read = 0
            ORDER BY message_id
            """,
            (user_id, chat_id, max_id),
        ).fetchall()
        return [Alert(*row) for row in rows]

    def mark_alert_read(self, user_id: int, chat_id: int, message_id: int) -> None:
        self.conn.execute(
            "UPDATE alerts SET read = 1 WHERE user_id = ? AND chat_id = ? AND message_id = ?",
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
