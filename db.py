# db.py — схема БД FindFood 3.0
import sqlite3
from contextlib import closing

DB_PATH = "foodmate.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with closing(get_conn()) as conn, conn:
        # Пользователи
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER UNIQUE,
            name TEXT,
            city TEXT,
            favorite_taste TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)
        # Рецепты
        conn.execute("""
        CREATE TABLE IF NOT EXISTS recipes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            ingredients TEXT NOT NULL,
            steps TEXT NOT NULL,
            category TEXT,            -- sweet, salty, spicy, neutral
            cuisine TEXT,
            reaction TEXT,            -- имя png в /images
            tags TEXT,                -- "пицца;сыр;итальянская"
            keywords TEXT,            -- расширенные синонимы
            likes INTEGER DEFAULT 0
        );
        """)
        # Заведения
        conn.execute("""
        CREATE TABLE IF NOT EXISTS restaurants(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            city TEXT NOT NULL,
            address TEXT NOT NULL,
            cuisine TEXT,
            rating REAL DEFAULT 4.5,
            contact TEXT,
            tags TEXT,
            reaction TEXT,
            keywords TEXT,
            likes INTEGER DEFAULT 0
        );
        """)
        # Избранное
        conn.execute("""
        CREATE TABLE IF NOT EXISTS favorites(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            recipe_id INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chat_id, recipe_id)
        );
        """)
        # Логи
        conn.execute("""
        CREATE TABLE IF NOT EXISTS logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_query TEXT,
            bot_reply TEXT,
            meta TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)
    print("✅ DB ready")
