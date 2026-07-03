import logging

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.channel_utils import (
    channel_matches_chat,
    channel_member_check_target,
    channel_public_url,
)
from services.content import BTN_CHECK_SUB, BTN_SUBSCRIBE
from services.content_store import get_text
from services.models import Channel

logger = logging.getLogger(__name__)

_MEMBER_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.CREATOR,
}


async def get_all_channels(session: AsyncSession) -> list[Channel]:
    result = await session.execute(select(Channel).order_by(Channel.id))
    return list(result.scalars().all())


async def get_enabled_channels(session: AsyncSession) -> list[Channel]:
    result = await session.execute(
        select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id)
    )
    return list(result.scalars().all())


async def find_channel_by_chat(
    session: AsyncSession, chat_id: int, chat_username: str | None
) -> Channel | None:
    channels = await get_all_channels(session)
    for channel in channels:
        if channel_matches_chat(channel, chat_id, chat_username):
            return channel
    return None


async def ensure_channel_resolved(
    bot: Bot, session: AsyncSession, channel: Channel
) -> None:
    if channel.chat_id is not None or not channel.username:
        return
    try:
        chat = await bot.get_chat(f"@{channel.username}")
        channel.chat_id = chat.id
        if chat.username:
            channel.username = chat.username
        await session.flush()
    except Exception as exc:
        logger.warning(
            "Could not resolve chat_id for channel %s (@%s): %s",
            channel.id,
            channel.username,
            exc,
        )


async def is_member_of_channel(bot: Bot, channel: Channel, user_id: int) -> bool:
    target = channel_member_check_target(channel)
    if target is None:
        logger.error(
            "Channel %s (%s) has no chat_id/username — cannot check subscription",
            channel.id,
            channel.title,
        )
        return False

    try:
        member = await bot.get_chat_member(target, user_id)
    except TelegramForbiddenError as exc:
        logger.error(
            "Bot is not admin in channel %s (%s): %s",
            channel.id,
            channel.title,
            exc,
        )
        return False
    except TelegramBadRequest as exc:
        error = str(exc).lower()
        if any(
            phrase in error
            for phrase in (
                "user not found",
                "not a member",
                "participate",
                "member not found",
            )
        ):
            return False
        logger.warning(
            "get_chat_member failed for channel %s (%s): %s",
            channel.id,
            channel.title,
            exc,
        )
        return False
    except Exception as exc:
        logger.warning(
            "get_chat_member failed for channel %s (%s): %s",
            channel.id,
            channel.title,
            exc,
        )
        return False

    return member.status in _MEMBER_STATUSES


async def is_subscribed(bot: Bot, session: AsyncSession, user_id: int) -> bool:
    channels = await get_enabled_channels(session)
    if not channels:
        logger.error("No enabled channels configured — subscription check always fails")
        return False

    for channel in channels:
        await ensure_channel_resolved(bot, session, channel)
        if await is_member_of_channel(bot, channel, user_id):
            return True
    return False


async def add_channel_buttons(
    session: AsyncSession, builder: InlineKeyboardBuilder
) -> None:
    channels = await get_enabled_channels(session)
    btn_sub = await get_text(session, BTN_SUBSCRIBE)

    if not channels:
        return

    if len(channels) == 1:
        url = channel_public_url(channels[0])
        if url:
            builder.row(InlineKeyboardButton(text=btn_sub, url=url))
        return

    for channel in channels:
        url = channel_public_url(channel)
        if url:
            builder.row(
                InlineKeyboardButton(
                    text=f"📢 {channel.title}",
                    url=url,
                )
            )


async def subscribe_keyboard(session: AsyncSession):
    builder = InlineKeyboardBuilder()
    await add_channel_buttons(session, builder)
    btn_check = await get_text(session, BTN_CHECK_SUB)
    builder.row(
        InlineKeyboardButton(
            text=btn_check,
            callback_data="check_subscription",
        )
    )
    return builder.as_markup()
