from app.textutil import utf16_slice

_MENTION_NAME = {"MessageEntityMentionName", "InputMessageEntityMentionName"}


def is_group_chat(chat: object) -> bool:
    """Ordinary groups and supergroups. Private chats and broadcast channels are out."""
    if getattr(chat, "megagroup", False):
        return True
    if getattr(chat, "broadcast", False):
        return False
    return getattr(chat, "title", None) is not None and getattr(chat, "first_name", None) is None


def is_explicit_mention(
    text: str | None,
    entities,
    me_id: int,
    me_username: str | None,
    outgoing: bool,
) -> bool:
    if outgoing or not entities:
        return False
    body = text or ""
    username = (me_username or "").casefold()
    for entity in entities:
        kind = type(entity).__name__
        if kind == "MessageEntityMention" and username:
            fragment = utf16_slice(body, entity.offset, entity.length).casefold()
            if fragment == f"@{username}":
                return True
        elif kind in _MENTION_NAME and getattr(entity, "user_id", None) == me_id:
            return True
    return False
