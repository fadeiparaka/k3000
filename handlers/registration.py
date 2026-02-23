"""
Хендлеры для процесса регистрации
"""
import re
import logging
from datetime import datetime
from typing import Optional
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import CommandStart, Command
import pytz

from config import EVENT_DEADLINE, TIMEZONE, EVENT_ANNOUNCE_LINK, BASE_DIR
from database import add_or_update_user, update_user_activity, set_user_consented, has_user_consented
from google_sheets import is_user_registered, register_user, get_sheet_url
from utils import send_thinking, delete_thinking

logger = logging.getLogger(__name__)

router = Router()

moscow_tz = pytz.timezone(TIMEZONE)


class RegistrationStates(StatesGroup):
    """Состояния FSM для процесса регистрации"""
    waiting_for_name = State()
    confirming_name = State()


def is_registration_deadline_passed() -> bool:
    """Проверяет, не прошла ли дата дедлайна регистрации (по Москве)"""
    now = datetime.now(moscow_tz)
    deadline = moscow_tz.localize(EVENT_DEADLINE)
    return now > deadline



def validate_name(name: str) -> tuple[bool, Optional[str]]:
    """
    Валидирует имя и фамилию.
    Возвращает (is_valid, error_message)
    """
    # Проверка на наличие цифр
    if re.search(r'\d', name):
        return False, "Имя и фамилия не должны содержать цифры. Пожалуйста, отправьте ваши имя и фамилию текстом."
    
    # Проверка на эмодзи и специальные символы (разрешаем только буквы, пробелы, дефис, апостроф)
    if not re.match(r'^[а-яА-ЯёЁa-zA-Z\s\-\']+$', name):
        return False, "Пожалуйста, используйте только буквы (кириллица или латиница), пробелы, дефис или апостроф."
    
    # Проверка на минимум два слова
    words = name.strip().split()
    if len(words) < 2:
        return False, "Пожалуйста, укажите и имя, и фамилию (минимум два слова)."
    
    return True, None


def get_main_menu_keyboard():
    """Клавиатура главного меню"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Бесплатная рега", callback_data="register_start")]
    ])


def get_consent_keyboard():
    """Клавиатура экрана согласия"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Продолжить", callback_data="consent_continue", style="success")]
    ])


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start — экран согласия на обработку данных"""
    user_id = message.from_user.id
    username = message.from_user.username
    add_or_update_user(user_id, username)
    await state.clear()

    await message.answer(
        "Привет. Подтверди, пожалуйста, что мы можем обрабатывать твои персональные данные 🤦 /privacy",
        reply_markup=get_consent_keyboard()
    )


@router.callback_query(F.data == "consent_continue")
async def consent_continue(callback: CallbackQuery, state: FSMContext):
    """После нажатия «Продолжить» — сохраняем согласие и показываем главное меню"""
    user_id = callback.from_user.id
    set_user_consented(user_id)
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "27-го февраля делаем мощный афтыч открытия К-30. Ты с нами?",
        reply_markup=get_main_menu_keyboard()
    )


@router.message(Command("privacy"))
async def cmd_privacy(message: Message):
    """Команда /privacy — отправка файла политики конфиденциальности"""
    privacy_path = BASE_DIR / "k30privacy.txt"
    if not privacy_path.exists():
        await message.answer("Файл политики конфиденциальности временно недоступен.")
        return
    try:
        document = FSInputFile(privacy_path, filename="k30privacy.txt")
        await message.answer_document(document=document)
    except Exception as e:
        logger.error(f"Error sending privacy file: {e}")
        await message.answer("Не удалось отправить файл. Попробуйте позже.")


@router.callback_query(F.data == "register_start")
async def register_start(callback: CallbackQuery, state: FSMContext):
    """Начало процесса регистрации"""
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    bot = callback.bot

    # Проверка дедлайна
    if is_registration_deadline_passed():
        await callback.answer()
        await callback.message.edit_text(
            "Упс. Регистрация закрыта. Следите за анонсами новых событий!"
        )
        return

    thinking = await send_thinking(chat_id, bot)
    try:
        # Проверка, не зарегистрирован ли уже (обращение к Google Sheets)
        if is_user_registered(user_id):
            await callback.answer()
            await callback.message.edit_text(
                "Ты уже в списке. Ждём 27 февраля на афтыче!"
            )
            return

        # Переходим в состояние ожидания имени
        await state.set_state(RegistrationStates.waiting_for_name)

        await callback.answer()
        await callback.message.edit_text(
            "Одна рега - один человек. Регистрация закроется в 18:00, 26-го февраля или если места закончатся.<br><br>"
            "<i>Рега не отменяет фейсконтроль, так что принарядись и будь вежлив на входе</i> 👫<br>"
            "<blockquote expandable>Не регайся, если не уверен, что сможешь прийти.</blockquote><br>"
            "<b>Напиши свое имя и фамилию ниже одним сообщением и ты окажешься в списке на входе</b> 👇",
            parse_mode="HTML"
        )
    finally:
        await delete_thinking(thinking)


@router.message(RegistrationStates.waiting_for_name, F.text)
async def process_name(message: Message, state: FSMContext):
    """Обработка введенного имени"""
    user_id = message.from_user.id
    name = message.text.strip()
    
    # Валидация
    is_valid, error_msg = validate_name(name)
    
    if not is_valid:
        await message.answer(error_msg)
        return
    
    # Сохраняем имя в состоянии
    await state.update_data(full_name=name)
    await state.set_state(RegistrationStates.confirming_name)
    
    # Формируем сообщение подтверждения
    username = message.from_user.username
    tg_contact = f"@{username}" if username else "этот аккаунт"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Верно", callback_data="confirm_registration"),
            InlineKeyboardButton(text="✏️ Изменить", callback_data="change_name")
        ]
    ])
    
    await message.answer(
        f"Ваши имя и фамилия: {name}.\n"
        f"Контакт в тг: {tg_contact}",
        reply_markup=keyboard
    )


@router.message(RegistrationStates.waiting_for_name)
async def process_name_invalid(message: Message):
    """Обработка невалидного сообщения (не текст)"""
    await message.answer(
        "Пожалуйста, отправь свои имя и фамилию одним сообщением."
    )


@router.callback_query(F.data == "change_name")
async def change_name(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Изменить'"""
    await state.set_state(RegistrationStates.waiting_for_name)
    
    await callback.answer()
    await callback.message.edit_text(
        "Напиши своё имя и фамилию"
    )


@router.callback_query(F.data == "confirm_registration")
async def confirm_registration(callback: CallbackQuery, state: FSMContext):
    """Подтверждение регистрации"""
    user_id = callback.from_user.id
    username = callback.from_user.username
    chat_id = callback.message.chat.id
    bot = callback.bot

    # Повторная проверка дедлайна
    if is_registration_deadline_passed():
        await callback.answer()
        await callback.message.edit_text(
            "Упс. Регистрация закрыта. Следите за анонсами новых событий!"
        )
        await state.clear()
        return

    # Получаем данные из состояния
    data = await state.get_data()
    full_name = data.get("full_name")

    if not full_name:
        await callback.answer("Ошибка: данные не найдены. Попробуйте начать заново.", show_alert=True)
        await state.clear()
        return

    thinking = await send_thinking(chat_id, bot)
    try:
        # Проверка, не зарегистрирован ли уже (на случай гонок)
        if is_user_registered(user_id):
            await callback.answer()
            await callback.message.edit_text(
                "Ты уже в списке. Ждём 27 февраля на афтыче!"
            )
            await state.clear()
            return

        # Регистрируем пользователя (запись в Google Sheets)
        success = register_user(user_id, full_name, username)

        if success:
            # Обновляем активность пользователя
            update_user_activity(user_id)

            await callback.answer()
            await callback.message.edit_text(
                "Поздравляем 🎈 Ты зареган на заслуженный афтыч. "
                "Вход по регистрациям возможен до 23:30 в день ивента, 27-го февраля.\n\n"
                "<blockquote>Просто назови своё имя и фамилию на входе.</blockquote>",
                parse_mode="HTML"
            )

            # TODO: Отправить картинку с информацией о событии
            # await callback.message.answer_photo(photo=...)
        else:
            await callback.answer("Вы уже зарегистрированы!", show_alert=True)
            await callback.message.edit_text(
                "Ты уже в списке. Ждём 27 февраля на афтыче!"
            )
    except Exception as e:
        logger.error(f"Error registering user {user_id}: {e}")
        await callback.answer("Произошла ошибка при регистрации. Попробуйте позже.", show_alert=True)
    finally:
        await delete_thinking(thinking)

    await state.clear()


@router.message()
async def handle_unknown_message(message: Message):
    """Обработчик неизвестных сообщений — главное меню только если согласие дано"""
    user_id = message.from_user.id
    username = message.from_user.username
    add_or_update_user(user_id, username)

    if not has_user_consented(user_id):
        await message.answer(
            "Привет. Подтверди, пожалуйста, что мы можем обрабатывать твои персональные данные 🤦 /privacy",
            reply_markup=get_consent_keyboard()
        )
        return

    await message.answer(
        "27-го февраля делаем мощный афтыч открытия К-30. Ты с нами?",
        reply_markup=get_main_menu_keyboard()
    )
