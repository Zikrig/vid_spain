from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import settings
from services.channel_store import migrate_channels_schema, resolve_unresolved_channels, seed_channels
from services.content_store import seed_content
from services.models import Base, Campaign, PushMessage
from services.content import DEFAULT_PUSHES

engine = create_async_engine(settings.database_url, echo=False)
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


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
        await session.commit()

    async with session_factory() as session:
        campaign = await session.get(Campaign, 1)
        if campaign is None:
            campaign = Campaign(id=1, name="Основная", is_active=True)
            session.add(campaign)
            for push_data in DEFAULT_PUSHES:
                session.add(PushMessage(campaign_id=1, **push_data))

        await seed_content(session)
        await seed_channels(session)
        await session.commit()
