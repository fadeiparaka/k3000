"""
Вспомогательные функции
"""
from aiogram import Bot
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest
import logging

logger = logging.getLogger(__name__)

THINKING_TEXT = "Думаю..."


async def send_thinking(chat_id: int, bot: Bot) -> Message | None:
    """Отправляет сообщение «Думаю...» в чат. Возвращает сообщение для последующего удаления."""
    try:
        return await bot.send_message(chat_id=chat_id, text=THINKING_TEXT)
    except Exception as e:
        logger.warning(f"Could not send thinking message: {e}")
        return None


async def delete_thinking(msg: Message | None):
    """Удаляет сообщение «Думаю...» (игнорирует ошибки)."""
    if msg is None:
        return
    try:
        await msg.delete()
    except TelegramBadRequest:
        pass
    except Exception as e:
        logger.warning(f"Could not delete thinking message: {e}")
