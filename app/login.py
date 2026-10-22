import asyncio
import getpass
from pathlib import Path

from telethon import TelegramClient

from app.config import load_settings


async def run() -> None:
    settings = load_settings(require_bot=False)
    settings.session_path.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(settings.session_path), settings.api_id, settings.api_hash)
    await client.start(
        phone=settings.phone or (lambda: input("Номер телефона: ").strip()),
        code_callback=lambda: input("Код из Telegram: ").strip(),
        password=lambda: getpass.getpass("Пароль двухэтапной проверки: "),
    )
    me = await client.get_me()
    username = f"@{me.username}" if me.username else "без username"
    expected = settings.expected_username
    if expected and (me.username or "").casefold() != expected.casefold():
        await client.disconnect()
        session_file = Path(str(settings.session_path) + ".session")
        session_file.unlink(missing_ok=True)
        raise SystemExit(f"Вошли в {username}. Для этого запуска нужен @{expected}.")
    print(f"Вход выполнен: id {me.id}, {username}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(run())
