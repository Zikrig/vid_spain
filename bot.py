import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config.settings import settings
from handlers import router
from services.channel_store import resolve_unresolved_channels
from services.database import init_db, session_factory
from services.scheduler import PushScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    async with session_factory() as session:
        await resolve_unresolved_channels(bot, session)

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    scheduler = PushScheduler(bot, session_factory)
    scheduler.start()

    try:
        logger.info("Bot started")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await scheduler.stop()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
