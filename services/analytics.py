import csv
import io
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import Event, PushDelivery, PushMessage, User


async def log_event(
    session: AsyncSession,
    user_id: int,
    event_type: str,
    source: str | None = None,
    meta: str | None = None,
) -> None:
    session.add(
        Event(
            user_id=user_id,
            event_type=event_type,
            source=source,
            meta=meta,
        )
    )


async def get_funnel_stats(session: AsyncSession) -> dict:
    users = (await session.execute(select(User))).scalars().all()
    by_source: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "start": 0,
            "subscribed": 0,
            "lead_magnet": 0,
            "consultation": 0,
        }
    )

    for user in users:
        src = user.source or "direct"
        by_source[src]["start"] += 1
        if user.subscribed_to_channel:
            by_source[src]["subscribed"] += 1
        if user.got_lead_magnet:
            by_source[src]["lead_magnet"] += 1
        if user.consultation_clicked:
            by_source[src]["consultation"] += 1

    push_stats = []
    pushes = (
        await session.execute(
            select(PushMessage).order_by(PushMessage.order_index)
        )
    ).scalars().all()

    for push in pushes:
        delivered = (
            await session.scalar(
                select(func.count(PushDelivery.id)).where(
                    PushDelivery.push_id == push.id
                )
            )
        ) or 0
        clicked = (
            await session.scalar(
                select(func.count(PushDelivery.id)).where(
                    PushDelivery.push_id == push.id,
                    PushDelivery.clicked.is_(True),
                )
            )
        ) or 0
        push_stats.append(
            {
                "id": push.id,
                "order": push.order_index,
                "delivered": delivered,
                "clicked": clicked,
                "enabled": push.enabled,
            }
        )

    return {"by_source": dict(by_source), "pushes": push_stats}


def format_funnel_report(stats: dict) -> str:
    lines = ["<b>📊 Воронка по источникам</b>\n"]
    for source, data in sorted(stats["by_source"].items()):
        lines.append(
            f"<b>{source}</b>\n"
            f"  Старт: {data['start']}\n"
            f"  Подписка: {data['subscribed']}\n"
            f"  Лид-магнит: {data['lead_magnet']}\n"
            f"  Консультация: {data['consultation']}\n"
        )

    lines.append("\n<b>📬 Пуши</b>")
    for push in stats["pushes"]:
        status = "✅" if push["enabled"] else "⏸"
        lines.append(
            f"{status} #{push['order']}: доставлено {push['delivered']}, "
            f"кликов {push['clicked']}"
        )
    return "\n".join(lines)


async def export_users_csv(session: AsyncSession) -> bytes:
    users = (await session.execute(select(User))).scalars().all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "user_id",
            "username",
            "first_name",
            "source",
            "subscribed",
            "lead_magnet",
            "consultation_clicked",
            "created_at",
        ]
    )
    for user in users:
        writer.writerow(
            [
                user.id,
                user.username or "",
                user.first_name or "",
                user.source,
                user.subscribed_to_channel,
                user.got_lead_magnet,
                user.consultation_clicked,
                user.created_at,
            ]
        )
    return output.getvalue().encode("utf-8-sig")
