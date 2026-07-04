from aiogram import Bot, F, Router
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.analytics import log_event
from services.channels import find_channel_by_chat, is_subscribed, subscribe_keyboard
from services.content import (
    CTA_REDIRECT,
    LEAD_MAGNET,
    LEAD_MAGNET_VIDEO,
    NOT_SUBSCRIBED,
    SUB_CHECK_FAIL,
    SUB_CHECK_OK,
)
from services.content_store import get_text
from services.database import session_factory
from services.models import PushMessage, User
from services.scheduler import _consultation_url, _resolve_button_url
from services.subscription import is_member_status
from services.users import (
    mark_consultation_click,
    mark_lead_magnet,
    mark_subscribed,
)

router = Router()


async def _deliver_lead_magnet(message: Message, session) -> None:
    text = await get_text(session, LEAD_MAGNET)
    await message.answer(text)
    video_url = (await get_text(session, LEAD_MAGNET_VIDEO)).strip()
    if video_url:
        await message.answer(f"🎬 Видео-гайд: {video_url}")


@router.callback_query(F.data == "get_lead_magnet")
async def get_lead_magnet(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    user_id = callback.from_user.id

    async with session_factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            await callback.message.answer("Нажмите /start для начала.")
            return

        if user.got_lead_magnet:
            await _deliver_lead_magnet(callback.message, session)
            await session.commit()
            return

        subscribed = await is_subscribed(bot, session, user_id)
        if subscribed:
            await mark_subscribed(session, user)
            await mark_lead_magnet(session, user)
            await session.commit()
            await _deliver_lead_magnet(callback.message, session)
            return

        not_sub_text = await get_text(session, NOT_SUBSCRIBED)
        keyboard = await subscribe_keyboard(session)
        await session.commit()

    await callback.message.answer(not_sub_text, reply_markup=keyboard)


@router.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery, bot: Bot) -> None:
    user_id = callback.from_user.id

    async with session_factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            await callback.answer("Нажмите /start", show_alert=True)
            return

        fail_msg = await get_text(session, SUB_CHECK_FAIL)
        ok_msg = await get_text(session, SUB_CHECK_OK)

        subscribed = await is_subscribed(bot, session, user_id)
        if not subscribed:
            await callback.answer(fail_msg, show_alert=True)
            return

        await mark_subscribed(session, user)
        if not user.got_lead_magnet:
            await mark_lead_magnet(session, user)
        await session.commit()

    await callback.answer(ok_msg)
    async with session_factory() as session:
        await _deliver_lead_magnet(callback.message, session)


@router.callback_query(F.data.startswith("push_cta:"))
async def push_cta_click(callback: CallbackQuery) -> None:
    push_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    async with session_factory() as session:
        user = await session.get(User, user_id)
        push = await session.get(PushMessage, push_id)
        if user is None or push is None:
            await callback.answer("Ошибка", show_alert=True)
            return

        await mark_consultation_click(session, user, push_id=push_id)
        url = _resolve_button_url(push.button_url, user) or _consultation_url(user)
        redirect_text = await get_text(session, CTA_REDIRECT)
        await session.commit()

    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=push.button_text or "Записаться", url=url))
    await callback.message.answer(
        redirect_text,
        reply_markup=builder.as_markup(),
    )


@router.chat_member()
async def on_chat_member_update(event: ChatMemberUpdated, bot: Bot) -> None:
    async with session_factory() as session:
        channel = await find_channel_by_chat(
            session, event.chat.id, event.chat.username
        )
        if channel is None or not channel.enabled:
            return

        user_id = event.new_chat_member.user.id
        new_status = event.new_chat_member.status
        old_status = event.old_chat_member.status

        was_subscribed = is_member_status(old_status)
        is_now_subscribed = is_member_status(new_status)

        if was_subscribed and not is_now_subscribed:
            user = await session.get(User, user_id)
            if user:
                still_subscribed = await is_subscribed(bot, session, user_id)
                if not still_subscribed:
                    user.subscribed_to_channel = False
                    await log_event(
                        session,
                        user_id,
                        "unsubscribed",
                        source=user.source,
                        meta=f"channel_id={channel.id}",
                    )
        elif not was_subscribed and is_now_subscribed:
            user = await session.get(User, user_id)
            if user:
                await mark_subscribed(session, user)

        await session.commit()
