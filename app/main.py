import asyncio
import logging
import signal

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

from app.config import Settings, load_settings
from app.db import Store
from app.format import notification_html, sender_label
from app.links import build_message_link
from app.login_ui import is_login_code, mask_phone, normalize_login_code, user_can_connect
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


LOGIN_TEXT = (
    "Подключение аккаунта делается в этом чате.\n"
    "1. Нажмите «Получить код». Код придёт в служебный чат «Telegram», не сюда.\n"
    "2. Нажмите «Ввести код» и отправьте пять цифр."
)


class PendingLogin:
    def __init__(self) -> None:
        self.code_hash: str | None = None
        self.step: str | None = None
        self.lock = asyncio.Lock()


def login_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Получить код", callback_data="login:send"),
            InlineKeyboardButton(text="Ввести код", callback_data="login:enter"),
        ]]
    )


def _is_owner(user_id: int | None, username: str | None, settings: Settings) -> bool:
    return user_can_connect(user_id, username, settings.owner_id, settings.expected_username)


async def _finish_login(message: Message, client: TelegramClient, store: Store, settings: Settings, pending: PendingLogin) -> None:
    me = await client.get_me()
    expected = settings.expected_username
    pending.step = None
    pending.code_hash = None
    if expected and (me.username or "").casefold() != expected.casefold():
        actual = f"@{me.username}" if me.username else "без username"
        await message.answer(f"Вошли в {actual}. Для этого запуска нужен @{expected}.")
        log.error("Вход выполнен в %s, ожидался @%s", actual, expected)
        return
    store.set_notify_chat(message.chat.id)
    username = f"@{me.username}" if me.username else "без username"
    log.info("Вход выполнен: id %s, %s", me.id, username)
    await message.answer("Вход выполнен. Упоминания из групп будут приходить сюда.")


def _register_bot(
    dp: Dispatcher,
    client: TelegramClient,
    store: Store,
    settings: Settings,
    pending: PendingLogin,
) -> None:
    @dp.message(CommandStart())
    async def on_start(message: Message) -> None:
        user = message.from_user
        if not _is_owner(user.id if user else None, user.username if user else None, settings):
            await message.answer("Этот бот присылает уведомления только владельцу аккаунта.")
            return
        if await client.is_user_authorized():
            store.set_notify_chat(message.chat.id)
            await message.answer("Буду присылать сюда сообщения из групп, где отметили этот аккаунт.")
            return
        await message.answer(LOGIN_TEXT, reply_markup=login_keyboard())

    @dp.callback_query(F.data == "login:send")
    async def on_send_code(query: CallbackQuery) -> None:
        user = query.from_user
        if not _is_owner(user.id, user.username, settings):
            await query.answer("Это действие доступно только владельцу.", show_alert=True)
            return
        if await client.is_user_authorized():
            await query.answer("Аккаунт уже подключён.", show_alert=True)
            return
        if not settings.phone:
            await query.answer("Номер для входа не задан.", show_alert=True)
            return
        try:
            async with pending.lock:
                sent = await client.send_code_request(settings.phone)
                pending.code_hash = sent.phone_code_hash
                pending.step = "code"
        except FloodWaitError as exc:
            await query.answer(f"Telegram просит подождать {exc.seconds} секунд.", show_alert=True)
            return
        except Exception:
            log.exception("Не удалось отправить код")
            await query.answer("Не удалось отправить код. Попробуйте ещё раз.", show_alert=True)
            return
        await query.answer("Код отправлен")
        if query.message:
            await query.message.answer(
                f"Код отправлен на {mask_phone(settings.phone)}. "
                "Откройте служебный чат «Telegram» и нажмите «Ввести код». "
                "Предыдущий код больше не действует."
            )

    @dp.callback_query(F.data == "login:enter")
    async def on_enter_code(query: CallbackQuery) -> None:
        user = query.from_user
        if not _is_owner(user.id, user.username, settings):
            await query.answer("Это действие доступно только владельцу.", show_alert=True)
            return
        if pending.step != "code" or not pending.code_hash:
            await query.answer("Сначала нажмите «Получить код».", show_alert=True)
            return
        await query.answer()
        if query.message:
            await query.message.answer(
                "Введите пять цифр кода",
                reply_markup=ForceReply(input_field_placeholder="12345"),
            )

    @dp.message()
    async def on_login_text(message: Message) -> None:
        user = message.from_user
        if not _is_owner(user.id if user else None, user.username if user else None, settings) or pending.step is None:
            return
        text = message.text or ""
        if pending.step == "code":
            if not is_login_code(text):
                await message.answer("Нужны пять цифр кода. Нажмите «Ввести код» и отправьте их.")
                return
            try:
                async with pending.lock:
                    await client.sign_in(
                        settings.phone,
                        normalize_login_code(text),
                        phone_code_hash=pending.code_hash,
                    )
            except SessionPasswordNeededError:
                pending.step = "password"
                await message.answer(
                    "Код принят. Введите пароль двухэтапной проверки следующим сообщением. Он не сохраняется."
                )
                return
            except PhoneCodeInvalidError:
                await message.answer("Код не подошёл. Проверьте цифры или запросите новый кнопкой «Получить код».")
                return
            except PhoneCodeExpiredError:
                pending.step = None
                pending.code_hash = None
                await message.answer("Этот код уже не действует. Нажмите «Получить код» ещё раз.")
                return
            except Exception:
                log.exception("Не удалось войти по коду")
                await message.answer("Войти по этому коду не получилось. Нажмите «Получить код» ещё раз.")
                return
            await _finish_login(message, client, store, settings, pending)
            return
        if pending.step == "password":
            try:
                async with pending.lock:
                    await client.sign_in(password=text)
            except PasswordHashInvalidError:
                await message.answer("Пароль не подошёл. Введите его ещё раз.")
                return
            except Exception:
                log.exception("Не удалось подтвердить пароль")
                await message.answer("Пароль не принят. Введите его ещё раз.")
                return
            try:
                await message.delete()
            except Exception:
                log.info("Сообщение с паролем удалить не удалось")
            await _finish_login(message, client, store, settings, pending)


async def _on_message(event, client: TelegramClient, bot: Bot, store: Store, lock: asyncio.Lock) -> None:
    message = event.message
    if message is None or not await client.is_user_authorized():
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
    if await client.is_user_authorized():
        me = await client.get_me()
        expected = settings.expected_username
        if expected and (me.username or "").casefold() != expected.casefold():
            await client.disconnect()
            store.close()
            raise SystemExit(f"Сессия от другого аккаунта. Для этого запуска нужен @{expected}.")
        log.info("Аккаунт: id %s, %s", me.id, f"@{me.username}" if me.username else "без username")
    else:
        log.info("Сессия не авторизована. Вход выполняется кнопками в боте.")
    if settings.bot_token is None:
        raise SystemExit("В .env нужен BOT_TOKEN.")
    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    pending = PendingLogin()
    _register_bot(dp, client, store, settings, pending)
    if not await client.is_user_authorized() and settings.owner_id is not None:
        try:
            await bot.send_message(settings.owner_id, LOGIN_TEXT, reply_markup=login_keyboard())
        except TelegramForbiddenError:
            log.error("Владелец ещё не нажал «Запустить» у бота.")
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
