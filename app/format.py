from app.textutil import html_escape

_MAX_BODY = 3500


def sender_label(sender: object | None, post_author: str | None = None) -> str:
    if sender is None:
        return post_author or "Неизвестный отправитель"
    title = getattr(sender, "title", None)
    if title and getattr(sender, "first_name", None) is None:
        if post_author:
            return f"{title} ({post_author})"
        return title
    first = getattr(sender, "first_name", None) or ""
    last = getattr(sender, "last_name", None) or ""
    name = " ".join(part for part in (first, last) if part) or "Без имени"
    username = getattr(sender, "username", None)
    if username:
        return f"{name} (@{username})"
    return name


def with_read_status(body: str, read: bool) -> str:
    label = "Прочитано" if read else "Не прочитано"
    return f"Статус: {label}\n{body}"


def notification_html(chat_title: str, sender: str, text: str | None) -> str:
    body = (text or "").strip() or "Сообщение без текста"
    escaped = html_escape(body)
    if len(escaped) > _MAX_BODY:
        escaped = escaped[:_MAX_BODY].rstrip() + "…"
    return (
        f"Название группы: {html_escape(chat_title or 'Группа')}\n"
        f"Отправитель: {html_escape(sender)}\n\n"
        f"Текст сообщения:\n{escaped}"
    )
