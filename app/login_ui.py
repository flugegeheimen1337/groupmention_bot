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
