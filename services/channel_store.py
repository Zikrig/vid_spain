import logging

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import Channel

logger = logging.getLogger(__name__)


async def seed_channels(session: AsyncSession) -> None:
    count = await session.scalar(select(func.count(Channel.id)))
    if count:
        return

    session.add(
        Channel(
            title="Spain Permit",
            username="SpainPermit",
            chat_id=None,
            enabled=True,
        )
    )


async def migrate_channels_schema(session: AsyncSession) -> None:
    conn = await session.connection()
    result = await conn.execute(text("PRAGMA table_info(channels)"))
    columns = {row[1] for row in result.fetchall()}

    if not columns:
        return

    if "username" not in columns:
        await conn.execute(text("ALTER TABLE channels ADD COLUMN username VARCHAR(255)"))
    if "chat_id" not in columns:
        await conn.execute(text("ALTER TABLE channels ADD COLUMN chat_id BIGINT"))
    if "invite_url" not in columns:
        await conn.execute(text("ALTER TABLE channels ADD COLUMN invite_url VARCHAR(512)"))

    if "channel_id" in columns:
        rows = await conn.execute(
            text("SELECT id, channel_id, channel_url FROM channels")
        )
        for row in rows.fetchall():
            row_id, old_id, old_url = row
            username = None
            chat_id = None
            invite_url = None

            old_id = (old_id or "").strip()
            if old_id.startswith("@"):
                username = old_id.lstrip("@")
            elif old_id.lstrip("-").isdigit():
                chat_id = int(old_id)
            elif old_id and not old_id.startswith("http"):
                username = old_id.lstrip("@")

            if old_url and "/+" in old_url:
                invite_url = old_url
            elif old_url and not username:
                from services.channel_utils import parse_channel_input

                try:
                    username, invite_url, chat_id_hint = parse_channel_input(old_url)
                    if chat_id_hint is not None:
                        chat_id = chat_id_hint
                except ValueError:
                    pass

            await conn.execute(
                text(
                    "UPDATE channels SET username = :username, chat_id = :chat_id, "
                    "invite_url = :invite_url WHERE id = :id AND username IS NULL "
                    "AND chat_id IS NULL"
                ),
                {
                    "username": username,
                    "chat_id": chat_id,
                    "invite_url": invite_url,
                    "id": row_id,
                },
            )


async def resolve_unresolved_channels(bot, session: AsyncSession) -> None:
    channels = (
        await session.execute(
            select(Channel).where(Channel.chat_id.is_(None), Channel.username.is_not(None))
        )
    ).scalars().all()

    for channel in channels:
        try:
            chat = await bot.get_chat(f"@{channel.username}")
            channel.chat_id = chat.id
            if chat.username:
                channel.username = chat.username
            logger.info(
                "Resolved channel %s (@%s) -> chat_id=%s",
                channel.title,
                channel.username,
                channel.chat_id,
            )
        except Exception as exc:
            logger.warning(
                "Could not resolve channel %s (@%s): %s",
                channel.title,
                channel.username,
                exc,
            )

    await session.commit()
