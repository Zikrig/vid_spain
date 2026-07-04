from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.content import DEFAULT_CONTENT, LEAD_MAGNET
from services.models import BotContent

LEAD_MAGNET_LINK = "https://spainpermit.com/#diagnostic"
LEAD_MAGNET_LINK_SUFFIX = (
    f'\n\n👉 <a href="{LEAD_MAGNET_LINK}">Записаться на бесплатную диагностику</a>'
)


async def get_text(session: AsyncSession, key: str, default: str = "") -> str:
    row = await session.get(BotContent, key)
    if row is None or not row.text:
        return DEFAULT_CONTENT.get(key, default)
    return row.text


async def get_image_file_id(session: AsyncSession, key: str) -> str | None:
    row = await session.get(BotContent, key)
    if row is None:
        return None
    return row.image_file_id


async def set_text(session: AsyncSession, key: str, text: str) -> None:
    row = await session.get(BotContent, key)
    if row is None:
        row = BotContent(key=key, text=text)
        session.add(row)
    else:
        row.text = text


async def set_image_file_id(
    session: AsyncSession, key: str, file_id: str | None
) -> None:
    row = await session.get(BotContent, key)
    if row is None:
        row = BotContent(key=key, text="", image_file_id=file_id)
        session.add(row)
    else:
        row.image_file_id = file_id


async def seed_content(session: AsyncSession) -> None:
    existing = (
        await session.execute(select(BotContent.key))
    ).scalars().all()
    existing_keys = set(existing)

    for key, text in DEFAULT_CONTENT.items():
        if key not in existing_keys:
            session.add(BotContent(key=key, text=text))

    row = await session.get(BotContent, LEAD_MAGNET)
    if row and LEAD_MAGNET_LINK not in row.text:
        row.text = row.text.rstrip() + LEAD_MAGNET_LINK_SUFFIX
