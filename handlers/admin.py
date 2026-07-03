from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete, select

from config.settings import settings
from services.analytics import export_users_csv, format_funnel_report, get_funnel_stats
from services.content import CONTENT_IMAGE_KEY, CONTENT_LABELS, START_CAPTION, START_IMAGE
from services.channel_resolve import message_html
from services.content_store import get_text, set_image_file_id, set_text
from services.database import session_factory
from services.models import Campaign, PushDelivery, PushMessage

router = Router()


class AdminStates(StatesGroup):
    edit_text = State()
    edit_delay = State()
    edit_button_text = State()
    edit_button_url = State()
    edit_image = State()
    edit_content_text = State()
    edit_content_image = State()
    duplicate_campaign = State()


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


def admin_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📝 Тексты", callback_data="admin:texts"),
        InlineKeyboardButton(text="📬 Пуши", callback_data="admin:pushes"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Аналитика", callback_data="admin:stats"),
        InlineKeyboardButton(text="📥 Экспорт CSV", callback_data="admin:export"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Кампании", callback_data="admin:campaigns"),
        InlineKeyboardButton(text="📢 Каналы", callback_data="admin:channels"),
    )
    return builder.as_markup()


def pushes_list_keyboard(pushes: list[PushMessage]):
    builder = InlineKeyboardBuilder()
    for push in pushes:
        status = "✅" if push.enabled else "⏸"
        builder.row(
            InlineKeyboardButton(
                text=f"{status} #{push.order_index} — {push.delay_minutes} мин",
                callback_data=f"admin:push:{push.id}",
            )
        )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin:menu"))
    return builder.as_markup()


def push_edit_keyboard(push_id: int, enabled: bool):
    builder = InlineKeyboardBuilder()
    toggle_text = "⏸ Отключить" if enabled else "✅ Включить"
    builder.row(
        InlineKeyboardButton(
            text=toggle_text, callback_data=f"admin:toggle:{push_id}"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="✏️ Текст", callback_data=f"admin:edit_text:{push_id}"
        ),
        InlineKeyboardButton(
            text="🖼 Картинка", callback_data=f"admin:edit_image:{push_id}"
        ),
        InlineKeyboardButton(
            text="🗑 Удалить", callback_data=f"admin:push_delete:{push_id}"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="⏱ Тайминг", callback_data=f"admin:edit_delay:{push_id}"
        ),
        InlineKeyboardButton(
            text="🔘 Кнопка", callback_data=f"admin:edit_btn:{push_id}"
        ),
        InlineKeyboardButton(
            text="🔗 Ссылка", callback_data=f"admin:edit_url:{push_id}"
        ),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ К списку", callback_data="admin:pushes")
    )
    return builder.as_markup()


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "<b>🛠 Админ-панель</b>\n\nУправление контентом и аналитикой бота.",
        reply_markup=admin_main_keyboard(),
    )


@router.callback_query(F.data == "admin:menu")
async def admin_menu(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        "<b>🛠 Админ-панель</b>",
        reply_markup=admin_main_keyboard(),
    )
    await callback.answer()


def texts_list_keyboard():
    builder = InlineKeyboardBuilder()
    for key, label in CONTENT_LABELS.items():
        if key == START_IMAGE:
            continue
        builder.row(
            InlineKeyboardButton(
                text=label,
                callback_data=f"admin:content:{key}",
            )
        )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin:menu"))
    return builder.as_markup()


def content_edit_keyboard(content_key: str):
    builder = InlineKeyboardBuilder()
    image_key = CONTENT_IMAGE_KEY.get(content_key)
    if image_key:
        builder.row(
            InlineKeyboardButton(
                text="✏️ Текст",
                callback_data=f"admin:content_edit:{content_key}",
            ),
            InlineKeyboardButton(
                text="🖼 Картинка",
                callback_data=f"admin:content_img:{image_key}",
            ),
            InlineKeyboardButton(
                text="🗑 Удалить",
                callback_data=f"admin:content_img_reset:{image_key}",
            ),
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="✏️ Текст",
                callback_data=f"admin:content_edit:{content_key}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="◀️ К списку", callback_data="admin:texts")
    )
    return builder.as_markup()


async def format_content_detail(session, content_key: str) -> str:
    label = CONTENT_LABELS.get(content_key, content_key)
    image_key = CONTENT_IMAGE_KEY.get(content_key)

    if image_key:
        from services.content_store import get_image_file_id

        text = await get_text(session, content_key)
        text_preview = text[:300] + ("..." if len(text) > 300 else "")
        file_id = await get_image_file_id(session, image_key)
        img_status = (
            "загружена в Telegram ✅"
            if file_id
            else "файл по умолчанию (assets/)"
        )
        return (
            f"<b>{label}</b>\n\n"
            f"{text_preview}\n\n"
            f"🖼 Картинка: {img_status}"
        )

    text = await get_text(session, content_key)
    preview = text[:300] + ("..." if len(text) > 300 else "")
    return f"<b>{label}</b>\n\n{preview}"


def format_push_detail(push: PushMessage) -> str:
    preview = push.text[:200] + ("..." if len(push.text) > 200 else "")
    image_status = "есть ✅" if push.image_file_id else "нет"
    return (
        f"<b>Пуш #{push.order_index}</b>\n"
        f"Тайминг: {push.delay_minutes} мин от входа в бота\n"
        f"Кнопка: {push.button_text or '—'}\n"
        f"Ссылка: {push.button_url or '—'}\n"
        f"Картинка: {image_status}\n"
        f"Стоп при клике: {'да' if push.stop_on_consultation_click else 'нет'}\n\n"
        f"{preview}"
    )


@router.callback_query(F.data == "admin:texts")
async def admin_texts(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        "<b>📝 Тексты бота</b>\n\nВыберите блок для редактирования:",
        reply_markup=texts_list_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:content:"))
async def admin_content_detail(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    content_key = callback.data.split(":", 2)[2]
    if content_key == START_IMAGE:
        content_key = START_CAPTION

    async with session_factory() as session:
        text = await format_content_detail(session, content_key)

    await callback.message.edit_text(
        text,
        reply_markup=content_edit_keyboard(content_key),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:content_edit:"))
async def admin_content_edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    content_key = callback.data.split(":", 2)[2]
    label = CONTENT_LABELS.get(content_key, content_key)
    await state.set_state(AdminStates.edit_content_text)
    await state.update_data(content_key=content_key)
    await callback.message.answer(
        f"Отправьте новый текст для «{label}».\n"
        "Можно использовать форматирование Telegram (жирный, курсив) — "
        "оно сохранится как HTML."
    )
    await callback.answer()


@router.message(AdminStates.edit_content_text)
async def admin_content_edit_save(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    content_key = data["content_key"]

    async with session_factory() as session:
        await set_text(session, content_key, message_html(message))
        await session.commit()

    await state.clear()
    await message.answer(
        "Текст сохранён ✅",
        reply_markup=InlineKeyboardBuilder()
        .row(
            InlineKeyboardButton(
                text="◀️ К посту",
                callback_data=f"admin:content:{content_key}",
            )
        )
        .as_markup(),
    )


@router.callback_query(F.data.startswith("admin:content_img:"))
async def admin_content_img_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    content_key = callback.data.split(":", 2)[2]
    label = CONTENT_LABELS.get(content_key, content_key)
    parent_key = next(
        (post_key for post_key, image_key in CONTENT_IMAGE_KEY.items() if image_key == content_key),
        content_key,
    )
    await state.set_state(AdminStates.edit_content_image)
    await state.update_data(content_key=content_key, parent_key=parent_key)
    await callback.message.answer(
        f"Отправьте новое фото для «{CONTENT_LABELS.get(parent_key, label)}»."
    )
    await callback.answer()


@router.message(AdminStates.edit_content_image, F.photo)
async def admin_content_img_save(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    content_key = data["content_key"]
    parent_key = data.get("parent_key", content_key)
    file_id = message.photo[-1].file_id

    async with session_factory() as session:
        await set_image_file_id(session, content_key, file_id)
        await session.commit()

    await state.clear()
    await message.answer(
        "Картинка сохранена ✅",
        reply_markup=InlineKeyboardBuilder()
        .row(
            InlineKeyboardButton(
                text="◀️ К посту",
                callback_data=f"admin:content:{parent_key}",
            )
        )
        .as_markup(),
    )


@router.callback_query(F.data.startswith("admin:content_img_reset:"))
async def admin_content_img_reset(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    content_key = callback.data.split(":", 2)[2]
    parent_key = next(
        (post_key for post_key, image_key in CONTENT_IMAGE_KEY.items() if image_key == content_key),
        content_key,
    )
    async with session_factory() as session:
        await set_image_file_id(session, content_key, None)
        await session.commit()
        text = await format_content_detail(session, parent_key)

    await callback.answer("Картинка удалена")
    await callback.message.edit_text(
        text,
        reply_markup=content_edit_keyboard(parent_key),
    )


@router.callback_query(F.data == "admin:pushes")
async def admin_pushes(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    async with session_factory() as session:
        pushes = (
            await session.execute(
                select(PushMessage)
                .where(PushMessage.campaign_id == 1)
                .order_by(PushMessage.order_index)
            )
        ).scalars().all()

    await callback.message.edit_text(
        "<b>📬 Цепочка прогрева</b>\nВыберите пуш для редактирования:",
        reply_markup=pushes_list_keyboard(list(pushes)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:push:"))
async def admin_push_detail(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    push_id = int(callback.data.split(":")[2])
    async with session_factory() as session:
        push = await session.get(PushMessage, push_id)

    if push is None:
        await callback.answer("Пуш не найден", show_alert=True)
        return

    await callback.message.edit_text(
        format_push_detail(push),
        reply_markup=push_edit_keyboard(push.id, push.enabled),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:toggle:"))
async def admin_toggle_push(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    push_id = int(callback.data.split(":")[2])
    async with session_factory() as session:
        push = await session.get(PushMessage, push_id)
        if push:
            push.enabled = not push.enabled
            enabled = push.enabled
            await session.commit()
        else:
            await callback.answer("Не найден", show_alert=True)
            return

    await callback.answer("Обновлено")
    await callback.message.edit_reply_markup(
        reply_markup=push_edit_keyboard(push_id, enabled)
    )


@router.callback_query(F.data.startswith("admin:edit_text:"))
async def admin_edit_text_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    push_id = int(callback.data.split(":")[2])
    await state.set_state(AdminStates.edit_text)
    await state.update_data(push_id=push_id)
    await callback.message.answer(
        "Отправьте новый текст пуша.\n"
        "Форматирование Telegram (жирный, курсив) сохранится как HTML."
    )
    await callback.answer()


@router.message(AdminStates.edit_text)
async def admin_edit_text_save(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    push_id = data["push_id"]
    async with session_factory() as session:
        push = await session.get(PushMessage, push_id)
        if push:
            push.text = message_html(message)
            await session.commit()

    await state.clear()
    await message.answer(
        "Текст сохранён ✅",
        reply_markup=InlineKeyboardBuilder()
        .row(InlineKeyboardButton(text="◀️ К пушу", callback_data=f"admin:push:{push_id}"))
        .as_markup(),
    )


@router.callback_query(F.data.startswith("admin:edit_delay:"))
async def admin_edit_delay_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    push_id = int(callback.data.split(":")[2])
    await state.set_state(AdminStates.edit_delay)
    await state.update_data(push_id=push_id)
    await callback.message.answer(
        "Отправьте задержку в минутах (от момента /start, первого входа в бота):"
    )
    await callback.answer()


@router.message(AdminStates.edit_delay)
async def admin_edit_delay_save(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    if not message.text or not message.text.strip().isdigit():
        await message.answer("Введите число минут, например: 1440")
        return

    data = await state.get_data()
    push_id = data["push_id"]
    delay = int(message.text.strip())

    async with session_factory() as session:
        push = await session.get(PushMessage, push_id)
        if push:
            push.delay_minutes = delay
            await session.commit()

    await state.clear()
    await message.answer(
        f"Тайминг сохранён: {delay} мин ✅",
        reply_markup=InlineKeyboardBuilder()
        .row(InlineKeyboardButton(text="◀️ К пушу", callback_data=f"admin:push:{push_id}"))
        .as_markup(),
    )


@router.callback_query(F.data.startswith("admin:edit_btn:"))
async def admin_edit_btn_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    push_id = int(callback.data.split(":")[2])
    await state.set_state(AdminStates.edit_button_text)
    await state.update_data(push_id=push_id)
    await callback.message.answer("Отправьте текст кнопки:")
    await callback.answer()


@router.message(AdminStates.edit_button_text)
async def admin_edit_btn_save(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    push_id = data["push_id"]
    async with session_factory() as session:
        push = await session.get(PushMessage, push_id)
        if push:
            push.button_text = message.text or ""
            await session.commit()

    await state.clear()
    await message.answer(
        "Текст кнопки сохранён ✅",
        reply_markup=InlineKeyboardBuilder()
        .row(InlineKeyboardButton(text="◀️ К пушу", callback_data=f"admin:push:{push_id}"))
        .as_markup(),
    )


@router.callback_query(F.data.startswith("admin:edit_url:"))
async def admin_edit_url_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    push_id = int(callback.data.split(":")[2])
    await state.set_state(AdminStates.edit_button_url)
    await state.update_data(push_id=push_id)
    await callback.message.answer(
        "Отправьте URL кнопки.\n"
        "Используйте {consultation_url} для ссылки записи с меткой источника."
    )
    await callback.answer()


@router.message(AdminStates.edit_button_url)
async def admin_edit_url_save(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    push_id = data["push_id"]
    async with session_factory() as session:
        push = await session.get(PushMessage, push_id)
        if push:
            push.button_url = message.text or ""
            await session.commit()

    await state.clear()
    await message.answer(
        "Ссылка сохранена ✅",
        reply_markup=InlineKeyboardBuilder()
        .row(InlineKeyboardButton(text="◀️ К пушу", callback_data=f"admin:push:{push_id}"))
        .as_markup(),
    )


@router.callback_query(F.data.startswith("admin:edit_image:"))
async def admin_edit_image_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    push_id = int(callback.data.split(":")[2])
    await state.set_state(AdminStates.edit_image)
    await state.update_data(push_id=push_id)
    await callback.message.answer(
        "Отправьте картинку для пуша или /skip чтобы убрать изображение."
    )
    await callback.answer()


@router.message(AdminStates.edit_image, F.photo)
async def admin_edit_image_save(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    push_id = data["push_id"]
    file_id = message.photo[-1].file_id

    async with session_factory() as session:
        push = await session.get(PushMessage, push_id)
        if push:
            push.image_file_id = file_id
            await session.commit()

    await state.clear()
    await message.answer(
        "Картинка сохранена ✅",
        reply_markup=InlineKeyboardBuilder()
        .row(InlineKeyboardButton(text="◀️ К пушу", callback_data=f"admin:push:{push_id}"))
        .as_markup(),
    )


@router.message(AdminStates.edit_image, Command("skip"))
async def admin_edit_image_skip(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    push_id = data["push_id"]

    async with session_factory() as session:
        push = await session.get(PushMessage, push_id)
        if push:
            push.image_file_id = None
            await session.commit()

    await state.clear()
    await message.answer(
        "Картинка удалена ✅",
        reply_markup=InlineKeyboardBuilder()
        .row(InlineKeyboardButton(text="◀️ К пушу", callback_data=f"admin:push:{push_id}"))
        .as_markup(),
    )


@router.callback_query(F.data.startswith("admin:push_delete:"))
async def admin_push_delete(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    push_id = int(callback.data.split(":")[2])
    async with session_factory() as session:
        push = await session.get(PushMessage, push_id)
        if push is None:
            await callback.answer("Пуш не найден", show_alert=True)
            return

        await session.execute(
            delete(PushDelivery).where(PushDelivery.push_id == push_id)
        )
        await session.delete(push)
        await session.commit()

    await callback.answer("Пуш удалён")
    async with session_factory() as session:
        all_pushes = (
            await session.execute(
                select(PushMessage)
                .where(PushMessage.campaign_id == 1)
                .order_by(PushMessage.order_index)
            )
        ).scalars().all()

    await callback.message.edit_text(
        "<b>📬 Цепочка прогрева</b>\nВыберите пуш для редактирования:",
        reply_markup=pushes_list_keyboard(list(all_pushes)),
    )


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    async with session_factory() as session:
        stats = await get_funnel_stats(session)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin:menu"))
    await callback.message.edit_text(
        format_funnel_report(stats),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:export")
async def admin_export(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    async with session_factory() as session:
        csv_data = await export_users_csv(session)

    file = BufferedInputFile(csv_data, filename="users_export.csv")
    await callback.message.answer_document(file, caption="Экспорт пользователей")
    await callback.answer()


@router.callback_query(F.data == "admin:campaigns")
async def admin_campaigns(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📋 Дублировать кампанию",
            callback_data="admin:duplicate",
        )
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin:menu"))

    async with session_factory() as session:
        campaigns = (await session.execute(select(Campaign))).scalars().all()
        lines = ["<b>📋 Кампании</b>\n"]
        for c in campaigns:
            status = "активна" if c.is_active else "неактивна"
            lines.append(f"• {c.name} ({status})")

    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "admin:duplicate")
async def admin_duplicate_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.duplicate_campaign)
    await callback.message.answer("Введите название новой кампании:")
    await callback.answer()


@router.message(AdminStates.duplicate_campaign)
async def admin_duplicate_save(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    name = (message.text or "Новая кампания").strip()[:255]

    async with session_factory() as session:
        source_pushes = (
            await session.execute(
                select(PushMessage).where(PushMessage.campaign_id == 1)
            )
        ).scalars().all()

        campaign = Campaign(name=name, is_active=False)
        session.add(campaign)
        await session.flush()

        for push in source_pushes:
            session.add(
                PushMessage(
                    campaign_id=campaign.id,
                    order_index=push.order_index,
                    delay_minutes=push.delay_minutes,
                    text=push.text,
                    image_file_id=push.image_file_id,
                    button_text=push.button_text,
                    button_url=push.button_url,
                    enabled=push.enabled,
                    stop_on_consultation_click=push.stop_on_consultation_click,
                )
            )
        campaign_id = campaign.id
        await session.commit()

    await state.clear()
    await message.answer(
        f"Кампания «{name}» создана (id={campaign_id}). "
        "Активируйте её в БД или добавьте переключение в админке."
    )
