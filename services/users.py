from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.analytics import log_event
from services.models import PushDelivery, User


async def get_or_create_user(
    session: AsyncSession,
    user_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    source: str,
) -> tuple[User, bool]:
    user = await session.get(User, user_id)
    is_new = user is None
    if user is None:
        user = User(
            id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            source=source,
        )
        session.add(user)
        await log_event(session, user_id, "start", source=source)
    else:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
    return user, is_new


async def start_warmup(session: AsyncSession, user: User) -> None:
    if user.warmup_started_at is None:
        user.warmup_started_at = datetime.now(timezone.utc)
        await log_event(session, user.id, "warmup_started", source=user.source)


async def mark_subscribed(session: AsyncSession, user: User) -> None:
    if not user.subscribed_to_channel:
        user.subscribed_to_channel = True
        await log_event(session, user.id, "subscribed", source=user.source)


async def mark_lead_magnet(session: AsyncSession, user: User) -> None:
    if not user.got_lead_magnet:
        user.got_lead_magnet = True
        await log_event(session, user.id, "lead_magnet", source=user.source)


async def mark_consultation_click(
    session: AsyncSession, user: User, push_id: int | None = None
) -> None:
    user.consultation_clicked = True
    meta = f"push_id={push_id}" if push_id else None
    await log_event(
        session, user.id, "consultation_click", source=user.source, meta=meta
    )

    if push_id:
        from services.models import PushMessage

        delivery = await session.scalar(
            select(PushDelivery).where(
                PushDelivery.user_id == user.id,
                PushDelivery.push_id == push_id,
            )
        )
        if delivery:
            delivery.clicked = True

        push = await session.get(PushMessage, push_id)
        if push and push.stop_on_consultation_click:
            user.warmup_stopped = True


async def reset_user_warmup(session: AsyncSession, user: User) -> None:
    user.warmup_started_at = datetime.now(timezone.utc)
    user.warmup_stopped = False
    user.consultation_clicked = False
    await session.execute(
        delete(PushDelivery).where(PushDelivery.user_id == user.id)
    )
    await log_event(session, user.id, "warmup_reset", source=user.source)


async def reset_all_warmups(session: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    await session.execute(delete(PushDelivery))
    users = (await session.execute(select(User))).scalars().all()
    count = 0
    for user in users:
        if user.warmup_started_at is None:
            continue
        user.warmup_started_at = now
        user.warmup_stopped = False
        user.consultation_clicked = False
        count += 1
    return count
