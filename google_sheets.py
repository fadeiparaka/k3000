"""
Модуль для работы с Google Sheets
"""
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from typing import Optional, List, Dict
import logging
from config import GOOGLE_SHEETS_CREDENTIALS_PATH, GOOGLE_SHEET_ID, TIMEZONE
import pytz

logger = logging.getLogger(__name__)

moscow_tz = pytz.timezone(TIMEZONE)

# Настройка доступа к Google Sheets API
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


def get_sheets_client():
    """Создает клиент для работы с Google Sheets"""
    creds = Credentials.from_service_account_file(
        GOOGLE_SHEETS_CREDENTIALS_PATH,
        scopes=SCOPES
    )
    client = gspread.authorize(creds)
    return client


def get_worksheet():
    """Получает рабочий лист таблицы"""
    client = get_sheets_client()
    sheet = client.open_by_key(GOOGLE_SHEET_ID)
    # Используем первый лист
    worksheet = sheet.sheet1
    return worksheet


def init_sheet_headers():
    """Инициализирует заголовки таблицы, если их еще нет"""
    try:
        worksheet = get_worksheet()
        
        # Проверяем, есть ли заголовки
        headers = worksheet.row_values(1)
        
        if not headers or headers[0] != "User ID":
            # Создаем заголовки
            worksheet.append_row([
                "User ID",
                "Дата",
                "Имя Фамилия",
                "TG Username",
                "Статус",
                "Примечания"
            ])
            logger.info("Sheet headers initialized")
        else:
            logger.info("Sheet headers already exist")
    except Exception as e:
        logger.error(f"Error initializing sheet headers: {e}")
        raise


def is_user_registered(user_id: int) -> bool:
    """Проверяет, зарегистрирован ли пользователь"""
    try:
        worksheet = get_worksheet()
        
        # Ищем user_id в первом столбце
        cell = worksheet.find(str(user_id), in_column=1)
        return cell is not None
    except gspread.exceptions.CellNotFound:
        return False
    except Exception as e:
        logger.error(f"Error checking registration: {e}")
        return False


def register_user(user_id: int, full_name: str, username: Optional[str] = None):
    """
    Регистрирует пользователя в Google Sheets.
    Возвращает True если успешно, False если пользователь уже зарегистрирован.
    """
    try:
        worksheet = get_worksheet()
        
        # Проверяем, не зарегистрирован ли уже
        if is_user_registered(user_id):
            return False
        
        # Форматируем дату и время регистрации
        now = datetime.now(moscow_tz)
        date_str = now.strftime("%Y-%m-%d %H:%M")
        
        # Форматируем username
        tg_username = f"@{username}" if username else "-"
        
        # Добавляем строку
        worksheet.append_row([
            user_id,
            date_str,
            full_name,
            tg_username,
            "active",
            ""  # Примечания пустые
        ])
        
        logger.info(f"User {user_id} registered in Google Sheets")
        return True
    except Exception as e:
        logger.error(f"Error registering user: {e}")
        raise


def get_registration_count() -> int:
    """Возвращает количество зарегистрированных пользователей"""
    try:
        worksheet = get_worksheet()
        
        # Получаем все значения из первого столбца (кроме заголовка)
        user_ids = worksheet.col_values(1)
        
        # Убираем заголовок "User ID"
        if user_ids and user_ids[0] == "User ID":
            return len(user_ids) - 1
        
        return len(user_ids)
    except Exception as e:
        logger.error(f"Error getting registration count: {e}")
        return 0


def get_sheet_url() -> str:
    """Возвращает URL Google Sheets таблицы"""
    return f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}"

def get_all_registered_ids() -> set:
    """Возвращает set всех user_id из Google Sheets одним запросом"""
    try:
        worksheet = get_worksheet()
        user_ids = worksheet.col_values(1)  # один запрос к API
        # убираем заголовок "User ID"
        if user_ids and user_ids[0] == "User ID":
            user_ids = user_ids[1:]
        return set(str(uid) for uid in user_ids if uid)
    except Exception as e:
        logger.error(f"Error getting all registered ids: {e}")
        return set()
