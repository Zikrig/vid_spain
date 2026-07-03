from aiogram import Bot
from aiogram.enums import ChatMemberStatus

from services.channels import is_subscribed as _is_subscribed


async def is_subscribed(bot: Bot, session, user_id: int) -> bool:
    return await _is_subscribed(bot, session, user_id)


def is_member_status(status: str) -> bool:
    return status in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    }
