# db.py — база FindFood 3.1
import sqlite3
import time
from contextlib import closing
from typing import Optional

DB_PATH = "foodmate.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with closing(get_conn()) as conn, conn:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        # Миграция старой таблицы feedback -> ai_feedback
        legacy_feedback = False
        try:
            cols = conn.execute("PRAGMA table_info(feedback)").fetchall()
            column_names = {col[1] for col in cols}
            legacy_feedback = bool(column_names) and "feedback_type" not in column_names and "question" in column_names
        except sqlite3.OperationalError:
            legacy_feedback = False
        if legacy_feedback:
            conn.execute("ALTER TABLE feedback RENAME TO ai_feedback")

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
            likes INTEGER DEFAULT 0,
            popularity INTEGER DEFAULT 1,
            title_en TEXT,
            ingredients_en TEXT,
            steps_en TEXT,
            photo_url TEXT
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
            keywords TEXT,
            category TEXT,
            description TEXT,
            photo_url TEXT,
            latitude REAL,
            longitude REAL
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

        CREATE TABLE IF NOT EXISTS ai_feedback(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT,
            answer TEXT,
            user_id INTEGER,
            liked INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS feedback(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_id INTEGER,
            item_type TEXT,
            feedback_type TEXT CHECK(feedback_type IN ('like', 'dislike', 'next')),
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

        CREATE TABLE IF NOT EXISTS user_state(
            user_id INTEGER PRIMARY KEY,
            category TEXT,
            mode TEXT,
            city TEXT,
            last_action TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
            "ALTER TABLE recipes ADD COLUMN popularity INTEGER DEFAULT 1",
            "ALTER TABLE recipes ADD COLUMN title_en TEXT",
            "ALTER TABLE recipes ADD COLUMN ingredients_en TEXT",
            "ALTER TABLE recipes ADD COLUMN steps_en TEXT",
            "ALTER TABLE recipes ADD COLUMN photo_url TEXT",
            "ALTER TABLE restaurants ADD COLUMN contact TEXT",
            "ALTER TABLE restaurants ADD COLUMN reaction TEXT",
            "ALTER TABLE restaurants ADD COLUMN keywords TEXT",
            "ALTER TABLE restaurants ADD COLUMN category TEXT",
            "ALTER TABLE restaurants ADD COLUMN description TEXT",
            "ALTER TABLE restaurants ADD COLUMN photo_url TEXT",
            "ALTER TABLE restaurants ADD COLUMN latitude REAL",
            "ALTER TABLE restaurants ADD COLUMN longitude REAL",
            "ALTER TABLE user_history ADD COLUMN item_id INTEGER",
            "ALTER TABLE user_history ADD COLUMN item_type TEXT",
            "ALTER TABLE user_history ADD COLUMN liked INTEGER DEFAULT 0",
            "ALTER TABLE user_state ADD COLUMN city TEXT"
        ):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass

        # Индексы могут ссылаться на добавленные позже колонки — создаём их после миграций.
        for ddl in (
            "CREATE INDEX IF NOT EXISTS idx_recipes_tags ON recipes(tags)",
            "CREATE INDEX IF NOT EXISTS idx_recipes_keywords ON recipes(keywords)",
            "CREATE INDEX IF NOT EXISTS idx_recipes_category ON recipes(category)",
            "CREATE INDEX IF NOT EXISTS idx_restaurants_city ON restaurants(city)",
            "CREATE INDEX IF NOT EXISTS idx_restaurants_category ON restaurants(category)",
            "CREATE INDEX IF NOT EXISTS idx_restaurants_tags ON restaurants(tags)",
            "CREATE INDEX IF NOT EXISTS idx_restaurants_keywords ON restaurants(keywords)",
            "CREATE INDEX IF NOT EXISTS idx_history_chat ON user_history(chat_id)",
            "CREATE INDEX IF NOT EXISTS idx_tastes_chat ON user_tastes(chat_id)",
            "CREATE INDEX IF NOT EXISTS idx_preferences_user ON user_preferences(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_state_category ON user_state(category)"
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


def increment_preference_feedback(user_id: int, liked: bool, conn: Optional[sqlite3.Connection] = None, retries: int = 3):
    payload = (
        user_id,
        1 if liked else 0,
        0 if liked else 1,
        1 if liked else 0,
        0 if liked else 1,
    )

    def _execute(target_conn: sqlite3.Connection):
        target_conn.execute(
            """
            INSERT INTO user_preferences(user_id, liked_count, disliked_count)
            VALUES (?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                liked_count = user_preferences.liked_count + ?,
                disliked_count = user_preferences.disliked_count + ?,
                updated_at = CURRENT_TIMESTAMP
            """,
            payload,
        )

    if conn is not None:
        _execute(conn)
        return

    for attempt in range(retries):
        try:
            with closing(get_conn()) as owned_conn, owned_conn:
                _execute(owned_conn)
            return
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() and attempt < retries - 1:
                time.sleep(0.2 * (attempt + 1))
                continue
            raise


def load_user_state(user_id: int) -> dict:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT user_id, category, mode, city, last_action FROM user_state WHERE user_id=?",
            (user_id,),
        ).fetchone()
    if not row:
        return {"user_id": user_id, "category": None, "mode": None, "city": None, "last_action": None}
    return dict(row)


def save_user_state(
    user_id: int,
    *,
    category: Optional[str] = None,
    mode: Optional[str] = None,
    city: Optional[str] = None,
    last_action: Optional[str] = None,
):
    with closing(get_conn()) as conn, conn:
        conn.execute(
            """
            INSERT INTO user_state(user_id, category, mode, city, last_action)
            VALUES (?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                category = COALESCE(excluded.category, user_state.category),
                mode = COALESCE(excluded.mode, user_state.mode),
                city = COALESCE(excluded.city, user_state.city),
                last_action = COALESCE(excluded.last_action, user_state.last_action),
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, category, mode, city, last_action),
        )


def clear_user_state(user_id: int):
    with closing(get_conn()) as conn, conn:
        conn.execute("DELETE FROM user_state WHERE user_id=?", (user_id,))


def log_item_feedback(
    user_id: int,
    item_id: Optional[int],
    item_type: str,
    feedback_type: str,
    conn: Optional[sqlite3.Connection] = None,
    retries: int = 3,
):
    def _execute(target_conn: sqlite3.Connection):
        target_conn.execute(
            """
            INSERT INTO feedback(user_id, item_id, item_type, feedback_type)
            VALUES (?,?,?,?)
            """,
            (user_id, item_id, item_type, feedback_type),
        )

    if conn is not None:
        _execute(conn)
        return

    for attempt in range(retries):
        try:
            with closing(get_conn()) as owned_conn, owned_conn:
                _execute(owned_conn)
            return
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() and attempt < retries - 1:
                time.sleep(0.2 * (attempt + 1))
                continue
            raise
