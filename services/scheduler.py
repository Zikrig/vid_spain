import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.settings import settings
from services.models import PushDelivery, PushMessage, User

logger = logging.getLogger(__name__)


def _consultation_url(user: User) -> str:
    return settings.consultation_url.format(
        source=user.source or "direct",
        user_id=user.id,
    )


def _resolve_button_url(url_template: str | None, user: User) -> str | None:
    if not url_template:
        return None
    return url_template.replace("{consultation_url}", _consultation_url(user))


class PushScheduler:
    def __init__(self, bot: Bot, session_factory: async_sessionmaker[AsyncSession]):
        self.bot = bot
        self.session_factory = session_factory
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            try:
                await self._process_pending()
            except Exception:
                logger.exception("Push scheduler error")
            await asyncio.sleep(30)

    async def _process_pending(self) -> None:
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            users = (
                await session.execute(
                    select(User).where(
                        User.warmup_started_at.is_not(None),
                        User.warmup_stopped.is_(False),
                    )
                )
            ).scalars().all()

            pushes = (
                await session.execute(
                    select(PushMessage)
                    .where(PushMessage.enabled.is_(True))
                    .order_by(PushMessage.order_index)
                )
            ).scalars().all()

            for user in users:
                if user.warmup_started_at is None:
                    continue
                started = user.warmup_started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)

                for push in pushes:
                    if push.stop_on_consultation_click and user.consultation_clicked:
                        continue

                    due_at = started + timedelta(minutes=push.delay_minutes)
                    if due_at > now:
                        continue

                    existing = await session.scalar(
                        select(PushDelivery.id).where(
                            PushDelivery.user_id == user.id,
                            PushDelivery.push_id == push.id,
                        )
                    )
                    if existing:
                        continue

                    await self._send_push(session, user, push)
                    session.add(
                        PushDelivery(user_id=user.id, push_id=push.id)
                    )
            await session.commit()

    async def _send_push(
        self, session: AsyncSession, user: User, push: PushMessage
    ) -> None:
        builder = InlineKeyboardBuilder()
        if push.button_text:
            builder.row(
                InlineKeyboardButton(
                    text=push.button_text,
                    callback_data=f"push_cta:{push.id}",
                )
            )
        keyboard = builder.as_markup() if push.button_text else None

        try:
            if push.image_file_id:
                await self.bot.send_photo(
                    user.id,
                    push.image_file_id,
                    caption=push.text,
                    reply_markup=keyboard,
                )
            elif push.text:
                await self.bot.send_message(
                    user.id,
                    push.text,
                    reply_markup=keyboard,
                )
        except Exception:
            logger.exception("Failed to send push %s to user %s", push.id, user.id)
