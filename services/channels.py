from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.channel_utils import channel_api_target, channel_matches_chat, channel_public_url
from services.content import BTN_CHECK_SUB, BTN_SUBSCRIBE
from services.content_store import get_text
from services.models import Channel

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


async def is_member_of_channel(bot: Bot, channel: Channel, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(channel_api_target(channel), user_id)
    except Exception:
        return False
    return member.status in _MEMBER_STATUSES


async def is_subscribed(bot: Bot, session: AsyncSession, user_id: int) -> bool:
    channels = await get_enabled_channels(session)
    if not channels:
        return False
    for channel in channels:
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
