# db.py — база FindFood 3.1
import sqlite3
from contextlib import closing

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

        CREATE TABLE IF NOT EXISTS synonyms(
            word TEXT PRIMARY KEY,
            alt_words TEXT
        );
        """)

        # Мягкие миграции под существующие данные
        for ddl in (
            "ALTER TABLE users ADD COLUMN age INTEGER",
            "ALTER TABLE users ADD COLUMN locale TEXT",
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
            "CREATE INDEX IF NOT EXISTS idx_tastes_chat ON user_tastes(chat_id)"
        ):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass
    print("✅ DB initialized")
