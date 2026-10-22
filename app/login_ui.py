def mask_phone(phone: str) -> str:
    if len(phone) < 6:
        return phone
    return f"{phone[:4]}***{phone[-2:]}"


def normalize_login_code(text: str) -> str:
    return "".join(text.split())


def is_login_code(text: str) -> bool:
    code = normalize_login_code(text)
    return len(code) == 5 and code.isdigit()
