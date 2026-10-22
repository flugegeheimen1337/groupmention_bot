import os
import secrets

from aiohttp import web
from telethon import TelegramClient
from telethon.errors import (
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

from app.config import Settings
from app.db import Store
from app.login_ui import is_login_code, normalize_login_code

PAGE = """<!doctype html>
<html lang="ru">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Код Telegram</title>
<body style="font-family: sans-serif; max-width: 28rem; margin: 2rem auto; padding: 0 1rem;">
<h1 style="font-size: 1.25rem;">Вход в Telegram</h1>
<p>{notice}</p>
<form method="post">
<label for="value">{label}</label><br>
<input id="value" name="value" {extra} required autofocus
 style="font-size: 1.5rem; padding: .4rem; width: 100%; margin: .6rem 0;">
<button style="font-size: 1.1rem; padding: .5rem 1rem;">Продолжить</button>
</form>
</body>
</html>
"""


def code_sent_text(masked_phone: str, url: str) -> str:
    return (
        f"Код отправлен на {masked_phone}. Он в служебном чате «Telegram».\n\n"
        "Не отправляйте эти цифры сообщением в Telegram: он сразу отменяет код.\n\n"
        f"Откройте страницу и введите код там:\n{url}"
    )


def public_base() -> str | None:
    explicit = os.environ.get("LOGIN_PUBLIC_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    host = os.environ.get("LOGIN_PUBLIC_HOST", "").strip()
    port = os.environ.get("LOGIN_PORT", "8080").strip() or "8080"
    if not host:
        return None
    return f"http://{host}:{port}"


def _page(notice: str, label: str, extra: str) -> web.Response:
    html = PAGE.format(notice=notice, label=label, extra=extra)
    return web.Response(text=html, content_type="text/html")


async def start_login_site(client: TelegramClient, store: Store, settings: Settings, pending, bot) -> str | None:
    base = public_base()
    if base is None:
        return None
    pending.web_token = secrets.token_urlsafe(18)
    port = int(os.environ.get("LOGIN_PORT", "8080").strip() or "8080")

    def allowed(token: str) -> bool:
        return token == pending.web_token

    async def show(request: web.Request) -> web.Response:
        if not allowed(request.match_info["token"]):
            return web.Response(status=404, text="not found")
        if pending.step == "password":
            return _page(
                "Код принят. Введите пароль двухэтапной проверки. Он не сохраняется.",
                "Пароль",
                'type="password" autocomplete="current-password"',
            )
        return _page(
            "Введите пять цифр из служебного чата «Telegram». В сам Telegram их отправлять не нужно.",
            "Код",
            'inputmode="numeric" autocomplete="one-time-code" pattern="[0-9 ]{5,7}"',
        )

    async def submit(request: web.Request) -> web.Response:
        if not allowed(request.match_info["token"]):
            return web.Response(status=404, text="not found")
        form = await request.post()
        value = str(form.get("value", ""))
        if pending.step == "password":
            try:
                async with pending.lock:
                    await client.sign_in(password=value)
            except PasswordHashInvalidError:
                return _page("Пароль не подошёл.", "Пароль", 'type="password"')
            except Exception:
                return _page("Пароль не принят. Введите его ещё раз.", "Пароль", 'type="password"')
            await _complete(bot, client, store, settings, pending)
            return web.Response(text="Вход выполнен. Вернитесь в бота MentionMe.", content_type="text/plain")
        if pending.step != "code" or not pending.code_hash:
            return _page("Сначала в боте нажмите «Получить код».", "Код", 'inputmode="numeric"')
        if not is_login_code(value):
            return _page("Нужны пять цифр.", "Код", 'inputmode="numeric"')
        try:
            async with pending.lock:
                await client.sign_in(
                    settings.phone,
                    normalize_login_code(value),
                    phone_code_hash=pending.code_hash,
                )
        except SessionPasswordNeededError:
            pending.step = "password"
            return _page(
                "Код принят. Введите пароль двухэтапной проверки. Он не сохраняется.",
                "Пароль",
                'type="password"',
            )
        except PhoneCodeInvalidError:
            return _page("Код не подошёл. Проверьте цифры в служебном чате.", "Код", 'inputmode="numeric"')
        except PhoneCodeExpiredError:
            pending.step = None
            pending.code_hash = None
            return _page("Этот код уже не действует. В боте нажмите «Получить код» ещё раз.", "Код", 'inputmode="numeric"')
        except Exception:
            return _page("Войти не получилось. Запросите новый код в боте.", "Код", 'inputmode="numeric"')
        await _complete(bot, client, store, settings, pending)
        return web.Response(text="Вход выполнен. Вернитесь в бота MentionMe.", content_type="text/plain")

    app = web.Application()
    app.router.add_get("/{token}", show)
    app.router.add_post("/{token}", submit)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    return f"{base}/{pending.web_token}"


async def _complete(bot, client, store, settings, pending) -> None:
    from app.main import _finish_login

    class _Target:
        def __init__(self, chat_id: int):
            self.chat = type("Chat", (), {"id": chat_id})()

        async def answer(self, text: str) -> None:
            await bot.send_message(self.chat.id, text)

    chat_id = pending.chat_id
    if chat_id is None:
        return
    await _finish_login(_Target(chat_id), client, store, settings, pending)
