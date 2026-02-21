"""
Хендлеры для админ-команд
"""
import asyncio
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

from config import ADMINS
from database import get_all_users, remove_user, update_user_activity
from google_sheets import get_registration_count, get_sheet_url
from scheduler import send_reminder_1, send_reminder_2
from utils import send_thinking, delete_thinking

logger = logging.getLogger(__name__)

router = Router()


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь админом"""
    return user_id in ADMINS


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Команда /stats - статистика регистраций"""
    if not is_admin(message.from_user.id):
        await message.answer("Эта команда доступна только администраторам.")
        return

    thinking = await send_thinking(message.chat.id, message.bot)
    try:
        count = get_registration_count()
        sheet_url = get_sheet_url()
        await message.answer(
            f"Всего регистраций: {count}\n\n"
            f"Список участников: {sheet_url}"
        )
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        await message.answer("Произошла ошибка при получении статистики.")
    finally:
        await delete_thinking(thinking)


@router.message(Command("post"))
async def cmd_post(message: Message):
    """Команда /post - рассылка поста всем пользователям"""
    if not is_admin(message.from_user.id):
        await message.answer("Эта команда доступна только администраторам.")
        return

    # Проверяем, что команда отправлена как reply на другое сообщение
    if not message.reply_to_message:
        await message.answer(
            "Для отправки поста ответьте командой /post на сообщение с текстом и/или медиа, "
            "которое хотите разослать всем пользователям."
        )
        return

    source_message = message.reply_to_message
    thinking = await send_thinking(message.chat.id, message.bot)
    try:
        users = get_all_users()
    finally:
        await delete_thinking(thinking)

    if not users:
        await message.answer("В базе нет пользователей для рассылки.")
        return

    total_users = len(users)
    success_count = 0
    failed_count = 0

    await message.answer(f"Начинаю рассылку для {total_users} пользователей...")

    from_chat_id = source_message.chat.id
    message_id = source_message.message_id
    batch_size = 10
    delay_between_batches = 1.0

    for i, (user_id, username) in enumerate(users):
        try:
            await message.bot.copy_message(
                chat_id=user_id,
                from_chat_id=from_chat_id,
                message_id=message_id
            )
            update_user_activity(user_id)
            success_count += 1

            if (i + 1) % batch_size == 0:
                await asyncio.sleep(delay_between_batches)
        
        except TelegramBadRequest as e:
            # Обработка ошибок блокировки бота
            if "bot was blocked" in str(e).lower() or "403" in str(e):
                logger.info(f"User {user_id} blocked the bot, removing from database")
                remove_user(user_id)
                failed_count += 1
            else:
                logger.error(f"Error sending message to user {user_id}: {e}")
                failed_count += 1
        except Exception as e:
            logger.error(f"Unexpected error sending message to user {user_id}: {e}")
            failed_count += 1
    
    await message.answer(
        f"Рассылка завершена.\n"
        f"Успешно: {success_count}\n"
        f"Ошибок: {failed_count}"
    )


@router.message(Command("send_reminder_1"))
async def cmd_send_reminder_1(message: Message):
    """Ручная отправка напоминания 1 (26.02 22:00) — всем пользователям бота. Для проверки."""
    if not is_admin(message.from_user.id):
        await message.answer("Эта команда доступна только администраторам.")
        return
    await message.answer("Отправляю напоминание 1 (26.02 22:00) всем пользователям...")
    await send_reminder_1(message.bot)
    await message.answer("Готово.")


@router.message(Command("send_reminder_2"))
async def cmd_send_reminder_2(message: Message):
    """Ручная отправка напоминания 2 (27.02 10:00) — только зарегистрированным. Для проверки."""
    if not is_admin(message.from_user.id):
        await message.answer("Эта команда доступна только администраторам.")
        return
    await message.answer("Отправляю напоминание 2 (27.02 10:00) зарегистрированным...")
    await send_reminder_2(message.bot)
    await message.answer("Готово.")
