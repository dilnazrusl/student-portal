"""
db_core.py
----------
Подключение к PostgreSQL и общие помощники для всех остальных db_*.py файлов.

Настройки подключения теперь НЕ лежат в коде (пароль в коде = пароль на GitHub).
Они берутся по порядку из:
  1) переменных окружения (Render и т.п.),
  2) секретов Streamlit (.streamlit/secrets.toml локально / раздел Secrets на Streamlit Cloud),
  3) значений по умолчанию — это твоя локальная база, как раньше.

Нужные ключи: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SSLMODE.
"""

import os
from contextlib import contextmanager

import psycopg2


def _get(name, default=None):
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return default


DB_CONFIG = {
    "host": _get("DB_HOST", "localhost"),
    "port": int(_get("DB_PORT", 5432)),
    "dbname": _get("DB_NAME", "universety"),
    "user": _get("DB_USER", "postgres"),
    "password": _get("DB_PASSWORD", "postgres"),
    "sslmode": _get("DB_SSLMODE", "prefer"),   # для Neon в секретах поставь "require"
    "connect_timeout": 20,                      # Neon «просыпается» пару секунд после простоя
}


def get_connection():
    """Открывает новое подключение к базе данных."""
    return psycopg2.connect(**DB_CONFIG)


def fetch_all(query, params=()):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()
    finally:
        conn.close()


def fetch_one(query, params=()):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()
    finally:
        conn.close()


@contextmanager
def transaction():
    """
    Одна транзакция: либо все изменения сохраняются (commit),
    либо при ошибке откатываются целиком (rollback).
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def log_staff_action(cur, staff, action, target_type, target_id, target_name, details):
    """Записывает действие сотрудника в журнал staff_action_log (в той же транзакции)."""
    cur.execute(
        """
        INSERT INTO staff_action_log
            (staff_id, staff_name, department, action, target_type, target_id, target_name, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (staff["staff_id"], staff["name"], staff["department"],
         action, target_type, target_id, target_name, details),
    )


def allocate_id(cur, table, id_col):
    """
    Следующий свободный ID: «последний + 1».
    Берём значение из последовательности, но не меньше максимального ID в таблице + 1.
    """
    cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (table, id_col))
    seq = cur.fetchone()[0]
    cur.execute("SELECT nextval(%s)", (seq,))
    nxt = cur.fetchone()[0]
    cur.execute(f"SELECT COALESCE(MAX({id_col}), 0) FROM {table}")
    mx = cur.fetchone()[0]
    if nxt <= mx:
        nxt = mx + 1
        cur.execute("SELECT setval(%s, %s)", (seq, nxt))
    return nxt
