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
from sqlalchemy import delete, func, select

from config.settings import settings
from services.analytics import export_users_csv, format_funnel_report, get_funnel_stats
from services.content import (
    CONTENT_ALERT_KEYS,
    CONTENT_BUTTON_KEYS,
    CONTENT_GROUP_LABELS,
    CONTENT_IMAGE_KEY,
    CONTENT_LABELS,
    CONTENT_TEXT_KEYS,
    START_CAPTION,
    START_IMAGE,
)
from services.channel_resolve import message_html
from services.content_store import get_text, set_image_file_id, set_text
from services.database import session_factory
from services.models import PushDelivery, PushMessage, User
from services.users import get_or_create_user, reset_all_warmups, reset_user_warmup

router = Router()


class AdminStates(StatesGroup):
    edit_text = State()
    edit_delay = State()
    edit_button_text = State()
    edit_button_url = State()
    edit_image = State()
    edit_content_text = State()
    edit_content_image = State()
    add_push_delay = State()
    add_push_text = State()


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


def content_group_for_key(content_key: str) -> str:
    if content_key in CONTENT_BUTTON_KEYS:
        return "buttons"
    if content_key in CONTENT_ALERT_KEYS:
        return "alerts"
    return "messages"


def texts_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📝 Сообщения", callback_data="admin:texts:messages"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔘 Кнопки", callback_data="admin:texts:buttons"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔔 Алерты", callback_data="admin:texts:alerts"
        )
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin:menu"))
    return builder.as_markup()


def content_group_keyboard(group: str):
    keys_by_group = {
        "messages": CONTENT_TEXT_KEYS,
        "buttons": CONTENT_BUTTON_KEYS,
        "alerts": CONTENT_ALERT_KEYS,
    }
    builder = InlineKeyboardBuilder()
    for key in keys_by_group[group]:
        builder.row(
            InlineKeyboardButton(
                text=CONTENT_LABELS[key],
                callback_data=f"admin:content:{key}",
            )
        )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin:texts"))
    return builder.as_markup()


def admin_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📝 Контент", callback_data="admin:texts"),
        InlineKeyboardButton(text="📬 Пуши", callback_data="admin:pushes"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Аналитика", callback_data="admin:stats"),
        InlineKeyboardButton(text="📥 Экспорт CSV", callback_data="admin:export"),
    )
    builder.row(
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
    builder.row(
        InlineKeyboardButton(text="➕ Добавить пуш", callback_data="admin:push_add")
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin:menu"))
    return builder.as_markup()


def push_edit_keyboard(push_id: int, enabled: bool):
    builder = InlineKeyboardBuilder()
    toggle_text = "⏸ Отключить пуш" if enabled else "✅ Включить пуш"
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
            text="🔘 Кнопка", callback_data=f"admin:push_btn:{push_id}"
        ),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ К списку", callback_data="admin:pushes")
    )
    return builder.as_markup()


def push_button_menu_keyboard(push_id: int, button_enabled: bool):
    builder = InlineKeyboardBuilder()
    toggle_text = "⏸ Выключить" if button_enabled else "✅ Включить"
    builder.row(
        InlineKeyboardButton(
            text="✏️ Текст", callback_data=f"admin:edit_btn:{push_id}"
        ),
        InlineKeyboardButton(
            text="🔗 Ссылка", callback_data=f"admin:edit_url:{push_id}"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=toggle_text, callback_data=f"admin:push_btn_toggle:{push_id}"
        )
    )
    builder.row(
        InlineKeyboardButton(text="◀️ К пушу", callback_data=f"admin:push:{push_id}")
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


@router.message(Command("fm"))
async def cmd_fm(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    async with session_factory() as session:
        user = await session.get(User, message.from_user.id)
        if user is None:
            user, _ = await get_or_create_user(
                session,
                message.from_user.id,
                message.from_user.username,
                message.from_user.first_name,
                message.from_user.last_name,
                "direct",
            )
        await reset_user_warmup(session, user)
        await session.commit()

    await message.answer(
        "Прогрев сброшен для вашего аккаунта.\n"
        "Пуши начнут приходить заново по таймингам от текущего момента."
    )


@router.message(Command("f_all"))
async def cmd_f_all(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    async with session_factory() as session:
        count = await reset_all_warmups(session)
        await session.commit()

    await message.answer(
        f"Прогрев сброшен для {count} пользователей.\n"
        "Все пуши будут отправлены заново по таймингам."
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
        InlineKeyboardButton(
            text="◀️ К списку",
            callback_data=f"admin:texts:{content_group_for_key(content_key)}",
        )
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
    button_status = "включена ✅" if push.button_enabled else "выключена ⏸"
    return (
        f"<b>Пуш #{push.order_index}</b>\n"
        f"Тайминг: {push.delay_minutes} мин от входа в бота\n"
        f"Кнопка: {button_status} — {push.button_text or '—'}\n"
        f"Картинка: {image_status}\n\n"
        f"{preview}"
    )


def format_push_button_detail(push: PushMessage) -> str:
    status = "включена ✅" if push.button_enabled else "выключена ⏸"
    url = push.button_url or "{consultation_url}"
    return (
        f"<b>🔘 Кнопка — пуш #{push.order_index}</b>\n\n"
        f"Статус: {status}\n"
        f"Текст: {push.button_text or '—'}\n"
        f"Ссылка: {url}"
    )


@router.callback_query(F.data == "admin:texts")
async def admin_texts(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        "<b>📝 Контент бота</b>\n\nВыберите раздел:",
        reply_markup=texts_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:texts:"))
async def admin_texts_group(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    group = callback.data.split(":")[2]
    if group not in CONTENT_GROUP_LABELS:
        await callback.answer("Раздел не найден", show_alert=True)
        return

    await callback.message.edit_text(
        f"<b>{CONTENT_GROUP_LABELS[group]}</b>\n\nВыберите элемент:",
        reply_markup=content_group_keyboard(group),
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
                select(PushMessage).order_by(PushMessage.order_index)
            )
        ).scalars().all()

    await callback.message.edit_text(
        "<b>📬 Цепочка прогрева</b>\n"
        "Выберите пуш или добавьте новый:",
        reply_markup=pushes_list_keyboard(list(pushes)),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^admin:push:\d+$"))
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


@router.callback_query(F.data.regexp(r"^admin:push_btn:\d+$"))
async def admin_push_button_menu(callback: CallbackQuery) -> None:
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
        format_push_button_detail(push),
        reply_markup=push_button_menu_keyboard(push.id, push.button_enabled),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:push_btn_toggle:"))
async def admin_push_button_toggle(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    push_id = int(callback.data.split(":")[2])
    async with session_factory() as session:
        push = await session.get(PushMessage, push_id)
        if push is None:
            await callback.answer("Не найден", show_alert=True)
            return
        push.button_enabled = not push.button_enabled
        button_enabled = push.button_enabled
        await session.commit()

    await callback.answer("Обновлено")
    await callback.message.edit_text(
        format_push_button_detail(push),
        reply_markup=push_button_menu_keyboard(push_id, button_enabled),
    )


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
    await callback.message.answer(
        "Отправьте текст кнопки в пуше (подпись на ссылке).\n"
        "URL настраивается отдельно: 🔗 Ссылка."
    )
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
        .row(InlineKeyboardButton(text="◀️ К кнопке", callback_data=f"admin:push_btn:{push_id}"))
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
        "Отправьте URL кнопки — откроется сразу при нажатии в пуше.\n"
        "Шаблон: <code>{consultation_url}</code> — подставит ссылку из .env с меткой источника."
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
        .row(InlineKeyboardButton(text="◀️ К кнопке", callback_data=f"admin:push_btn:{push_id}"))
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
                select(PushMessage).order_by(PushMessage.order_index)
            )
        ).scalars().all()

    await callback.message.edit_text(
        "<b>📬 Цепочка прогрева</b>\n"
        "Выберите пуш или добавьте новый:",
        reply_markup=pushes_list_keyboard(list(all_pushes)),
    )


@router.callback_query(F.data == "admin:push_add")
async def admin_push_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.add_push_delay)
    await callback.message.answer(
        "Через сколько минут после входа в бота отправить новый пуш?\n"
        "Например: <code>60</code> — через час, <code>1440</code> — через сутки."
    )
    await callback.answer()


@router.message(AdminStates.add_push_delay)
async def admin_push_add_delay(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    if not message.text or not message.text.strip().isdigit():
        await message.answer("Введите число минут, например: 1440")
        return

    await state.update_data(delay_minutes=int(message.text.strip()))
    await state.set_state(AdminStates.add_push_text)
    await message.answer(
        "Отправьте текст нового пуша.\n"
        "Форматирование Telegram (жирный, курсив) сохранится как HTML."
    )


@router.message(AdminStates.add_push_text)
async def admin_push_add_text(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    text = message_html(message).strip()
    if not text:
        await message.answer("Текст пуша не может быть пустым.")
        return

    data = await state.get_data()
    delay = data["delay_minutes"]

    async with session_factory() as session:
        next_order = (
            await session.scalar(select(func.max(PushMessage.order_index))) or 0
        ) + 1
        push = PushMessage(
            order_index=next_order,
            delay_minutes=delay,
            text=text,
            button_text="Записаться на консультацию",
            button_url="{consultation_url}",
            button_enabled=True,
            enabled=True,
            stop_on_consultation_click=True,
        )
        session.add(push)
        await session.flush()
        push_id = push.id
        await session.commit()

    await state.clear()
    await message.answer(
        f"Пуш #{next_order} добавлен ✅\n\n"
        f"Тайминг: {delay} мин.\n"
        "Кнопку, картинку и остальное можно настроить в карточке пуша.",
        reply_markup=InlineKeyboardBuilder()
        .row(InlineKeyboardButton(text="◀️ К пушу", callback_data=f"admin:push:{push_id}"))
        .row(InlineKeyboardButton(text="📬 К списку", callback_data="admin:pushes"))
        .as_markup(),
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
