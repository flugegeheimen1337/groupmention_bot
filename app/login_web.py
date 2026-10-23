import logging
import os

from aiohttp import web
from telethon import utils
from telethon.tl.functions.auth import ResendCodeRequest, SendCodeRequest
from telethon.tl.types import CodeSettings
from telethon.tl.types.auth import SentCodeSuccess
from telethon.errors import (
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

from app.login_ui import is_login_code, normalize_login_code

log = logging.getLogger("groupmention")

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


def code_sent_text(masked_phone: str, url: str, delivery: str | None = None) -> str:
    where = delivery or (
        "Это не SMS. Откройте Telegram и найдите служебный чат «Telegram» "
        "(синяя галочка). Пять цифр лежат в последнем сообщении этого чата."
    )
    return (
        f"Код для {masked_phone} запрошен.\n\n"
        f"{where}\n\n"
        "Не отправляйте эти цифры сообщением в Telegram: он сразу отменяет код.\n\n"
        f"Откройте страницу и введите код там:\n{url}"
    )


async def request_login_code(client, phone: str):
    parsed = utils.parse_phone(phone) or phone
    client._phone_code_hash.pop(parsed, None)
    result = await client(SendCodeRequest(parsed, client.api_id, client.api_hash, CodeSettings()))
    if isinstance(result, SentCodeSuccess):
        raise RuntimeError("Сессия уже авторизована")
    if result.phone_code_hash:
        client._phone_code_hash[parsed] = result.phone_code_hash
    client._phone = parsed
    return result


async def resend_login_code(client, phone: str, phone_hash: str):
    parsed = utils.parse_phone(phone) or phone
    try:
        result = await client(ResendCodeRequest(parsed, phone_hash))
    except PhoneCodeExpiredError:
        return None
    if isinstance(result, SentCodeSuccess):
        raise RuntimeError("Сессия уже авторизована")
    if result.phone_code_hash:
        client._phone_code_hash[parsed] = result.phone_code_hash
    client._phone = parsed
    return result


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


async def start_login_site(hub, bot) -> bool:
    if not hub.base_url:
        return False
    port = int(os.environ.get("LOGIN_PORT", "8080").strip() or "8080")

    def pending_for(token: str):
        return hub.pending_by_token(token)

    async def show(request: web.Request) -> web.Response:
        pending = pending_for(request.match_info["token"])
        if pending is None:
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
        pending = pending_for(request.match_info["token"])
        if pending is None or pending.client is None:
            return web.Response(status=404, text="not found")
        form = await request.post()
        value = str(form.get("value", ""))
        client = pending.client
        if pending.step == "password":
            try:
                async with pending.lock:
                    await client.sign_in(password=value)
            except PasswordHashInvalidError:
                return _page("Пароль не подошёл.", "Пароль", 'type="password"')
            except Exception:
                return _page("Пароль не принят. Введите его ещё раз.", "Пароль", 'type="password"')
            await hub.complete(pending, bot)
            return web.Response(text="Вход выполнен. Вернитесь в бота MentionMe.", content_type="text/plain")
        if pending.step != "code" or not pending.code_hash or not pending.phone:
            return _page("Сначала в боте нажмите «Получить код».", "Код", 'inputmode="numeric"')
        if not is_login_code(value):
            return _page("Нужны пять цифр.", "Код", 'inputmode="numeric"')
        try:
            async with pending.lock:
                await client.sign_in(
                    pending.phone,
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
            log.info("Код отклонён: цифры не совпали")
            return _page("Код не подошёл. Проверьте цифры в служебном чате.", "Код", 'inputmode="numeric"')
        except PhoneCodeExpiredError:
            pending.step = None
            pending.code_hash = None
            pending.sent_at = None
            pending.resend_after = None
            log.info("Код отклонён: срок действия истёк")
            return _page("Этот код уже не действует. В боте нажмите «Получить код» ещё раз.", "Код", 'inputmode="numeric"')
        except Exception:
            log.exception("Вход по коду не выполнен")
            return _page("Войти не получилось. Запросите новый код в боте.", "Код", 'inputmode="numeric"')
        await hub.complete(pending, bot)
        return web.Response(text="Вход выполнен. Вернитесь в бота MentionMe.", content_type="text/plain")

    app = web.Application()
    app.router.add_get("/{token}", show)
    app.router.add_post("/{token}", submit)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    return True
