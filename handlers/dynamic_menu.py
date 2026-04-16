"""
Пользовательские хендлеры динамического меню.
"""
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import add_or_update_user, has_user_consented
from menu_service import (
    MENU_BACK_PREFIX,
    MENU_CALLBACK_PREFIX,
    handle_reply_menu_message,
    replace_with_root_menu,
    safe_callback_answer,
    send_dynamic_node,
    send_reply_menu_if_any,
    send_root_menu,
)

router = Router()


@router.callback_query(F.data.startswith(MENU_CALLBACK_PREFIX))
async def dynamic_menu_open(callback: CallbackQuery):
    raw_id = callback.data.removeprefix(MENU_CALLBACK_PREFIX)
    if not raw_id.isdigit():
        await safe_callback_answer(callback, "Некорректная кнопка.", show_alert=True)
        return
    await send_dynamic_node(callback, int(raw_id))


@router.callback_query(F.data.startswith(MENU_BACK_PREFIX))
async def dynamic_menu_back(callback: CallbackQuery):
    target = callback.data.removeprefix(MENU_BACK_PREFIX)
    if target == "root":
        await replace_with_root_menu(callback)
        return
    if not target.isdigit():
        await safe_callback_answer(callback, "Некорректная кнопка.", show_alert=True)
        return
    await send_dynamic_node(callback, int(target))


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def reply_menu_text(message: Message, state: FSMContext):
    if message.chat.type != "private":
        return
    add_or_update_user(message.from_user.id, message.from_user.username)
    if not has_user_consented(message.from_user.id):
        await message.answer(
            "Привет. Подтверди, пожалуйста, что мы можем обрабатывать твои персональные данные 🤦 /privacy",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Продолжить", callback_data="consent_continue", style="success")]
            ])
        )
        return
    handled = await handle_reply_menu_message(message)
    if not handled:
        await send_root_menu(message)
        await send_reply_menu_if_any(message)
