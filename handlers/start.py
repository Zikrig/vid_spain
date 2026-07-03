from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config.settings import settings
from services.channels import add_channel_buttons
from services.content import BTN_GET_GUIDE, START_CAPTION, START_IMAGE
from services.content_store import get_image_file_id, get_text
from services.database import session_factory
from services.users import get_or_create_user, start_warmup

router = Router()


def _parse_source(text: str | None) -> str:
    if not text:
        return "direct"
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return "direct"
    return parts[1].strip()[:255] or "direct"


async def start_keyboard(session) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    btn_get = await get_text(session, BTN_GET_GUIDE)
    builder.row(
        InlineKeyboardButton(text=btn_get, callback_data="get_lead_magnet")
    )
    await add_channel_buttons(session, builder)
    return builder


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    source = _parse_source(message.text)
    async with session_factory() as session:
        user, _ = await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
            source,
        )
        await start_warmup(session, user)
        caption = await get_text(session, START_CAPTION)
        keyboard = (await start_keyboard(session)).as_markup()
        image_file_id = await get_image_file_id(session, START_IMAGE)
        await session.commit()

    if image_file_id:
        await message.answer_photo(
            photo=image_file_id,
            caption=caption,
            reply_markup=keyboard,
        )
    else:
        photo = FSInputFile(settings.start_image_path)
        await message.answer_photo(
            photo=photo,
            caption=caption,
            reply_markup=keyboard,
        )
