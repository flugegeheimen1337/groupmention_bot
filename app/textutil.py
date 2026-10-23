def utf16_slice(text: str, offset: int, length: int) -> str:
    """Telegram counts entity offsets in UTF-16 code units."""
    if offset < 0 or length < 0:
        return ""
    encoded = text.encode("utf-16-le")
    start = offset * 2
    end = (offset + length) * 2
    if start > len(encoded) or end > len(encoded):
        return ""
    return encoded[start:end].decode("utf-16-le")


def html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
