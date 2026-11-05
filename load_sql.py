"""
load_sql.py — загружает весь SQL-файл в базу одним запуском.
Запуск:  python load_sql.py update_db_neon.sql
Берёт подключение из тех же настроек, что и приложение (db_core.py).
"""
import sys
import psycopg2
from db_core import DB_CONFIG

path = sys.argv[1] if len(sys.argv) > 1 else "update_db_neon.sql"
sql = open(path, encoding="utf-8").read()

conn = psycopg2.connect(**DB_CONFIG)
try:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.student')")
        if cur.fetchone()[0] is not None:
            sys.exit("Таблица student уже есть — файл уже загружен. Повторно запускать его не нужно.")
        cur.execute(sql)          # весь файл одной транзакцией: либо всё, либо ничего
    conn.commit()
    print("Готово: база создана и заполнена.")
except Exception as exc:
    conn.rollback()
    sys.exit(f"Ошибка, ничего не сохранено:\n{exc}")
finally:
    conn.close()
