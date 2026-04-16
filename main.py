"""
Главный файл бота К-30
"""
import logging
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database import init_database
from google_sheets import init_sheet_headers
from handlers import registration, admin, lost_items, dynamic_menu, menu_admin
from scheduler import setup_scheduler

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Основная функция запуска бота"""
    # Проверка токена
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set! Please check your .env file.")
        return

    # Инициализация базы данных
    try:
        init_database()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        return

    # Инициализация Google Sheets
    try:
        init_sheet_headers()
        logger.info("Google Sheets initialized")
    except Exception as e:
        logger.error(f"Error initializing Google Sheets: {e}")
        return

    # Создание бота и диспетчера
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    
    dp.include_router(lost_items.router)
    dp.include_router(admin.router)
    dp.include_router(menu_admin.router)
    dp.include_router(dynamic_menu.router)
    dp.include_router(registration.router)
    

    # Настройка планировщика
    scheduler = setup_scheduler(bot)

    try:
        logger.info("Bot starting...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error(f"Error running bot: {e}")
    finally:
        if scheduler.running:
            scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
