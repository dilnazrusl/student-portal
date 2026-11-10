"""
db_finance.py
-------------
Финансовый кабинет и бухгалтерия.

  • цена курса = кредиты × цена одного кредита (50 000 ₸, настройка в таблице app_setting);
  • у студента-платника есть баланс: стоимость его курсов, оплаты, остаток к оплате;
  • у студента на гранте оплаты и чеков нет (оплата не требуется);
  • бухгалтерия записывает оплаты, студент-платник прикладывает чеки (файлы).
"""

import psycopg2

import db_files
import storage
from constants import FUNDING_RU, PAYMENT_METHOD_RU
from db_core import fetch_all, fetch_one, log_staff_action, transaction


# ------------------------------------------------------------------ цены ----

def get_credit_price():
    row = fetch_one("SELECT setting_value FROM app_setting WHERE setting_key = 'credit_price_kzt'")
    return int(row[0]) if row else 50000


def get_course_prices():
    """{код курса: (кредиты, цена)}"""
    return {r[0]: (r[1], int(r[2])) for r in fetch_all(
        "SELECT course_code, credits, price_kzt FROM v_course_price")}


def get_funding(student_id):
    row = fetch_one("SELECT funding FROM student WHERE student_id = %s", (student_id,))
    return row[0] if row else None


# --------------------------------------------------------------- кабинет ----

def student_finance(student_id):
    """Всё для финансового кабинета (и для бухгалтера): курсы, цены, оплаты, остаток."""
    s = fetch_one("SELECT student_id, name, funding, status FROM student WHERE student_id = %s",
                  (student_id,))
    if s is None:
        return None
    courses = fetch_all(
        """
        SELECT e.course_code, p.course_name, p.credits, p.price_kzt, e.semester
        FROM enrollment e JOIN v_course_price p ON p.course_code = e.course_code
        WHERE e.student_id = %s ORDER BY e.semester DESC, e.course_code
        """, (student_id,))
    payments = fetch_all(
        """
        SELECT pay.payment_id, pay.paid_at, pay.amount, pay.method, pay.note, st.name
        FROM payment pay JOIN staff st ON st.staff_id = pay.recorded_by
        WHERE pay.student_id = %s ORDER BY pay.paid_at DESC, pay.payment_id DESC
        """, (student_id,))
    total = sum(int(c[3]) for c in courses)
    paid = sum(int(p[2]) for p in payments)
    return {
        "student_id": s[0], "name": s[1], "funding": s[2], "status": s[3],
        "courses": [{"course_code": c[0], "course_name": c[1], "credits": c[2],
                     "price": int(c[3]), "semester": c[4]} for c in courses],
        "payments": [{"payment_id": p[0], "paid_at": p[1], "amount": int(p[2]),
                      "method": PAYMENT_METHOD_RU.get(p[3], p[3]), "note": p[4] or "",
                      "staff": p[5]} for p in payments],
        "total": total, "paid": paid,
        "debt": max(total - paid, 0) if s[2] == "paid" else 0,
        "credit_price": get_credit_price(),
    }


def list_students_finance():
    """Для бухгалтера: все студенты, форма обучения и остаток."""
    rows = fetch_all("SELECT student_id, name, funding, total_kzt, paid_kzt FROM v_student_balance "
                     "ORDER BY name, student_id")
    return [{"id": r[0], "name": r[1], "funding": r[2], "total": int(r[3]), "paid": int(r[4]),
             "debt": max(int(r[3]) - int(r[4]), 0) if r[2] == "paid" else 0} for r in rows]


# ------------------------------------------------------------ форма обучения ----

def set_funding(staff, student_id, funding):
    """HR меняет форму обучения (платное / грант) и это пишется в журнал."""
    if funding not in FUNDING_RU:
        raise ValueError("Выбери форму обучения из списка.")
    with transaction() as cur:
        cur.execute("SELECT name, funding FROM student WHERE student_id = %s FOR UPDATE", (student_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Такого студента нет в базе.")
        name, old = row
        if old == funding:
            return False
        cur.execute("UPDATE student SET funding = %s WHERE student_id = %s", (funding, student_id))
        log_staff_action(cur, staff, "SET_FUNDING", "student", student_id, name,
                         f"Студент: {name} (ID {student_id})\n"
                         f"Форма обучения: {FUNDING_RU[old]} → {FUNDING_RU[funding]}")
    return True


# ------------------------------------------------------------------ оплаты ----

def add_payment(staff, student_id, amount, method, note, receipt_id=None):
    """Бухгалтер записывает оплату. Только для студентов-платников."""
    if method not in PAYMENT_METHOD_RU:
        raise ValueError("Выбери способ оплаты.")
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        raise ValueError("Введи сумму числом.")
    if amount <= 0:
        raise ValueError("Сумма должна быть больше нуля.")
    if amount > 100_000_000:
        raise ValueError("Слишком большая сумма — проверь, нет ли лишних нулей.")
    with transaction() as cur:
        cur.execute("SELECT name, funding FROM student WHERE student_id = %s FOR UPDATE", (student_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Такого студента нет в базе.")
        if row[1] != "paid":
            raise ValueError("Этот студент учится по гранту — оплата не требуется.")
        if receipt_id is not None:
            cur.execute("SELECT 1 FROM payment_receipt WHERE receipt_id = %s AND student_id = %s",
                        (receipt_id, student_id))
            if cur.fetchone() is None:
                raise ValueError("Этого чека нет у выбранного студента.")
        cur.execute(
            "INSERT INTO payment (student_id, amount, method, note, receipt_id, recorded_by) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (student_id, amount, method, (note or "").strip()[:200] or None, receipt_id, staff["staff_id"]))
        log_staff_action(cur, staff, "ADD_PAYMENT", "student", student_id, row[0],
                         f"Студент: {row[0]} (ID {student_id})\nСумма: {amount:,.0f} ₸\n"
                         f"Способ: {PAYMENT_METHOD_RU[method]}"
                         + (f"\nКомментарий: {note.strip()}" if note and note.strip() else ""))


# ------------------------------------------------------------------- чеки ----

def add_receipt(student_id, file_name, data):
    """Студент-платник прикладывает чек (файл)."""
    stored = None
    try:
        with transaction() as cur:
            cur.execute("SELECT funding, status FROM student WHERE student_id = %s FOR UPDATE", (student_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError("Такого студента нет в базе.")
            if row[0] != "paid":
                raise ValueError("Чеки прикладывают только студенты на платном обучении.")
            if row[1] != "Active":
                raise ValueError("Чек можно приложить только при статусе «Активный».")
            file_id, stored = db_files._insert_file(cur, "receipt", file_name, data, "student", student_id)
            cur.execute("INSERT INTO payment_receipt (student_id, file_id) VALUES (%s, %s)",
                        (student_id, file_id))
    except Exception:
        if stored:
            storage.delete(stored["storage_backend"], stored["storage_key"])
        raise


def list_receipts(student_id):
    rows = fetch_all(
        """
        SELECT r.receipt_id, f.file_name, f.size_bytes, r.uploaded_at,
               EXISTS (SELECT 1 FROM payment p WHERE p.receipt_id = r.receipt_id)
        FROM payment_receipt r JOIN stored_file f ON f.file_id = r.file_id
        WHERE r.student_id = %s ORDER BY r.uploaded_at DESC, r.receipt_id DESC
        """, (student_id,))
    return [{"receipt_id": r[0], "file_name": r[1], "size": r[2], "uploaded_at": r[3],
             "used": r[4]} for r in rows]


def delete_receipt(student_id, receipt_id):
    """Студент может удалить свой чек, пока бухгалтер не привязал к нему оплату."""
    with transaction() as cur:
        cur.execute("SELECT file_id FROM payment_receipt WHERE receipt_id = %s AND student_id = %s FOR UPDATE",
                    (receipt_id, student_id))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Чека уже нет.")
        cur.execute("SELECT 1 FROM payment WHERE receipt_id = %s", (receipt_id,))
        if cur.fetchone():
            raise ValueError("Этот чек уже учтён бухгалтерией — удалить его нельзя.")
        cur.execute("SELECT storage_backend, storage_key FROM stored_file WHERE file_id = %s", (row[0],))
        info = cur.fetchone()
        cur.execute("DELETE FROM payment_receipt WHERE receipt_id = %s", (receipt_id,))   # файл — триггером
    storage.delete(*info)


def open_receipt(role, user_id, receipt_id, department=None):
    """Скачать чек: сам студент или сотрудник бухгалтерии."""
    if role == "student":
        row = fetch_one("SELECT file_id FROM payment_receipt WHERE receipt_id = %s AND student_id = %s",
                        (receipt_id, user_id))
    elif role == "staff" and department == "Accounting":
        row = fetch_one("SELECT file_id FROM payment_receipt WHERE receipt_id = %s", (receipt_id,))
    else:
        row = None
    if row is None:
        raise ValueError("Нет доступа к этому файлу.")
    return db_files._read_file(row[0])
