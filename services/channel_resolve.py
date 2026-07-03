from aiogram import Bot
from aiogram.types import Message

from services.channel_utils import parse_channel_input
from services.models import Channel


def message_html(message: Message) -> str:
    """Preserve Telegram formatting as HTML for ParseMode.HTML."""
    if message.html_text is not None:
        return message.html_text
    return message.text or ""


async def resolve_channel(
    bot: Bot, raw: str, *, fallback_title: str | None = None
) -> Channel:
    username, invite_url, chat_id_hint = parse_channel_input(raw)

    chat = None
    if chat_id_hint is not None:
        chat = await bot.get_chat(chat_id_hint)
    elif username:
        chat = await bot.get_chat(f"@{username}")
    elif invite_url:
        chat = await bot.get_chat(invite_url)

    if chat is None:
        raise ValueError("Не удалось определить канал")

    resolved_username = chat.username
    title = fallback_title or (resolved_username or str(chat.id))

    return Channel(
        title=title[:255],
        username=resolved_username,
        chat_id=chat.id,
        invite_url=invite_url if not resolved_username else None,
        enabled=True,
    )


async def apply_channel_input(bot: Bot, channel: Channel, raw: str) -> None:
    username, invite_url, chat_id_hint = parse_channel_input(raw)

    chat = None
    if chat_id_hint is not None:
        chat = await bot.get_chat(chat_id_hint)
    elif username:
        chat = await bot.get_chat(f"@{username}")
    elif invite_url:
        chat = await bot.get_chat(invite_url)

    if chat is None:
        raise ValueError("Не удалось определить канал")

    channel.username = chat.username
    channel.chat_id = chat.id
    channel.invite_url = invite_url if not chat.username else None
