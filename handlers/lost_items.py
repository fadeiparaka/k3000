"""
Хендлеры для потеряшек
"""
import asyncio
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import LOST_ITEMS_CHAT_ID

logger = logging.getLogger(__name__)
router = Router()


class LostItemStates(StatesGroup):
    waiting_for_item = State()


_media_buffer: dict[str, list[Message]] = {}
_media_timers: set[str] = set()


@router.callback_query(F.data == "lost_item")
async def lost_item_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "Привет. Пожалуйста, опиши как мы можем идентифицировать твою вещь, "
        "её фото и свои контакты. Если мы найдем, то обязательно свяжемся. Спасибо",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Оставить заявку", callback_data="lost_item_start")]
        ])
    )


@router.callback_query(F.data == "lost_item_start")
async def lost_item_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(LostItemStates.waiting_for_item)
    await callback.answer()
    await callback.message.edit_text(
        "Следующим сообщением пришли текстовое описание + фото и свои контакты"
    )


# ⚠️ Альбом — ПЕРВЫМ
@router.message(LostItemStates.waiting_for_item, F.media_group_id)
async def process_lost_item_album(message: Message, state: FSMContext):
    if message.chat.type != "private":
        return

    group_id = message.media_group_id

    if group_id not in _media_buffer:
        _media_buffer[group_id] = []
    _media_buffer[group_id].append(message)

    if group_id in _media_timers:
        return
    _media_timers.add(group_id)

    await asyncio.sleep(0.7)

    messages = _media_buffer.pop(group_id, [])
    _media_timers.discard(group_id)

    if not messages:
        return

    messages.sort(key=lambda m: m.message_id)

    user_id = messages[0].from_user.id
    username = messages[0].from_user.username
    username_str = f"@{username}" if username else "без username"
    bot = messages[0].bot

    # Пометка
    await bot.send_message(
        chat_id=LOST_ITEMS_CHAT_ID,
        text=f"Потеряшка от {username_str} (id: <code>{user_id}</code>)",
        parse_mode="HTML"
    )

    # Пересылаем альбом одним вызовом — Telegram сохранит его как альбом
    await bot.copy_messages(
        chat_id=LOST_ITEMS_CHAT_ID,
        from_chat_id=messages[0].chat.id,
        message_ids=[m.message_id for m in messages]
    )

    await messages[0].answer("Спасибо, надеемся получится найти.")
    await state.clear()


# ⚠️ Одиночное — ВТОРЫМ, обязателен ~F.media_group_id
@router.message(LostItemStates.waiting_for_item, ~F.media_group_id)
async def process_lost_item_single(message: Message, state: FSMContext):
    if message.chat.type != "private":
        return

    user_id = message.from_user.id
    username = message.from_user.username
    username_str = f"@{username}" if username else "без username"
    bot = message.bot

    # Пометка
    await bot.send_message(
        chat_id=LOST_ITEMS_CHAT_ID,
        text=f"Потеряшка от {username_str} (id: <code>{user_id}</code>)",
        parse_mode="HTML"
    )

    # Пересылаем одиночное сообщение
    await message.copy_to(chat_id=LOST_ITEMS_CHAT_ID)

    await message.answer("Спасибо, надеемся получится найти.")
    await state.clear()
