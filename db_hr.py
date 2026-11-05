"""
db_hr.py
--------
Запросы HR-департамента: создание учётных записей студентов и преподавателей,
изменение статусов, удаление студентов. Каждое действие записывается в журнал
staff_action_log (его потом видит IT-департамент).

Ошибки, понятные человеку (например «такой ИИН уже есть»), поднимаются как
ValueError — окно покажет их текстом.
"""

import re

import psycopg2

from constants import (STATUSES, status_label, RELATIONSHIP_RU)
from db_core import fetch_all, fetch_one, transaction, log_staff_action, allocate_id
from utils import email_local_part, generate_password

PHONE_RE = re.compile(r"^\+?[0-9][0-9\-\s()]{6,18}$")


# ------------------------------------------------------------ справочники ----

def get_academic_departments():
    """Список департаментов преподавателей для выпадающего списка."""
    return [r[0] for r in fetch_all("SELECT DISTINCT department FROM instructor ORDER BY department")]


def get_all_courses():
    """Все курсы для выпадающих списков: [(код, название), ...]."""
    return [(r[0], r[1]) for r in fetch_all(
        "SELECT course_code, course_name FROM course ORDER BY course_code")]


def peek_next_id(table, id_col):
    """Какой ID получит следующая запись (для показа в анкете; ничего не меняет)."""
    seq = fetch_one("SELECT pg_get_serial_sequence(%s, %s)", (table, id_col))[0]
    last, called = fetch_one(f"SELECT last_value, is_called FROM {seq}")
    nxt = last + 1 if called else last
    mx = fetch_one(f"SELECT COALESCE(MAX({id_col}), 0) FROM {table}")[0]
    return max(nxt, mx + 1)


def _unique_password(cur, table):
    for _ in range(20):
        pw = generate_password()
        cur.execute(f"SELECT 1 FROM {table} WHERE password = %s", (pw,))
        if cur.fetchone() is None:
            return pw
    raise RuntimeError("Не удалось создать уникальный пароль")


# ---------------------------------------------------------------- создание ----

def create_student(staff, first, last, iin, course_year, contact_name, relationship, phone):
    """
    Создаёт студента: сам назначает ID (последний + 1), почту и пароль,
    сохраняет экстренный контакт и связь has. Возвращает словарь с ID и почтой.
    """
    first, last = first.strip(), last.strip()
    contact_name, phone = contact_name.strip(), phone.strip()
    if not first or not last:
        raise ValueError("Укажи имя и фамилию студента.")
    if not re.fullmatch(r"[0-9]{12}", iin):
        raise ValueError("ИИН должен состоять ровно из 12 цифр.")
    if course_year not in (1, 2, 3, 4):
        raise ValueError("Выбери курс обучения (1–4).")
    if not contact_name:
        raise ValueError("Укажи имя и фамилию экстренного контакта.")
    if relationship not in RELATIONSHIP_RU:
        raise ValueError("Выбери, кем приходится экстренный контакт.")
    if not PHONE_RE.match(phone):
        raise ValueError("Телефон контакта указан неверно (например +7-701-123-4567).")

    name = f"{first} {last}"
    try:
        with transaction() as cur:
            cur.execute("SELECT student_id FROM student WHERE iin = %s", (iin,))
            dup = cur.fetchone()
            if dup:
                raise ValueError(f"Студент с таким ИИН уже есть в системе (ID {dup[0]}).")

            # экстренный контакт: если контакт с таким именем уже есть (например, общий
            # родитель у брата и сестры) — просто привязываем студента к нему
            cur.execute("SELECT phone, relationship FROM emergency_contact WHERE contact_name = %s",
                        (contact_name,))
            existing = cur.fetchone()
            contact_reused = existing is not None
            if contact_reused:
                phone, relationship = existing
            else:
                cur.execute("SELECT contact_name FROM emergency_contact WHERE phone = %s", (phone,))
                owner = cur.fetchone()
                if owner:
                    raise ValueError(f"Телефон {phone} уже указан у контакта «{owner[0]}».")

            # все проверки пройдены — только теперь выдаём ID (чтобы в нумерации не было дырок)
            student_id = allocate_id(cur, "student", "student_id")
            email = f"{email_local_part(first, last)}{student_id}@mail.kz"
            password = _unique_password(cur, "student")

            cur.execute(
                """
                INSERT INTO student (student_id, iin, name, email, course_year, password)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (student_id, iin, name, email, course_year, password),
            )
            if not contact_reused:
                cur.execute(
                    "INSERT INTO emergency_contact (contact_name, phone, relationship) "
                    "VALUES (%s, %s, %s)",
                    (contact_name, phone, relationship),
                )
            cur.execute("INSERT INTO has (student_id, contact_name) VALUES (%s, %s)",
                        (student_id, contact_name))

            details = (
                f"ID: {student_id}\nИмя: {name}\nИИН: {iin}\nПочта: {email}\n"
                f"Курс обучения: {course_year}\n"
                f"Экстренный контакт: {contact_name} ({RELATIONSHIP_RU.get(relationship, relationship)}), {phone}\n"
                f"Статус: Активный"
            )
            log_staff_action(cur, staff, "CREATE_STUDENT", "student", student_id, name, details)
    except psycopg2.errors.UniqueViolation as exc:
        raise ValueError(f"Такая запись уже существует в базе.\n{exc.diag.message_detail or ''}")

    return {"student_id": student_id, "email": email, "name": name, "contact_reused": contact_reused}


def create_instructor(staff, first, last, department, course_code):
    """Создаёт преподавателя: ID (последний + 1), почта и пароль — автоматически."""
    first, last = first.strip(), last.strip()
    if not first or not last:
        raise ValueError("Укажи имя и фамилию преподавателя.")
    if not department:
        raise ValueError("Выбери департамент.")
    if not course_code:
        raise ValueError("Выбери предмет, который ведёт преподаватель.")

    name = f"{first} {last}"
    with transaction() as cur:
        cur.execute("SELECT course_name FROM course WHERE course_code = %s", (course_code,))
        course = cur.fetchone()
        if course is None:
            raise ValueError("Такого предмета нет в базе.")

        instructor_id = allocate_id(cur, "instructor", "instructor_id")
        email = f"{email_local_part(first, last)}{instructor_id}@kbtu.kz"
        password = _unique_password(cur, "instructor")

        cur.execute(
            """
            INSERT INTO instructor (instructor_id, name, email, department, password)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (instructor_id, name, email, department, password),
        )
        cur.execute("INSERT INTO teacher (instructor_id, course_code) VALUES (%s, %s)",
                    (instructor_id, course_code))

        details = (
            f"ID: {instructor_id}\nИмя: {name}\nПочта: {email}\nДепартамент: {department}\n"
            f"Предмет: {course_code} — {course[0]}\nСтатус: Работает"
        )
        log_staff_action(cur, staff, "CREATE_INSTRUCTOR", "instructor", instructor_id, name, details)

    return {"instructor_id": instructor_id, "email": email, "name": name}


# ------------------------------------------------------------------ статусы ----

_TABLES = {"student": ("student", "student_id"), "instructor": ("instructor", "instructor_id")}


def list_people_for_status(kind):
    """Все студенты или преподаватели по алфавиту: [(id, имя, статус), ...]."""
    table, id_col = _TABLES[kind]
    return [(r[0], r[1], r[2]) for r in fetch_all(
        f"SELECT {id_col}, name, status FROM {table} ORDER BY name, {id_col}")]


def get_person(kind, person_id):
    table, id_col = _TABLES[kind]
    row = fetch_one(f"SELECT {id_col}, name, status FROM {table} WHERE {id_col} = %s", (person_id,))
    return None if row is None else {"id": row[0], "name": row[1], "status": row[2]}


def change_status(staff, kind, person_id, new_status):
    """Меняет статус и пишет в журнал. Возвращает False, если статус не изменился."""
    if new_status not in dict(STATUSES[kind]):
        raise ValueError("Выбери статус из списка.")
    table, id_col = _TABLES[kind]
    with transaction() as cur:
        cur.execute(f"SELECT name, status FROM {table} WHERE {id_col} = %s FOR UPDATE", (person_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Такой записи уже нет в базе.")
        name, old = row
        if old == new_status:
            return False
        cur.execute(f"UPDATE {table} SET status = %s WHERE {id_col} = %s", (new_status, person_id))
        who = "Студент" if kind == "student" else "Преподаватель"
        details = (f"{who}: {name} (ID {person_id})\n"
                   f"Статус: {status_label(kind, old)} → {status_label(kind, new_status)}")
        log_staff_action(cur, staff, "CHANGE_STATUS", kind, person_id, name, details)
    return True


def delete_student(staff, student_id):
    """
    Полностью удаляет студента (вместе с его записями на курсы и связью has;
    экстренный контакт удаляется, если им больше никто не пользуется).
    Перед удалением в журнал записывается полный снимок данных (без пароля).
    """
    with transaction() as cur:
        cur.execute(
            "SELECT name, iin, email, course_year, status FROM student "
            "WHERE student_id = %s FOR UPDATE", (student_id,))
        s = cur.fetchone()
        if s is None:
            raise ValueError("Такого студента уже нет в базе.")
        name, iin, email, course_year, status = s

        cur.execute(
            """
            SELECT ec.contact_name, ec.relationship, ec.phone
            FROM has h JOIN emergency_contact ec ON ec.contact_name = h.contact_name
            WHERE h.student_id = %s
            """, (student_id,))
        contacts = cur.fetchall()

        cur.execute(
            """
            SELECT e.course_code, c.course_name, e.semester, e.grade
            FROM enrollment e JOIN course c ON c.course_code = e.course_code
            WHERE e.student_id = %s ORDER BY e.semester, e.course_code
            """, (student_id,))
        courses = cur.fetchall()

        lines = [f"ID: {student_id}", f"Имя: {name}", f"ИИН: {iin}", f"Почта: {email}",
                 f"Курс обучения: {course_year}", f"Статус на момент удаления: {status_label('student', status)}"]
        for cn, rel, ph in contacts:
            lines.append(f"Экстренный контакт: {cn} ({RELATIONSHIP_RU.get(rel, rel)}), {ph}")
        if courses:
            lines.append("Курсы на момент удаления:")
            for code, cname, sem, grade in courses:
                g = "—" if grade is None else f"{float(grade):g}%"
                lines.append(f"  • {code} — {cname} ({sem}), оценка {g}")
        else:
            lines.append("Курсы на момент удаления: нет")

        cur.execute("DELETE FROM student WHERE student_id = %s", (student_id,))  # has/enrollment — каскадом
        names = [c[0] for c in contacts]
        if names:
            cur.execute(
                """
                DELETE FROM emergency_contact ec
                WHERE ec.contact_name = ANY(%s)
                  AND NOT EXISTS (SELECT 1 FROM has h WHERE h.contact_name = ec.contact_name)
                """, (names,))

        log_staff_action(cur, staff, "DELETE_STUDENT", "student", student_id, name, "\n".join(lines))
