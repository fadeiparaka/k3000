"""
Модуль для настройки планировщика задач (напоминания)
"""
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import pytz
import asyncio

from config import REMINDER_1_DATETIME, REMINDER_2_DATETIME, TIMEZONE, EVENT_ANNOUNCE_LINK
from database import get_all_users, remove_user, update_user_activity
from google_sheets import is_user_registered
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)

moscow_tz = pytz.timezone(TIMEZONE)


async def send_reminder_1(bot):
    """
    Напоминание 26 февраля в 22:00
    Отправляется всем пользователям бота
    """
    logger.info("Sending reminder 1 (26.02 22:00)")
    
    users = get_all_users()
    success_count = 0
    failed_count = 0
    
    # Текст с вшитой ссылкой
    text = (
        f"Салют! Напоминаю, что регистрация на "
        f"[завтрашнюю афтерпати]({EVENT_ANNOUNCE_LINK}) "
        f"заканчивается через полтора часа. Ждем тебя!"
    )
    
    for user_id, username in users:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="Markdown"
            )
            update_user_activity(user_id)
            success_count += 1
        except TelegramBadRequest as e:
            if "bot was blocked" in str(e).lower() or "403" in str(e):
                logger.info(f"User {user_id} blocked the bot, removing from database")
                remove_user(user_id)
                failed_count += 1
            else:
                logger.error(f"Error sending reminder 1 to user {user_id}: {e}")
                failed_count += 1
        except Exception as e:
            logger.error(f"Unexpected error sending reminder 1 to user {user_id}: {e}")
            failed_count += 1
    
    logger.info(f"Reminder 1 sent: success={success_count}, failed={failed_count}")


async def send_reminder_2(bot):
    logger.info("Sending reminder 2 (27.02 14:00)")

    users = get_all_users()
    success_count = 0
    failed_count = 0

    # Один запрос к Google Sheets вместо 750
    from google_sheets import get_all_registered_ids
    registered_ids = get_all_registered_ids()
    logger.info(f"Registered users in sheet: {len(registered_ids)}")
    
    # Текст с вшитой ссылкой
    text = (
        "Привет. Ты зарегистрирован на сегодняшний афтыч в К-30 и мы нежно напоминаем о некоторых моментах в преддверии вечеринки:\n\n"
        "📄 Твое имя и фамилия будут в списках на входе. Именно так, как ты регался в боте\n\n"
        "🕐 Бесплатный вход по регам до 23:30. Скорее всего будет очередь, поэтому мы продлили доступ до 00:00\n\n"
        "👥 Постарайся приходить заранее, чтобы долго не стоять в очереди\n\n"
        "🎫 Если ты будешь с незарегистрированным другом или подругой, то они могут купить билет на нашем сайте или на входе. "
        "Вход по билетам без ограничений и всю ночь. Купить билет можно на сайте K-30.COM\n\n"
        "👀 В К-30 работает фейсконтроль. Пожалуйста, принарядись и будь вежлив на входе\n\n"
        "💿 Тайминг:\n\n"
        "<b>Внизу:</b>\n"
        "22:00 - Никита Гусев\n"
        "23:00 - Nadia\n"
        "00:30 - Utah\n"
        "02:00 - Nastya Tkacheva\n"
        "03:30 - Helter\n"
        "05:00 - end\n\n"
        "<b>Т-Лаб:</b>\n"
        "22:00 - Саша Яковлев\n"
        "23:40 - Сергей Летов - джазовая импровизация\n"
        "00:00 - Новые Композиторы\n"
        "01:00 - Lena Popova\n"
        "03:00 - Texture\n"
        "05:00 - end\n\n"
        "До встречи 👋"
    )
    
    for user_id, username in users:
        if str(user_id) not in registered_ids:
            continue

        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="HTML"
            )
            update_user_activity(user_id)
            success_count += 1
            await asyncio.sleep(0.05)  # ← 50ms пауза, ~20 сообщений/сек
        except Exception as e:
            logger.error(f"Error sending to {user_id}: {e}")
            failed_count += 1

    logger.info(f"Reminder 2 sent: success={success_count}, failed={failed_count}")


def setup_scheduler(bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=moscow_tz)

    # REMINDER_1_DATETIME и REMINDER_2_DATETIME — naive datetime (без tz),
    # например datetime(2026, 2, 26, 22, 0, 0)
    # reminder_1_dt = moscow_tz.localize(REMINDER_1_DATETIME)
    reminder_2_dt = moscow_tz.localize(REMINDER_2_DATETIME)

    now = datetime.now(moscow_tz)

    # if reminder_1_dt <= now:
    #     logger.warning("REMINDER_1_DATETIME в прошлом — напоминание 1 не будет запланировано")
    # else:
    #     scheduler.add_job(
    #         send_reminder_1,
    #         trigger=DateTrigger(run_date=reminder_1_dt),
    #         args=[bot],
    #         id="reminder_1",
    #         replace_existing=True
    #     )
    #     logger.info(f"Reminder 1 scheduled at {reminder_1_dt}")

    if reminder_2_dt <= now:
        logger.warning("REMINDER_2_DATETIME в прошлом — напоминание 2 не будет запланировано")
    else:
        scheduler.add_job(
            send_reminder_2,
            trigger=DateTrigger(run_date=reminder_2_dt),
            args=[bot],
            id="reminder_2",
            replace_existing=True
        )
        logger.info(f"Reminder 2 scheduled at {reminder_2_dt}")

    scheduler.start()
    logger.info("Scheduler started")
    return scheduler


