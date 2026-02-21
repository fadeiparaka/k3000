"""
Модуль для работы с SQLite базой данных пользователей бота
"""
import sqlite3
import logging
from datetime import datetime
from typing import Optional, List, Tuple
from config import DATABASE_PATH, TIMEZONE
import pytz

logger = logging.getLogger(__name__)

moscow_tz = pytz.timezone(TIMEZONE)


def get_db_connection():
    """Создает соединение с базой данных"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Инициализирует таблицы users и user_consent в базе данных"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_seen_at TEXT NOT NULL,
            last_activity_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_consent (
            user_id INTEGER PRIMARY KEY,
            consented_at TEXT NOT NULL
        )
    """)
    conn.commit()
    
    # Проверяем, что таблицы созданы
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    logger.info(f"Database initialized. Tables: {', '.join(tables)}")


def add_or_update_user(user_id: int, username: Optional[str] = None):
    """
    Добавляет или обновляет пользователя в базе данных.
    При первом добавлении устанавливает first_seen_at и last_activity_at.
    При обновлении обновляет username и last_activity_at.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.now(moscow_tz).isoformat()
    
    # Проверяем, существует ли пользователь
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    existing = cursor.fetchone()
    
    if existing:
        # Обновляем существующего пользователя
        cursor.execute("""
            UPDATE users 
            SET username = ?, last_activity_at = ?
            WHERE user_id = ?
        """, (username, now, user_id))
    else:
        # Добавляем нового пользователя
        cursor.execute("""
            INSERT INTO users (user_id, username, first_seen_at, last_activity_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, username, now, now))
    
    conn.commit()
    conn.close()
    logger.info(f"User {user_id} added/updated in database")


def update_user_activity(user_id: int):
    """Обновляет last_activity_at для пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.now(moscow_tz).isoformat()
    cursor.execute("""
        UPDATE users 
        SET last_activity_at = ?
        WHERE user_id = ?
    """, (now, user_id))
    
    conn.commit()
    conn.close()


def remove_user(user_id: int):
    """Удаляет пользователя из базы данных (при блокировке бота)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    
    conn.commit()
    conn.close()
    logger.info(f"User {user_id} removed from database")


def get_all_users() -> List[Tuple[int, Optional[str]]]:
    """Возвращает список всех пользователей (user_id, username)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id, username FROM users")
    users = cursor.fetchall()
    
    conn.close()
    return [(row[0], row[1]) for row in users]


def set_user_consented(user_id: int):
    """Отмечает, что пользователь дал согласие на обработку данных"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Проверяем существование таблицы и создаём если её нет (миграция для старых баз)
    try:
        cursor.execute("SELECT 1 FROM user_consent LIMIT 1")
    except sqlite3.OperationalError:
        # Таблица не существует — создаём её
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_consent (
                user_id INTEGER PRIMARY KEY,
                consented_at TEXT NOT NULL
            )
        """)
        conn.commit()
    
    now = datetime.now(moscow_tz).isoformat()
    cursor.execute(
        "INSERT OR REPLACE INTO user_consent (user_id, consented_at) VALUES (?, ?)",
        (user_id, now)
    )
    conn.commit()
    conn.close()
    logger.info(f"User {user_id} consent recorded")


def has_user_consented(user_id: int) -> bool:
    """Проверяет, дал ли пользователь согласие"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Проверяем существование таблицы и создаём если её нет (миграция для старых баз)
    try:
        cursor.execute("SELECT 1 FROM user_consent WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
    except sqlite3.OperationalError:
        # Таблица не существует — создаём её
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_consent (
                user_id INTEGER PRIMARY KEY,
                consented_at TEXT NOT NULL
            )
        """)
        conn.commit()
        result = None
    
    conn.close()
    return result is not None


def get_user_count() -> int:
    """Возвращает количество пользователей в базе"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as count FROM users")
    count = cursor.fetchone()[0]
    
    conn.close()
    return count
