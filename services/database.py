from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import settings
from services.channel_store import migrate_channels_schema, seed_channels
from services.content import DEFAULT_PUSHES
from services.content_store import seed_content
from services.models import Base, PushMessage

engine = create_async_engine(settings.database_url, echo=False)
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def migrate_drop_campaigns(session: AsyncSession) -> None:
    conn = await session.connection()
    tables = {
        row[0]
        for row in (
            await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        ).fetchall()
    }
    if "push_messages" not in tables:
        return

    columns = {
        row[1]
        for row in (await conn.execute(text("PRAGMA table_info(push_messages)"))).fetchall()
    }
    if "campaign_id" not in columns:
        if "campaigns" in tables:
            await conn.execute(text("DROP TABLE IF EXISTS campaigns"))
        return

    await conn.execute(
        text("DELETE FROM push_messages WHERE campaign_id IS NOT NULL AND campaign_id != 1")
    )
    await conn.execute(
        text(
            """
            CREATE TABLE push_messages_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_index INTEGER DEFAULT 0,
                delay_minutes INTEGER DEFAULT 0,
                text TEXT DEFAULT '',
                image_file_id VARCHAR(512),
                button_text VARCHAR(255),
                button_url VARCHAR(1024),
                enabled BOOLEAN DEFAULT 1,
                stop_on_consultation_click BOOLEAN DEFAULT 1
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            INSERT INTO push_messages_new (
                id, order_index, delay_minutes, text, image_file_id,
                button_text, button_url, enabled, stop_on_consultation_click
            )
            SELECT
                id, order_index, delay_minutes, text, image_file_id,
                button_text, button_url, enabled, stop_on_consultation_click
            FROM push_messages
            WHERE campaign_id = 1 OR campaign_id IS NULL
            """
        )
    )
    await conn.execute(text("DROP TABLE push_messages"))
    await conn.execute(text("ALTER TABLE push_messages_new RENAME TO push_messages"))
    await conn.execute(text("DROP TABLE IF EXISTS campaigns"))


async def init_db() -> None:
    db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
    if db_path.startswith("/"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    elif not db_path.startswith("postgresql"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await migrate_channels_schema(session)
        await migrate_drop_campaigns(session)
        await session.commit()

    async with session_factory() as session:
        push_count = await session.scalar(select(func.count(PushMessage.id)))
        if not push_count:
            for push_data in DEFAULT_PUSHES:
                session.add(PushMessage(**push_data))

        await seed_content(session)
        await seed_channels(session)
        await session.commit()
