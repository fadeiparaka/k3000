"""
Конфигурация бота К-30
"""
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from typing import List

# Определяем корневую директорию проекта (где находится config.py)
BASE_DIR = Path(__file__).parent.absolute()

# Загружаем .env из корня проекта
env_path = BASE_DIR / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()  # Fallback на стандартный поиск

# Telegram Bot Token
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Google Sheets Configuration
_credentials_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "credentials.json")
# Если путь относительный, делаем его относительно корня проекта
if not os.path.isabs(_credentials_path):
    GOOGLE_SHEETS_CREDENTIALS_PATH = str(BASE_DIR / _credentials_path)
else:
    GOOGLE_SHEETS_CREDENTIALS_PATH = _credentials_path
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

# Admin User IDs (парсим с защитой от некорректных значений)
ADMINS_STR = os.getenv("ADMINS", "")
ADMINS: List[int] = []
if ADMINS_STR:
    for part in ADMINS_STR.split(","):
        part = part.strip()
        if part:
            try:
                ADMINS.append(int(part))
            except ValueError:
                pass

# Event Configuration
EVENT_DEADLINE_STR = os.getenv("EVENT_DEADLINE", "2026-02-26 18:00")
EVENT_DEADLINE = datetime.strptime(EVENT_DEADLINE_STR, "%Y-%m-%d %H:%M")
EVENT_DATE_STR = os.getenv("EVENT_DATE", "2026-02-27 10:00").strip()
# принимаем и "2026-02-27", и "2026-02-27 10:00" — берём только дату
EVENT_DATE = datetime.strptime(EVENT_DATE_STR[:10], "%Y-%m-%d").date()
EVENT_ANNOUNCE_LINK = os.getenv("EVENT_ANNOUNCE_LINK", "")

# Timezone
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

# Database (всегда в корне проекта)
DATABASE_PATH = str(BASE_DIR / "users.db")

# Reminder times (in Moscow timezone)
REMINDER_1_DATETIME = datetime(2026, 2, 26, 14, 0)  # 26 февраля в 14:00
REMINDER_2_DATETIME = datetime(2026, 2, 27, 14, 0)  # 27 февраля в 10:00

MAX_PARTICIPANTS = 750

# Early Access
EARLY_ACCESS_LINK = "https://vk.cc/cV7rah"
EARLY_ACCESS_REMINDER_DATETIME = datetime(2026, 6, 19, 13, 0)  # за день до дедлайна

# Lost Items
LOST_ITEMS_CHAT_ID = int(os.getenv("LOST_ITEMS_CHAT_ID", "0"))
