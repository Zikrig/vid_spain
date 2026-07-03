from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from handlers.admin import is_admin
from services.channel_resolve import apply_channel_input, resolve_channel
from services.channel_utils import format_channel_info
from services.database import session_factory
from services.models import Channel

router = Router()


class ChannelAdminStates(StatesGroup):
    add_title = State()
    add_reference = State()
    edit_title = State()
    edit_reference = State()


def channels_list_keyboard(channels: list[Channel]):
    builder = InlineKeyboardBuilder()
    for channel in channels:
        status = "✅" if channel.enabled else "⏸"
        builder.row(
            InlineKeyboardButton(
                text=f"{status} {channel.title}",
                callback_data=f"admin:channel:{channel.id}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="➕ Добавить", callback_data="admin:channel_add")
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin:menu"))
    return builder.as_markup()


def channel_detail_keyboard(channel_id: int, enabled: bool):
    builder = InlineKeyboardBuilder()
    toggle = "⏸ Выключить" if enabled else "✅ Включить"
    builder.row(
        InlineKeyboardButton(
            text=toggle, callback_data=f"admin:channel_toggle:{channel_id}"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="✏️ Название", callback_data=f"admin:channel_edit_title:{channel_id}"
        ),
        InlineKeyboardButton(
            text="📢 Канал",
            callback_data=f"admin:channel_edit_ref:{channel_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🗑 Удалить", callback_data=f"admin:channel_delete:{channel_id}"
        )
    )
    builder.row(
        InlineKeyboardButton(text="◀️ К списку", callback_data="admin:channels")
    )
    return builder.as_markup()


@router.callback_query(F.data == "admin:channels")
async def admin_channels_list(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    async with session_factory() as session:
        channels = (
            await session.execute(select(Channel).order_by(Channel.id))
        ).scalars().all()

    text = "<b>📢 Каналы</b>\n\n"
    if channels:
        text += (
            "Выберите канал или добавьте новый.\n"
            "Проверка подписки — по любому <b>включённому</b> каналу.\n"
            "Ссылка t.me формируется автоматически из @username."
        )
    else:
        text += "Каналов пока нет. Добавьте хотя бы один."

    await callback.message.edit_text(
        text, reply_markup=channels_list_keyboard(list(channels))
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^admin:channel:\d+$"))
async def admin_channel_detail(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    channel_id = int(callback.data.split(":")[2])
    async with session_factory() as session:
        channel = await session.get(Channel, channel_id)

    if channel is None:
        await callback.answer("Канал не найден", show_alert=True)
        return

    await callback.message.edit_text(
        format_channel_info(channel),
        reply_markup=channel_detail_keyboard(channel.id, channel.enabled),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:channel_toggle:"))
async def admin_channel_toggle(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    channel_id = int(callback.data.split(":")[2])
    async with session_factory() as session:
        channel = await session.get(Channel, channel_id)
        if channel is None:
            await callback.answer("Не найден", show_alert=True)
            return
        channel.enabled = not channel.enabled
        enabled = channel.enabled
        info = format_channel_info(channel)
        await session.commit()

    await callback.answer("Обновлено")
    await callback.message.edit_text(
        info,
        reply_markup=channel_detail_keyboard(channel_id, enabled),
    )


@router.callback_query(F.data.startswith("admin:channel_delete:"))
async def admin_channel_delete(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    channel_id = int(callback.data.split(":")[2])
    async with session_factory() as session:
        channel = await session.get(Channel, channel_id)
        if channel is None:
            await callback.answer("Не найден", show_alert=True)
            return
        await session.delete(channel)
        await session.commit()

    await callback.answer("Канал удалён")
    await admin_channels_list(callback)


@router.callback_query(F.data == "admin:channel_add")
async def admin_channel_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(ChannelAdminStates.add_title)
    await callback.message.answer(
        "Введите название для кнопки, например: Spain Permit"
    )
    await callback.answer()


@router.message(ChannelAdminStates.add_title)
async def admin_channel_add_title(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    title = (message.text or "").strip()[:255]
    if not title:
        await message.answer("Название не может быть пустым.")
        return

    await state.update_data(title=title)
    await state.set_state(ChannelAdminStates.add_reference)
    await message.answer(
        "Отправьте канал одним сообщением:\n"
        "• @SpainPermit\n"
        "• https://t.me/SpainPermit\n"
        "• или числовой ID (-100...)\n\n"
        "Бот сохранит @username и chat ID, ссылку сформирует сам."
    )


@router.message(ChannelAdminStates.add_reference)
async def admin_channel_add_reference(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    raw = message.text or ""
    try:
        channel = await resolve_channel(bot, raw, fallback_title=data["title"])
    except ValueError as exc:
        await message.answer(f"❌ {exc}")
        return
    except Exception:
        await message.answer(
            "❌ Не удалось получить канал. Проверьте, что бот — админ канала, "
            "и вы отправили @username или ссылку t.me/..."
        )
        return

    async with session_factory() as session:
        session.add(channel)
        await session.commit()

    await state.clear()
    await message.answer(
        f"Канал «{channel.title}» добавлен ✅\n\n{format_channel_info(channel)}"
    )


@router.callback_query(F.data.startswith("admin:channel_edit_title:"))
async def admin_channel_edit_title_start(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    channel_id = int(callback.data.split(":")[2])
    await state.set_state(ChannelAdminStates.edit_title)
    await state.update_data(channel_id=channel_id)
    await callback.message.answer("Введите новое название для кнопки:")
    await callback.answer()


@router.message(ChannelAdminStates.edit_title)
async def admin_channel_edit_title_save(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    title = (message.text or "").strip()[:255]
    if not title:
        await message.answer("Название не может быть пустым.")
        return

    data = await state.get_data()
    async with session_factory() as session:
        channel = await session.get(Channel, data["channel_id"])
        if channel:
            channel.title = title
            await session.commit()

    await state.clear()
    await message.answer("Название сохранено ✅")


@router.callback_query(F.data.startswith("admin:channel_edit_ref:"))
async def admin_channel_edit_ref_start(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    channel_id = int(callback.data.split(":")[2])
    await state.set_state(ChannelAdminStates.edit_reference)
    await state.update_data(channel_id=channel_id)
    await callback.message.answer(
        "Отправьте @username, ссылку t.me/... или числовой ID канала:"
    )
    await callback.answer()


@router.message(ChannelAdminStates.edit_reference)
async def admin_channel_edit_ref_save(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    raw = message.text or ""

    async with session_factory() as session:
        channel = await session.get(Channel, data["channel_id"])
        if channel is None:
            await message.answer("Канал не найден.")
            await state.clear()
            return
        try:
            await apply_channel_input(bot, channel, raw)
            await session.commit()
        except ValueError as exc:
            await message.answer(f"❌ {exc}")
            return
        except Exception:
            await message.answer(
                "❌ Не удалось обновить канал. Проверьте доступ бота к каналу."
            )
            return
        info = format_channel_info(channel)

    await state.clear()
    await message.answer(f"Канал обновлён ✅\n\n{info}")
