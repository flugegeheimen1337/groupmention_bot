import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    bot_token: str | None
    phone: str | None
    expected_username: str | None
    session_path: Path
    database_path: Path


def _resolve(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT / path


def normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    phone = "".join(ch for ch in value if ch.isdigit() or ch == "+")
    if phone.startswith("8") and len(phone) == 11:
        phone = "+7" + phone[1:]
    if phone and not phone.startswith("+"):
        phone = "+" + phone
    return phone or None


def normalize_username(value: str | None) -> str | None:
    if not value:
        return None
    username = value.strip().lstrip("@")
    return username or None


def load_settings(*, require_bot: bool) -> Settings:
    load_dotenv(ROOT / ".env")
    raw_id = os.environ.get("API_ID", "").strip()
    api_hash = os.environ.get("API_HASH", "").strip()
    bot_token = os.environ.get("BOT_TOKEN", "").strip() or None
    phone = normalize_phone(os.environ.get("PHONE"))
    expected_username = normalize_username(os.environ.get("EXPECTED_USERNAME"))
    if not raw_id or not api_hash:
        raise SystemExit("В .env нужны API_ID и API_HASH.")
    try:
        api_id = int(raw_id)
    except ValueError as exc:
        raise SystemExit("API_ID должен быть числом.") from exc
    if require_bot and not bot_token:
        raise SystemExit("В .env нужен BOT_TOKEN. Его присылает @BotFather после /newbot.")
    return Settings(
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token,
        phone=phone,
        expected_username=expected_username,
        session_path=_resolve(os.environ.get("SESSION_PATH", "data/user").strip()),
        database_path=_resolve(os.environ.get("DATABASE_PATH", "data/mentions.sqlite3").strip()),
    )
