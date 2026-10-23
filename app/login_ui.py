def describe_code_delivery(type_name: str) -> str:
    if type_name == "SentCodeTypeApp":
        return (
            "Это не SMS. Код уже внутри Telegram.\n"
            "1. Выйдите из чата с ботом в общий список чатов. Приложение не закрывайте.\n"
            "2. Сверху может всплыть «Код для входа».\n"
            "3. Если его нет, в поиске наберите Telegram и откройте служебный чат с синей галочкой. "
            "Загляните и в архив: чат мог спрятаться туда.\n"
            "4. Пять цифр — в последнем сообщении этого чата."
        )
    if type_name in {"SentCodeTypeSms", "SentCodeTypeFirebaseSms"}:
        return "Telegram отправил код в SMS на этот номер."
    if type_name == "SentCodeTypeCall":
        return "Telegram позвонит и продиктует код."
    if type_name in {"SentCodeTypeFlashCall", "SentCodeTypeMissedCall"}:
        return "Telegram сделает звонок. Код — последние цифры номера, с которого звонят."
    if type_name == "SentCodeTypeEmailCode":
        return "Код отправлен на почту, привязанную к аккаунту Telegram."
    if type_name == "SentCodeTypeFragmentSms":
        return "Код отправлен SMS через Fragment."
    if type_name in {"SentCodeTypeSmsWord", "SentCodeTypeSmsPhrase"}:
        return "В SMS придёт слово или фраза. Введите их на странице целиком."
    if type_name == "SentCodeTypeSetUpEmailRequired":
        return (
            "Telegram не отправил код: в приложении сначала нужно привязать почту "
            "в настройках аккаунта, затем нажать «Получить код» ещё раз."
        )
    return "Откройте служебный чат «Telegram» в приложении и проверьте SMS на этот номер."


def code_was_sent(type_name: str) -> bool:
    return type_name != "SentCodeTypeSetUpEmailRequired"


def mask_phone(phone: str) -> str:
    if len(phone) < 6:
        return phone
    return f"{phone[:4]}***{phone[-2:]}"


def normalize_login_code(text: str) -> str:
    return "".join(text.split())


def is_login_code(text: str) -> bool:
    code = normalize_login_code(text)
    return len(code) == 5 and code.isdigit()


def user_can_connect(
    user_id: int | None,
    username: str | None,
    owner_id: int | None,
    expected_username: str | None,
) -> bool:
    if user_id is None:
        return False
    if owner_id is not None and user_id == owner_id:
        return True
    if not expected_username or not username:
        return False
    return username.casefold() == expected_username.casefold()
