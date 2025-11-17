from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

DB_PATH = (Path(__file__).resolve().parent.parent / "foodmate.db").resolve()
ALLOWED_TABLES = {"qa", "ai_logs", "ai_feedback", "restaurants", "dialogs", "dialog_questions", "admins"}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if column not in {row[1] for row in info}:
        conn.execute(ddl)


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        _ensure_column(conn, "qa", "type", "ALTER TABLE qa ADD COLUMN type TEXT")
        _ensure_column(conn, "qa", "is_active", "ALTER TABLE qa ADD COLUMN is_active INTEGER DEFAULT 1")
        conn.execute("UPDATE qa SET type = COALESCE(type, 'general') WHERE type IS NULL")
        conn.execute("UPDATE qa SET is_active = 1 WHERE is_active IS NULL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dialogs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                is_active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dialog_questions(
                dialog_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                order_num INTEGER DEFAULT 1,
                PRIMARY KEY(dialog_id, question_id),
                FOREIGN KEY(dialog_id) REFERENCES dialogs(id) ON DELETE CASCADE,
                FOREIGN KEY(question_id) REFERENCES qa(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admins(
                login TEXT PRIMARY KEY,
                password TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dialog_questions_dialog ON dialog_questions(dialog_id, order_num)"
        )
        has_admin = conn.execute("SELECT COUNT(1) FROM admins").fetchone()[0]
        if not has_admin:
            conn.execute("INSERT OR IGNORE INTO admins(login, password) VALUES (?, ?)", ("admin", "admin"))


def _validate_table(table: str) -> None:
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Access to table '{table}' is not allowed")


def select_all(
    table: str,
    where: Optional[str] = None,
    params: Optional[Sequence[Any]] = None,
    *,
    order_by: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    _validate_table(table)
    query = f"SELECT * FROM {table}"
    if where:
        query += f" WHERE {where}"
    if order_by:
        query += f" ORDER BY {order_by}"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    with get_conn() as conn:
        cur = conn.execute(query, params or [])
        return [dict(row) for row in cur.fetchall()]


def select_one(table: str, where: str, params: Sequence[Any]) -> Optional[Dict[str, Any]]:
    results = select_all(table, where, params, limit=1)
    return results[0] if results else None


def insert(table: str, data: Dict[str, Any]) -> int:
    _validate_table(table)
    columns = ",".join(data.keys())
    placeholders = ",".join(["?"] * len(data))
    query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
    values = list(data.values())
    with get_conn() as conn:
        cursor = conn.execute(query, values)
        return cursor.lastrowid


def update(table: str, data: Dict[str, Any], where: str, params: Sequence[Any]) -> None:
    _validate_table(table)
    assignments = ",".join([f"{column}=?" for column in data])
    query = f"UPDATE {table} SET {assignments} WHERE {where}"
    values: List[Any] = list(data.values()) + list(params)
    with get_conn() as conn:
        conn.execute(query, values)


def delete(table: str, where: str, params: Sequence[Any]) -> None:
    _validate_table(table)
    query = f"DELETE FROM {table} WHERE {where}"
    with get_conn() as conn:
        conn.execute(query, list(params))


def fetch_dialog_questions(dialog_id: int) -> List[Dict[str, Any]]:
    query = (
        "SELECT dq.dialog_id, dq.question_id, dq.order_num, q.question, q.type, q.is_active "
        "FROM dialog_questions dq "
        "JOIN qa q ON q.id = dq.question_id "
        "WHERE dq.dialog_id=? ORDER BY dq.order_num"
    )
    with get_conn() as conn:
        cur = conn.execute(query, (dialog_id,))
        return [dict(row) for row in cur.fetchall()]


def next_order_num(dialog_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(order_num), 0) + 1 AS next_val FROM dialog_questions WHERE dialog_id=?",
            (dialog_id,),
        ).fetchone()
        if row is None:
            return 1
        return int(row["next_val"] if isinstance(row, sqlite3.Row) else row[0])


def swap_order(dialog_id: int, question_id_a: int, question_id_b: int) -> None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT order_num FROM dialog_questions WHERE dialog_id=? AND question_id=?",
            (dialog_id, question_id_a),
        ).fetchone()
        other = conn.execute(
            "SELECT order_num FROM dialog_questions WHERE dialog_id=? AND question_id=?",
            (dialog_id, question_id_b),
        ).fetchone()
        if not row or not other:
            return
        conn.execute(
            "UPDATE dialog_questions SET order_num=? WHERE dialog_id=? AND question_id=?",
            (other["order_num"], dialog_id, question_id_a),
        )
        conn.execute(
            "UPDATE dialog_questions SET order_num=? WHERE dialog_id=? AND question_id=?",
            (row["order_num"], dialog_id, question_id_b),
        )


init_db()
