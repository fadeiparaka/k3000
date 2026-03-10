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


from config import EVENT_DEADLINE, TIMEZONE, EVENT_ANNOUNCE_LINK, BASE_DIR, MAX_PARTICIPANTS, EARLY_ACCESS_LINK
from database import add_or_update_user, update_user_activity, set_user_consented, has_user_consented, add_early_access_user, is_early_access_user
from google_sheets import is_user_registered, register_user, get_sheet_url, get_registration_count
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

def is_registration_limit_reached() -> bool:
    """
    Проверяет, достигнут ли лимит участников по данным Google Sheets.
    Считает только реальные регистрации (строки, кроме заголовка).
    """
    try:
        current_count = get_registration_count()
        return current_count >= MAX_PARTICIPANTS
    except Exception as e:
        logger.error(f"Error checking registration limit: {e}")
        # На всякий случай не блокируем регистрацию при ошибке
        return False



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
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ранний доступ на Формы Прослушивания (13.03)", callback_data="early_access")],
        [InlineKeyboardButton(text="Получить фотоотчёт", callback_data="get_photos")],
        [InlineKeyboardButton(text="Я забыл свои вещи в К-30", callback_data="lost_item")]
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
        "Салют, это бот К-30! Что тебя интересует?",
        reply_markup=get_main_menu_keyboard()
    )

@router.callback_query(F.data == "early_access")
async def early_access_info(callback: CallbackQuery):
    """Экран с описанием раннего доступа"""
    await callback.answer()
    await callback.message.edit_text(
        "Поздравляем, ты получил ранний доступ к вечеринке Формы Прослушивания.\n\n"
        "<b>Что это значит?</b>\n\n"
        "• Мы пришлем ссылку на приобретение билета всего за 500 рублей\n"
        "• Ссылка может перестать работать в любой момент, не откладывай\n"
        "• Вход по таким билетам возможен только до 00:30 в ночь события\n"
        "• Билет придет на почту, которую ты укажешь при покупке",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Получить секретную ссылку", callback_data="early_access_get_link")]
        ])
    )


@router.callback_query(F.data == "early_access_get_link")
async def early_access_get_link(callback: CallbackQuery):
    """Выдача ссылки + трекинг пользователя"""
    user_id = callback.from_user.id
    username = callback.from_user.username

    add_early_access_user(user_id, username)

    await callback.answer()
    await callback.message.edit_text(
        f"А вот и заветная ссылка 👉 {EARLY_ACCESS_LINK}"
    )


@router.callback_query(F.data == "get_photos")
async def get_photos_redirect(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "Фотоотчёт первой большой вечеринки после открытия\n\n"
        '<a href="https://disk.yandex.ru/d/9hMCg2epPtHBqg">Посмотреть</a>',
        parse_mode="HTML"
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
async def register_start_redirect(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "Салют, это бот К-30! Что тебя интересует?",
        reply_markup=get_main_menu_keyboard()
    )



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

    # Повторная проверка лимита (на случай гонок)
    if is_registration_limit_reached():
        await callback.answer()
        await callback.message.edit_text(
            "Упс. Превышен лимит мест в списках. Регистрация закрыта. Недорогие билеты на афтыч можно приобрести на сайте www.k-30.com"
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
async def handle_unknown_message(message: Message, state: FSMContext):
    if message.chat.type != "private":
        return

    # Если пользователь в каком-то состоянии FSM — не перехватываем
    current_state = await state.get_state()
    if current_state is not None:
        return

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
        "Салют, это бот К-30! Что тебя интересует?",
        reply_markup=get_main_menu_keyboard()
    )
