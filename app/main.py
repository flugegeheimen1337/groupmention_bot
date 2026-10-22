import asyncio
import logging
import signal
import time

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup
from telethon import TelegramClient, utils
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import GetPeerDialogsRequest
from telethon.tl.types import InputDialogPeer

from app.config import load_settings, normalize_phone
from app.db import Alert, Store
from app.format import notification_html, sender_label, with_read_status
from app.hub import AccountHub
from app.links import build_message_link
from app.login_ui import code_was_sent, describe_code_delivery, is_login_code, mask_phone
from app.login_web import code_sent_text, request_login_code, start_login_site
from app.mentions import is_explicit_mention, is_group_chat

log = logging.getLogger("groupmention")
CODE_RETRY_SECONDS = 120

START_TEXT = (
    "К этому боту можно подключить несколько аккаунтов. "
    "Каждый получает уведомления только из своих групп.\n\n"
    "Отправьте номер аккаунта в виде +79991234567.\n"
    "Затем нажмите «Получить код». Пять цифр введите на странице по ссылке, не в этот чат: "
    "Telegram сразу отменяет код, отправленный сообщением."
)


def _button(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Перейти к сообщению", url=url)]]
    )


def login_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(text="Получить код"),
            KeyboardButton(text="Ввести код"),
        ]],
        resize_keyboard=True,
        is_persistent=True,
    )


async def _send(bot: Bot, chat_id: int, text: str, url: str | None):
    markup = _button(url) if url else None
    for attempt in range(4):
        try:
            return await bot.send_message(chat_id, text, reply_markup=markup)
        except TelegramRetryAfter as exc:
            if attempt == 3:
                raise
            await asyncio.sleep(exc.retry_after + 1)
    return None


async def _edit(bot: Bot, chat_id: int, message_id: int, text: str, url: str | None) -> bool:
    markup = _button(url) if url else None
    for attempt in range(4):
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return True
        except TelegramRetryAfter as exc:
            if attempt == 3:
                return False
            await asyncio.sleep(exc.retry_after + 1)
        except TelegramBadRequest as exc:
            detail = str(exc).lower()
            if "not modified" in detail or "not found" in detail or "message_id_invalid" in detail:
                return True
            log.warning("Не удалось обновить статус уведомления: %s", exc)
            return False
        except Exception:
            log.exception("Не удалось обновить статус уведомления")
            return False
    return False


async def _apply_read(bot: Bot, store: Store, alert: Alert) -> None:
    changed = await _edit(bot, alert.bot_chat_id, alert.bot_message_id, with_read_status(alert.body, True), alert.url)
    if not changed:
        return
    store.mark_alert_read(alert.user_id, alert.chat_id, alert.message_id)
    log.info("Прочитано: user %s, chat %s, message %s", alert.user_id, alert.chat_id, alert.message_id)


async def _read_max_by_chat(client: TelegramClient, chat_ids: list[int]) -> dict[int, int]:
    found: dict[int, int] = {}
    for start in range(0, len(chat_ids), 20):
        peers = []
        for chat_id in chat_ids[start:start + 20]:
            try:
                entity = await client.get_input_entity(chat_id)
            except Exception:
                log.info("Чат %s недоступен для проверки прочтения", chat_id)
                continue
            peers.append(InputDialogPeer(entity))
        if not peers:
            continue
        result = await client(GetPeerDialogsRequest(peers))
        for dialog in result.dialogs:
            found[utils.get_peer_id(dialog.peer)] = dialog.read_inbox_max_id or 0
    return found


async def _sync_read_marks(client: TelegramClient, bot: Bot, store: Store, user_id: int) -> None:
    maxima = await _read_max_by_chat(client, store.unread_chat_ids(user_id))
    for chat_id, max_id in maxima.items():
        for alert in store.unread_up_to(user_id, chat_id, max_id):
            await _apply_read(bot, store, alert)


async def _request_code(message: Message, hub: AccountHub) -> None:
    user = message.from_user
    if user is None:
        return
    pending = hub.for_user(user.id)
    if user.id in hub.clients and await hub.clients[user.id].is_user_authorized():
        await message.answer("Этот аккаунт уже подключён. Упоминания из его групп приходят сюда.", reply_markup=login_keyboard())
        return
    if not pending.phone:
        await message.answer("Сначала отправьте номер в виде +79991234567.", reply_markup=login_keyboard())
        return
    if pending.step == "code" and pending.code_hash and pending.page_url and pending.sent_at:
        wait = CODE_RETRY_SECONDS - (time.monotonic() - pending.sent_at)
        if wait > 0:
            await message.answer(
                "Код уже запрошен и ещё действует. Повторный запрос отменит его.\n\n"
                f"{pending.delivery}\n\n{pending.page_url}",
                reply_markup=login_keyboard(),
            )
            return
    client = await hub.client_for(user.id)
    pending.client = client
    pending.chat_id = message.chat.id
    try:
        async with pending.lock:
            sent = await request_login_code(client, pending.phone)
    except FloodWaitError as exc:
        await message.answer(f"Telegram просит подождать {exc.seconds} секунд.", reply_markup=login_keyboard())
        return
    except Exception:
        log.exception("Не удалось отправить код")
        await message.answer("Не удалось отправить код. Попробуйте ещё раз.", reply_markup=login_keyboard())
        return
    type_name = type(sent.type).__name__ if getattr(sent, "type", None) else ""
    delivery = describe_code_delivery(type_name)
    log.info("Код запрошен, способ доставки: %s", type_name or "неизвестен")
    if not code_was_sent(type_name):
        pending.step = None
        pending.code_hash = None
        pending.sent_at = None
        await message.answer(delivery, reply_markup=login_keyboard())
        return
    pending.code_hash = sent.phone_code_hash
    pending.step = "code"
    pending.sent_at = time.monotonic()
    pending.delivery = delivery
    url = hub.issue_link(pending)
    if not url:
        await message.answer("Страница ввода кода не запущена.", reply_markup=login_keyboard())
        return
    await message.answer(code_sent_text(mask_phone(pending.phone), url, delivery), reply_markup=login_keyboard())


def _register_bot(dp: Dispatcher, hub: AccountHub, bot: Bot, store: Store) -> None:
    @dp.message(CommandStart())
    async def on_start(message: Message) -> None:
        user = message.from_user
        if user is None:
            return
        if user.id in hub.clients and await hub.clients[user.id].is_user_authorized():
            store.set_notify_chat_for(user.id, message.chat.id)
            await message.answer(
                "Этот аккаунт уже подключён. Упоминания из его групп приходят сюда.",
                reply_markup=login_keyboard(),
            )
            return
        await message.answer(START_TEXT, reply_markup=login_keyboard())

    @dp.message(F.text == "Получить код")
    async def on_send_code(message: Message) -> None:
        await _request_code(message, hub)

    @dp.message(F.text == "Ввести код")
    async def on_enter_code(message: Message) -> None:
        user = message.from_user
        if user is None:
            return
        url = hub.for_user(user.id).page_url
        if not url:
            await message.answer("Сначала нажмите «Получить код».", reply_markup=login_keyboard())
            return
        await message.answer(
            "Введите код на странице, не в этот чат. Иначе Telegram его отменит.\n" + url,
            reply_markup=login_keyboard(),
        )

    @dp.message()
    async def on_text(message: Message) -> None:
        user = message.from_user
        if user is None or not message.text:
            return
        pending = hub.for_user(user.id)
        phone = normalize_phone(message.text)
        if phone and len(phone) >= 11 and not is_login_code(message.text):
            pending.phone = phone
            pending.chat_id = message.chat.id
            pending.step = None
            pending.code_hash = None
            pending.sent_at = None
            await message.answer(
                f"Номер {mask_phone(phone)} сохранён. Нажмите «Получить код».",
                reply_markup=login_keyboard(),
            )
            return
        if pending.step == "code" and is_login_code(message.text):
            pending.step = None
            pending.code_hash = None
            await message.answer(
                "Этот код уже нельзя использовать: Telegram отменяет его, если отправить цифры сообщением. "
                "Нажмите «Получить код» и введите новый код на странице по ссылке.",
                reply_markup=login_keyboard(),
            )


async def _on_message(event, client: TelegramClient, bot: Bot, store: Store) -> None:
    message = event.message
    if message is None or not await client.is_user_authorized():
        return
    chat = await event.get_chat()
    if not is_group_chat(chat):
        return
    me = await client.get_me()
    if not is_explicit_mention(message.message, message.entities or [], me.id, me.username, message.out):
        return
    if store.was_sent(me.id, event.chat_id, message.id):
        return
    notify_chat = store.get_notify_chat_for(me.id) or me.id
    sender = await event.get_sender()
    text = notification_html(
        getattr(chat, "title", None) or "Группа",
        sender_label(sender, getattr(message, "post_author", None)),
        message.message,
    )
    url = build_message_link(event.chat_id, message.id, getattr(chat, "username", None))
    try:
        sent = await _send(bot, notify_chat, with_read_status(text, False), url)
    except TelegramForbiddenError:
        log.error("Бот не может написать пользователю %s. Нужно нажать «Запустить».", me.id)
        return
    except Exception:
        log.exception("Не удалось отправить уведомление")
        return
    if sent is None:
        return
    store.mark_sent(me.id, event.chat_id, message.id)
    store.save_alert(me.id, event.chat_id, message.id, sent.chat.id, sent.message_id, text, url, False)
    log.info("Уведомление отправлено: user %s, chat %s, message %s", me.id, event.chat_id, message.id)
    try:
        maxima = await _read_max_by_chat(client, [event.chat_id])
    except Exception:
        log.exception("Не удалось проверить, прочитано ли сообщение")
        return
    if message.id <= maxima.get(event.chat_id, 0):
        for alert in store.unread_up_to(me.id, event.chat_id, message.id):
            await _apply_read(bot, store, alert)


async def _on_read(event, client: TelegramClient, bot: Bot, store: Store) -> None:
    if getattr(event, "contents", False) or not event.inbox or not event.max_id or event.chat_id is None:
        return
    if not await client.is_user_authorized():
        return
    me = await client.get_me()
    if me is None:
        return
    for alert in store.unread_up_to(me.id, event.chat_id, event.max_id):
        await _apply_read(bot, store, alert)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings(require_bot=True)
    if settings.bot_token is None:
        raise SystemExit("В .env нужен BOT_TOKEN.")
    settings.session_path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(settings.database_path)
    hub = AccountHub(settings, store)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    ready = await start_login_site(hub, bot)
    if ready:
        log.info("Страница ввода кода запущена")
    else:
        log.error("Страница ввода кода не запущена: нет публичного адреса")

    async def on_mention(event, client) -> None:
        await _on_message(event, client, bot, store)

    async def on_read(event, client) -> None:
        await _on_read(event, client, bot, store)

    hub.on_mention = on_mention
    hub.on_read = on_read
    await hub.load_saved_sessions()
    for account_id, client in list(hub.clients.items()):
        try:
            await _sync_read_marks(client, bot, store, account_id)
        except Exception:
            log.exception("Не удалось сверить прочитанные сообщения для %s", account_id)
    dp = Dispatcher()
    _register_bot(dp, hub, bot, store)

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
    log.info("Слежение запущено, аккаунтов: %s", len(hub.clients))
    await stop.wait()
    polling.cancel()
    await hub.disconnect()
    await bot.session.close()
    store.close()
    try:
        await polling
    except (asyncio.CancelledError, Exception):
        pass
