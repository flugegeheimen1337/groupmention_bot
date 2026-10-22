import asyncio
import logging
import secrets
from pathlib import Path

from telethon import TelegramClient, events

from app.config import Settings
from app.db import Store
from app.login_web import public_base

log = logging.getLogger("groupmention")


class PendingLogin:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.phone: str | None = None
        self.code_hash: str | None = None
        self.step: str | None = None
        self.chat_id: int | None = None
        self.page_url: str | None = None
        self.client: TelegramClient | None = None
        self.lock = asyncio.Lock()


class AccountHub:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store
        self.clients: dict[int, TelegramClient] = {}
        self.pending: dict[int, PendingLogin] = {}
        self.tokens: dict[str, int] = {}
        self._listening: set[int] = set()
        self.base_url = public_base()
        self.on_mention = None

    def for_user(self, user_id: int) -> PendingLogin:
        if user_id not in self.pending:
            self.pending[user_id] = PendingLogin(user_id)
        return self.pending[user_id]

    def pending_by_token(self, token: str) -> PendingLogin | None:
        user_id = self.tokens.get(token)
        if user_id is None:
            return None
        return self.pending.get(user_id)

    def is_connected(self, user_id: int) -> bool:
        client = self.clients.get(user_id)
        return client is not None and client.is_connected()

    async def load_saved_sessions(self) -> None:
        paths: list[str] = []
        legacy = Path(str(self.settings.session_path) + ".session")
        if legacy.exists():
            paths.append(str(self.settings.session_path))
        folder = self.settings.session_path.parent / "sessions"
        if folder.exists():
            for file in folder.glob("*.session"):
                paths.append(str(file.with_suffix("")))
        for path in paths:
            client = TelegramClient(path, self.settings.api_id, self.settings.api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                continue
            me = await client.get_me()
            self.clients[me.id] = client
            if self.store.get_notify_chat_for(me.id) is None:
                self.store.set_notify_chat_for(me.id, me.id)
            self.attach(me.id)
            username = f"@{me.username}" if me.username else "без username"
            log.info("Сессия восстановлена: id %s, %s", me.id, username)

    async def client_for(self, user_id: int) -> TelegramClient:
        existing = self.clients.get(user_id)
        if existing is not None:
            if not existing.is_connected():
                await existing.connect()
            return existing
        folder = self.settings.session_path.parent / "sessions"
        folder.mkdir(parents=True, exist_ok=True)
        client = TelegramClient(
            str(folder / str(user_id)),
            self.settings.api_id,
            self.settings.api_hash,
        )
        await client.connect()
        self.clients[user_id] = client
        return client

    def issue_link(self, pending: PendingLogin) -> str | None:
        if not self.base_url:
            return None
        if pending.page_url:
            return pending.page_url
        token = secrets.token_urlsafe(18)
        self.tokens[token] = pending.user_id
        pending.page_url = f"{self.base_url}/{token}"
        return pending.page_url

    def attach(self, account_id: int) -> None:
        if account_id in self._listening or self.on_mention is None:
            return
        client = self.clients.get(account_id)
        if client is None:
            return

        async def handler(event, bound_client=client) -> None:
            await self.on_mention(event, bound_client)

        client.add_event_handler(handler, events.NewMessage(incoming=True))
        client.add_event_handler(handler, events.MessageEdited(incoming=True))
        self._listening.add(account_id)

    async def complete(self, pending: PendingLogin, bot) -> None:
        client = pending.client
        if client is None:
            return
        me = await client.get_me()
        pending.step = None
        pending.code_hash = None
        self.clients.pop(pending.user_id, None)
        self.clients[me.id] = client
        chat_id = pending.chat_id or me.id
        self.store.set_notify_chat_for(me.id, chat_id)
        self.attach(me.id)
        username = f"@{me.username}" if me.username else "без username"
        log.info("Вход выполнен: id %s, %s", me.id, username)
        await bot.send_message(chat_id, "Вход выполнен. Упоминания из групп будут приходить сюда.")

    async def disconnect(self) -> None:
        for client in self.clients.values():
            await client.disconnect()
