# db.py — база FindFood 3.1
import sqlite3
from contextlib import closing
from typing import Optional

DB_PATH = "foodmate.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with closing(get_conn()) as conn, conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER UNIQUE,
            name TEXT,
            age INTEGER,
            city TEXT,
            locale TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS recipes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            ingredients TEXT,
            steps TEXT,
            category TEXT,
            cuisine TEXT,
            reaction TEXT,
            tags TEXT,
            keywords TEXT,
            likes INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS restaurants(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            city TEXT,
            address TEXT,
            cuisine TEXT,
            rating REAL DEFAULT 4.5,
            contact TEXT,
            tags TEXT,
            reaction TEXT,
            keywords TEXT
        );

        CREATE TABLE IF NOT EXISTS favorites(
            chat_id INTEGER,
            recipe_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_history(
            chat_id INTEGER,
            item_id INTEGER,
            item_type TEXT,
            category TEXT,
            liked INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_tastes(
            chat_id INTEGER,
            category TEXT,
            likes INTEGER DEFAULT 0,
            dislikes INTEGER DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chat_id, category)
        );

        CREATE TABLE IF NOT EXISTS user_preferences(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            last_mode TEXT,
            last_category TEXT,
            last_query TEXT,
            liked_count INTEGER DEFAULT 0,
            disliked_count INTEGER DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS synonyms(
            word TEXT PRIMARY KEY,
            alt_words TEXT
        );

        CREATE TABLE IF NOT EXISTS qa(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT UNIQUE,
            answer TEXT,
            image TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS feedback(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT,
            answer TEXT,
            user_id INTEGER,
            liked INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS ai_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            question TEXT,
            answer TEXT,
            status TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Мягкие миграции под существующие данные
        for ddl in (
            "ALTER TABLE users ADD COLUMN age INTEGER",
            "ALTER TABLE users ADD COLUMN locale TEXT",
            "ALTER TABLE recipes ADD COLUMN likes INTEGER DEFAULT 0",
            "ALTER TABLE recipes ADD COLUMN cuisine TEXT",
            "ALTER TABLE recipes ADD COLUMN reaction TEXT",
            "ALTER TABLE recipes ADD COLUMN tags TEXT",
            "ALTER TABLE recipes ADD COLUMN keywords TEXT",
            "ALTER TABLE restaurants ADD COLUMN contact TEXT",
            "ALTER TABLE restaurants ADD COLUMN reaction TEXT",
            "ALTER TABLE restaurants ADD COLUMN keywords TEXT",
            "ALTER TABLE user_history ADD COLUMN item_id INTEGER",
            "ALTER TABLE user_history ADD COLUMN item_type TEXT",
            "ALTER TABLE user_history ADD COLUMN liked INTEGER DEFAULT 0"
        ):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass

        # Индексы могут ссылаться на добавленные позже колонки — создаём их после миграций.
        for ddl in (
            "CREATE INDEX IF NOT EXISTS idx_recipes_tags ON recipes(tags)",
            "CREATE INDEX IF NOT EXISTS idx_recipes_keywords ON recipes(keywords)",
            "CREATE INDEX IF NOT EXISTS idx_restaurants_city ON restaurants(city)",
            "CREATE INDEX IF NOT EXISTS idx_history_chat ON user_history(chat_id)",
            "CREATE INDEX IF NOT EXISTS idx_tastes_chat ON user_tastes(chat_id)",
            "CREATE INDEX IF NOT EXISTS idx_preferences_user ON user_preferences(user_id)"
        ):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass
    print("✅ DB initialized")


def upsert_user_preferences(user_id: int, *, mode: Optional[str] = None, category: Optional[str] = None, query: Optional[str] = None):
    with closing(get_conn()) as conn, conn:
        conn.execute(
            """
            INSERT INTO user_preferences(user_id, last_mode, last_category, last_query)
            VALUES (?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                last_mode = COALESCE(excluded.last_mode, user_preferences.last_mode),
                last_category = COALESCE(excluded.last_category, user_preferences.last_category),
                last_query = COALESCE(excluded.last_query, user_preferences.last_query),
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, mode, category, query),
        )


def increment_preference_feedback(user_id: int, liked: bool):
    with closing(get_conn()) as conn, conn:
        conn.execute(
            """
            INSERT INTO user_preferences(user_id, liked_count, disliked_count)
            VALUES (?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                liked_count = user_preferences.liked_count + ?,
                disliked_count = user_preferences.disliked_count + ?,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                1 if liked else 0,
                0 if liked else 1,
                1 if liked else 0,
                0 if liked else 1,
            ),
        )
