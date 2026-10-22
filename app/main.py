import asyncio
import logging
import signal

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from telethon import TelegramClient, events

from app.config import load_settings
from app.db import Store
from app.format import notification_html, sender_label
from app.links import build_message_link
from app.mentions import is_explicit_mention, is_group_chat

log = logging.getLogger("groupmention")


def _button(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Перейти к сообщению", url=url)]]
    )


async def _send(bot: Bot, chat_id: int, text: str, url: str | None) -> None:
    markup = _button(url) if url else None
    for attempt in range(4):
        try:
            await bot.send_message(chat_id, text, reply_markup=markup)
            return
        except TelegramRetryAfter as exc:
            if attempt == 3:
                raise
            await asyncio.sleep(exc.retry_after + 1)


def _register_bot(dp: Dispatcher, client: TelegramClient, store: Store) -> None:
    @dp.message(CommandStart())
    async def on_start(message: Message) -> None:
        me = await client.get_me()
        user = message.from_user
        if user is None or user.id != me.id:
            await message.answer("Этот бот присылает уведомления только владельцу аккаунта.")
            return
        store.set_notify_chat(message.chat.id)
        await message.answer(
            "Буду присылать сюда сообщения из групп, где отметили этот аккаунт."
        )


async def _on_message(event, client: TelegramClient, bot: Bot, store: Store, lock: asyncio.Lock) -> None:
    message = event.message
    if message is None:
        return
    chat = await event.get_chat()
    if not is_group_chat(chat):
        return
    me = await client.get_me()
    if not is_explicit_mention(message.message, message.entities or [], me.id, me.username, message.out):
        return
    async with lock:
        if store.was_sent(event.chat_id, message.id):
            return
        notify_chat = store.get_notify_chat()
        if notify_chat is None:
            log.warning("Нет получателя. Владелец должен открыть бота и нажать «Запустить».")
            return
        sender = await event.get_sender()
        text = notification_html(
            getattr(chat, "title", None) or "Группа",
            sender_label(sender, getattr(message, "post_author", None)),
            message.message,
        )
        url = build_message_link(event.chat_id, message.id, getattr(chat, "username", None))
        try:
            await _send(bot, notify_chat, text, url)
        except TelegramForbiddenError:
            log.error("Бот не может написать владельцу. Нужно открыть бота и нажать «Запустить».")
            return
        except Exception:
            log.exception("Не удалось отправить уведомление")
            return
        store.mark_sent(event.chat_id, message.id)
        log.info("Уведомление отправлено: chat %s, message %s", event.chat_id, message.id)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings(require_bot=True)
    settings.session_path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(settings.database_path)
    client = TelegramClient(str(settings.session_path), settings.api_id, settings.api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        store.close()
        raise SystemExit("Сессия не авторизована. Сначала выполните: python -m app.login")

    me = await client.get_me()
    log.info("Аккаунт: id %s, %s", me.id, f"@{me.username}" if me.username else "без username")
    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    _register_bot(dp, client, store)
    lock = asyncio.Lock()

    async def handler(event) -> None:
        await _on_message(event, client, bot, store, lock)

    client.add_event_handler(handler, events.NewMessage(incoming=True))
    client.add_event_handler(handler, events.MessageEdited(incoming=True))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, request_stop)

    polling = asyncio.create_task(dp.start_polling(bot, handle_signals=False))

    def polling_finished(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            log.error("Бот остановился: %s", error)
        stop.set()

    polling.add_done_callback(polling_finished)
    log.info("Слежение запущено")
    await stop.wait()
    polling.cancel()
    await client.disconnect()
    await bot.session.close()
    store.close()
    try:
        await polling
    except (asyncio.CancelledError, Exception):
        pass
