"""
Модуль для работы с SQLite базой данных пользователей бота
"""
import sqlite3
import logging
from datetime import datetime
from typing import Optional, List, Tuple, Any
from config import DATABASE_PATH, TIMEZONE, EARLY_ACCESS_LINK
import pytz

logger = logging.getLogger(__name__)

moscow_tz = pytz.timezone(TIMEZONE)


def get_db_connection():
    """Создает соединение с базой данных"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Инициализирует таблицы бота"""
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS early_access (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """) 

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS menu_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            menu_type TEXT NOT NULL DEFAULT 'inline',
            parent_id INTEGER,
            title TEXT NOT NULL,
            style TEXT,
            kind TEXT NOT NULL DEFAULT 'message',
            url TEXT,
            action TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            content_type TEXT,
            text TEXT,
            entities_json TEXT,
            caption TEXT,
            caption_entities_json TEXT,
            media_file_id TEXT,
            has_spoiler INTEGER NOT NULL DEFAULT 0,
            show_caption_above_media INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER,
            updated_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS menu_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            media_type TEXT NOT NULL,
            file_id TEXT NOT NULL,
            caption TEXT,
            caption_entities_json TEXT,
            has_spoiler INTEGER NOT NULL DEFAULT 0,
            show_caption_above_media INTEGER NOT NULL DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_reply_menu_state (
            user_id INTEGER PRIMARY KEY,
            parent_id INTEGER,
            updated_at TEXT NOT NULL
        )
    """)

    _ensure_menu_schema(cursor)
    _ensure_menu_seed(cursor)
    conn.commit()
    
    # Проверяем, что таблицы созданы
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    logger.info(f"Database initialized. Tables: {', '.join(tables)}")


def _now_iso() -> str:
    return datetime.now(moscow_tz).isoformat()


def _ensure_menu_schema(cursor: sqlite3.Cursor):
    cursor.execute("PRAGMA table_info(menu_nodes)")
    columns = {row["name"] for row in cursor.fetchall()}
    if "menu_type" not in columns:
        cursor.execute("ALTER TABLE menu_nodes ADD COLUMN menu_type TEXT NOT NULL DEFAULT 'inline'")


def _ensure_menu_seed(cursor: sqlite3.Cursor):
    """Создаёт стартовое динамическое меню только один раз для старых баз."""
    cursor.execute("SELECT value FROM bot_settings WHERE key = 'dynamic_menu_seeded'")
    if cursor.fetchone():
        return

    now = _now_iso()
    cursor.execute(
        "INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)",
        ("main_greeting", "Салют, это бот К-30! Что тебя интересует?")
    )

    cursor.execute("""
        INSERT INTO menu_nodes (
            menu_type, parent_id, title, style, kind, sort_order, content_type, text,
            entities_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "inline",
        None,
        "Ранний доступ на Формы Прослушивания (13.03)",
        None,
        "message",
        10,
        "text",
        "Поздравляем, ты получил ранний доступ к вечеринке Формы Прослушивания.\n\n"
        "Что это значит?\n\n"
        "• Мы пришлем ссылку на приобретение билета всего за 500 рублей\n"
        "• Ссылка может перестать работать в любой момент, не откладывай\n"
        "• Вход по таким билетам возможен только до 00:30 в ночь события\n"
        "• Билет придет на почту, которую ты укажешь при покупке",
        None,
        now,
        now,
    ))
    early_access_id = cursor.lastrowid

    cursor.execute("""
        INSERT INTO menu_nodes (
            menu_type, parent_id, title, style, kind, action, sort_order, content_type, text,
            entities_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "inline",
        early_access_id,
        "Получить секретную ссылку",
        None,
        "message",
        "early_access",
        10,
        "text",
        f"А вот и заветная ссылка 👉 {EARLY_ACCESS_LINK}",
        None,
        now,
        now,
    ))

    cursor.execute("""
        INSERT INTO menu_nodes (
            menu_type, parent_id, title, style, kind, sort_order, content_type, text,
            entities_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "inline",
        None,
        "Получить фотоотчёт",
        None,
        "message",
        20,
        "text",
        "Фотоотчёт «Новый Свет»\n\nПосмотреть",
        '[{"type":"text_link","offset":24,"length":10,"url":"https://disk.yandex.ru/d/8imwOmqTqyIlmg"}]',
        now,
        now,
    ))

    cursor.execute(
        "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
        ("dynamic_menu_seeded", "1")
    )


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
        (key, value)
    )
    conn.commit()
    conn.close()


def get_main_greeting() -> str:
    return get_setting("main_greeting", "Салют, это бот К-30! Что тебя интересует?") or "Салют, это бот К-30! Что тебя интересует?"


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def list_menu_children(parent_id: int | None, menu_type: str = "inline") -> list[dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    if parent_id is None:
        cursor.execute("""
            SELECT * FROM menu_nodes
            WHERE parent_id IS NULL AND menu_type = ?
            ORDER BY sort_order, id
        """, (menu_type,))
    else:
        cursor.execute("""
            SELECT * FROM menu_nodes
            WHERE parent_id = ? AND menu_type = ?
            ORDER BY sort_order, id
        """, (parent_id, menu_type))
    rows = [_row_to_dict(row) for row in cursor.fetchall()]
    conn.close()
    return [row for row in rows if row is not None]


def get_menu_node(node_id: int) -> dict[str, Any] | None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM menu_nodes WHERE id = ?", (node_id,))
    row = _row_to_dict(cursor.fetchone())
    conn.close()
    return row


def get_menu_media(node_id: int) -> list[dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM menu_media
        WHERE node_id = ?
        ORDER BY position, id
    """, (node_id,))
    rows = [_row_to_dict(row) for row in cursor.fetchall()]
    conn.close()
    return [row for row in rows if row is not None]


def create_menu_node(
    parent_id: int | None,
    title: str,
    style: str | None,
    kind: str,
    created_by: int | None,
    url: str | None = None,
    menu_type: str = "inline",
) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    if parent_id is None:
        cursor.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM menu_nodes WHERE parent_id IS NULL AND menu_type = ?",
            (menu_type,)
        )
    else:
        cursor.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM menu_nodes WHERE parent_id = ? AND menu_type = ?",
            (parent_id, menu_type)
        )
    sort_order = int(cursor.fetchone()[0] or 0) + 10
    now = _now_iso()
    cursor.execute("""
        INSERT INTO menu_nodes (
            menu_type, parent_id, title, style, kind, url, sort_order,
            created_by, updated_by, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (menu_type, parent_id, title, style, kind, url, sort_order, created_by, created_by, now, now))
    node_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return int(node_id)


def update_menu_button(node_id: int, title: str, style: str | None, updated_by: int | None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE menu_nodes
        SET title = ?, style = ?, updated_by = ?, updated_at = ?
        WHERE id = ?
    """, (title, style, updated_by, _now_iso(), node_id))
    conn.commit()
    conn.close()


def update_menu_url(node_id: int, url: str, updated_by: int | None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE menu_nodes
        SET kind = 'url', url = ?, updated_by = ?, updated_at = ?
        WHERE id = ?
    """, (url, updated_by, _now_iso(), node_id))
    cursor.execute("DELETE FROM menu_media WHERE node_id = ?", (node_id,))
    conn.commit()
    conn.close()


def update_menu_content(
    node_id: int,
    content_type: str,
    text: str | None,
    entities_json: str | None,
    caption: str | None,
    caption_entities_json: str | None,
    media_file_id: str | None,
    has_spoiler: bool,
    show_caption_above_media: bool,
    updated_by: int | None,
):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE menu_nodes
        SET kind = 'message',
            url = NULL,
            content_type = ?,
            text = ?,
            entities_json = ?,
            caption = ?,
            caption_entities_json = ?,
            media_file_id = ?,
            has_spoiler = ?,
            show_caption_above_media = ?,
            updated_by = ?,
            updated_at = ?
        WHERE id = ?
    """, (
        content_type,
        text,
        entities_json,
        caption,
        caption_entities_json,
        media_file_id,
        1 if has_spoiler else 0,
        1 if show_caption_above_media else 0,
        updated_by,
        _now_iso(),
        node_id,
    ))
    cursor.execute("DELETE FROM menu_media WHERE node_id = ?", (node_id,))
    conn.commit()
    conn.close()


def replace_menu_album(node_id: int, media_items: list[dict[str, Any]], updated_by: int | None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE menu_nodes
        SET kind = 'message',
            url = NULL,
            content_type = 'album',
            text = NULL,
            entities_json = NULL,
            caption = NULL,
            caption_entities_json = NULL,
            media_file_id = NULL,
            has_spoiler = 0,
            show_caption_above_media = 0,
            updated_by = ?,
            updated_at = ?
        WHERE id = ?
    """, (updated_by, _now_iso(), node_id))
    cursor.execute("DELETE FROM menu_media WHERE node_id = ?", (node_id,))
    for item in media_items:
        cursor.execute("""
            INSERT INTO menu_media (
                node_id, position, media_type, file_id, caption,
                caption_entities_json, has_spoiler, show_caption_above_media
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            node_id,
            item["position"],
            item["media_type"],
            item["file_id"],
            item.get("caption"),
            item.get("caption_entities_json"),
            1 if item.get("has_spoiler") else 0,
            1 if item.get("show_caption_above_media") else 0,
        ))
    conn.commit()
    conn.close()


def delete_menu_subtree(node_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()

    def collect(current_id: int) -> list[int]:
        cursor.execute("SELECT id FROM menu_nodes WHERE parent_id = ?", (current_id,))
        ids = [int(row[0]) for row in cursor.fetchall()]
        result = [current_id]
        for child_id in ids:
            result.extend(collect(child_id))
        return result

    ids_to_delete = collect(node_id)
    placeholders = ",".join("?" for _ in ids_to_delete)
    cursor.execute(f"DELETE FROM menu_media WHERE node_id IN ({placeholders})", ids_to_delete)
    cursor.execute(f"DELETE FROM menu_nodes WHERE id IN ({placeholders})", ids_to_delete)
    conn.commit()
    conn.close()


def menu_node_has_children(node_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM menu_nodes WHERE parent_id = ? LIMIT 1", (node_id,))
    result = cursor.fetchone() is not None
    conn.close()
    return result


def find_menu_child_by_title(parent_id: int | None, title: str, menu_type: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    cursor = conn.cursor()
    if parent_id is None:
        cursor.execute("""
            SELECT * FROM menu_nodes
            WHERE parent_id IS NULL AND menu_type = ? AND title = ?
            ORDER BY sort_order, id
            LIMIT 1
        """, (menu_type, title))
    else:
        cursor.execute("""
            SELECT * FROM menu_nodes
            WHERE parent_id = ? AND menu_type = ? AND title = ?
            ORDER BY sort_order, id
            LIMIT 1
        """, (parent_id, menu_type, title))
    row = _row_to_dict(cursor.fetchone())
    conn.close()
    return row


def get_user_reply_menu_parent(user_id: int) -> int | None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT parent_id FROM user_reply_menu_state WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row["parent_id"] if row else None


def set_user_reply_menu_parent(user_id: int, parent_id: int | None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO user_reply_menu_state (user_id, parent_id, updated_at)
        VALUES (?, ?, ?)
    """, (user_id, parent_id, _now_iso()))
    conn.commit()
    conn.close()


def get_menu_path(node_id: int | None) -> str:
    if node_id is None:
        return "/приветствие"

    conn = get_db_connection()
    cursor = conn.cursor()
    titles: list[str] = []
    current_id: int | None = node_id
    while current_id is not None:
        cursor.execute("SELECT parent_id, title FROM menu_nodes WHERE id = ?", (current_id,))
        row = cursor.fetchone()
        if not row:
            break
        titles.append(str(row["title"]).lower())
        current_id = row["parent_id"]
    conn.close()
    return "/приветствие" + "".join(f"/{title}" for title in reversed(titles))



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

def init_early_access_table():
    """Создаёт таблицу early_access если не существует"""
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS early_access (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        logger.info("Table early_access ready")


def add_early_access_user(user_id: int, username: Optional[str] = None) -> bool:
    """Добавляет пользователя в early_access. Возвращает True если добавлен впервые"""
    try:
        with sqlite3.connect(DATABASE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO early_access (user_id, username) VALUES (?, ?)",
                (user_id, username)
            )
            conn.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error adding early access user {user_id}: {e}")
        return False


def is_early_access_user(user_id: int) -> bool:
    """Проверяет, получал ли пользователь уже ссылку"""
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM early_access WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None


def get_all_early_access_users() -> list:
    """Возвращает всех пользователей из early_access"""
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username FROM early_access")
        return cursor.fetchall()
