import re
from urllib.parse import urlparse

from services.models import Channel

_TME_USER_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)/?", re.I)
_TME_INVITE_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(\+[\w-]+)", re.I)


def parse_channel_input(raw: str) -> tuple[str | None, str | None, int | None]:
    """Parse @username, t.me link, or numeric id.

    Returns (username without @, invite_url, numeric chat_id hint).
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("Пустой ввод")

    invite = _TME_INVITE_RE.search(text)
    if invite:
        url = text if text.startswith("http") else f"https://t.me/{invite.group(1)}"
        return None, url, None

    if text.startswith("http"):
        match = _TME_USER_RE.search(text)
        if not match:
            raise ValueError("Не удалось распознать ссылку на канал")
        return match.group(1), None, None

    if text.lstrip("-").isdigit():
        return None, None, int(text)

    username = text.lstrip("@")
    if not username:
        raise ValueError("Укажите @username, ссылку t.me/... или числовой ID")
    return username, None, None


def channel_api_target(channel: Channel) -> str | int:
    if channel.chat_id is not None:
        return channel.chat_id
    if channel.username:
        return f"@{channel.username}"
    if channel.invite_url:
        return channel.invite_url
    raise ValueError(f"Channel {channel.id} has no identifier")


def channel_public_url(channel: Channel) -> str | None:
    if channel.username:
        return f"https://t.me/{channel.username}"
    return channel.invite_url


def channel_matches_chat(
    channel: Channel, chat_id: int, chat_username: str | None
) -> bool:
    if channel.chat_id is not None and chat_id == channel.chat_id:
        return True
    if channel.username and chat_username:
        return channel.username.lower() == chat_username.lower()
    return False


def format_channel_info(channel: Channel) -> str:
    status = "включён" if channel.enabled else "выключен"
    username = f"@{channel.username}" if channel.username else "—"
    chat_id = str(channel.chat_id) if channel.chat_id is not None else "—"
    url = channel_public_url(channel) or "—"
    return (
        f"<b>{channel.title}</b> ({status})\n\n"
        f"Ник: <code>{username}</code>\n"
        f"ID: <code>{chat_id}</code>\n"
        f"Ссылка: {url}"
    )
