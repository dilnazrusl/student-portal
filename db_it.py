"""
db_it.py
--------
Запросы IT-департамента: списки студентов / преподавателей / сотрудников,
профили, история (входы + изменения «было → стало»), исправление имени и смена пароля.
"""

import psycopg2

from constants import (ACTION_LABELS, DEPARTMENTS, RELATIONSHIP_RU, status_label)
from db_core import fetch_all, fetch_one, transaction, log_staff_action
from utils import format_dt, format_grade, validate_password

_TABLES = {
    "student": ("student", "student_id"),
    "instructor": ("instructor", "instructor_id"),
    "staff": ("staff", "staff_id"),
}


# ------------------------------------------------------------------ списки ----

def list_people(kind):
    """
    Список людей для таблицы IT:
      student    -> id, name, last_login
      instructor -> id, name, last_login, last_change (последнее изменение оценки)
      staff      -> id, name, department, last_action_time, last_action (название)
    """
    if kind == "student":
        rows = fetch_all(
            """
            SELECT s.student_id, s.name,
                   (SELECT MAX(logged_at) FROM login_log l WHERE l.role = 'student' AND l.user_id = s.student_id)
            FROM student s ORDER BY s.student_id
            """)
        return [{"id": r[0], "name": r[1], "last_login": r[2]} for r in rows]

    if kind == "instructor":
        rows = fetch_all(
            """
            SELECT i.instructor_id, i.name,
                   (SELECT MAX(logged_at) FROM login_log l WHERE l.role = 'instructor' AND l.user_id = i.instructor_id),
                   (SELECT MAX(changed_at) FROM grade_change_log g WHERE g.instructor_id = i.instructor_id)
            FROM instructor i ORDER BY i.instructor_id
            """)
        return [{"id": r[0], "name": r[1], "last_login": r[2], "last_change": r[3]} for r in rows]

    rows = fetch_all(
        """
        SELECT s.staff_id, s.name, s.department, a.acted_at, a.action
        FROM staff s
        LEFT JOIN LATERAL (SELECT acted_at, action FROM staff_action_log x
                           WHERE x.staff_id = s.staff_id ORDER BY acted_at DESC LIMIT 1) a ON TRUE
        ORDER BY s.staff_id
        """)
    return [{"id": r[0], "name": r[1], "department": r[2],
             "last_action_time": r[3], "last_action": ACTION_LABELS.get(r[4], r[4] or "")} for r in rows]


# ----------------------------------------------------------------- профили ----

def get_profile(kind, person_id):
    """Подробный профиль (в том числе пароль — его видит только IT)."""
    if kind == "student":
        s = fetch_one(
            "SELECT student_id, name, email, iin, course_year, status, password "
            "FROM student WHERE student_id = %s", (person_id,))
        if s is None:
            return None
        contact = fetch_one(
            """
            SELECT ec.contact_name, ec.relationship, ec.phone
            FROM has h JOIN emergency_contact ec ON ec.contact_name = h.contact_name
            WHERE h.student_id = %s LIMIT 1
            """, (person_id,))
        courses = fetch_all(
            """
            SELECT e.course_code, c.course_name, e.semester
            FROM enrollment e JOIN course c ON c.course_code = e.course_code
            WHERE e.student_id = %s ORDER BY e.semester, e.course_code
            """, (person_id,))
        return {
            "id": s[0], "name": s[1], "email": s[2], "iin": s[3], "course_year": s[4],
            "status": status_label("student", s[5]), "password": s[6],
            "contact": None if contact is None else
                f"{contact[0]} ({RELATIONSHIP_RU.get(contact[1], contact[1])}), {contact[2]}",
            "courses": [f"{c[0]} — {c[1]} ({c[2]})" for c in courses],
        }

    if kind == "instructor":
        i = fetch_one(
            "SELECT instructor_id, name, email, department, status, password "
            "FROM instructor WHERE instructor_id = %s", (person_id,))
        if i is None:
            return None
        courses = fetch_all(
            """
            SELECT c.course_code, c.course_name FROM teacher t
            JOIN course c ON c.course_code = t.course_code
            WHERE t.instructor_id = %s ORDER BY c.course_code
            """, (person_id,))
        count = fetch_one(
            """
            SELECT COUNT(DISTINCT e.student_id) FROM enrollment e
            WHERE e.course_code IN (SELECT course_code FROM teacher WHERE instructor_id = %s)
            """, (person_id,))[0]
        return {
            "id": i[0], "name": i[1], "email": i[2], "department": i[3],
            "status": status_label("instructor", i[4]), "password": i[5],
            "courses": [f"{c[0]} — {c[1]}" for c in courses], "student_count": count,
        }

    st = fetch_one(
        "SELECT staff_id, name, email, department, password FROM staff WHERE staff_id = %s",
        (person_id,))
    if st is None:
        return None
    actions = fetch_one("SELECT COUNT(*) FROM staff_action_log WHERE staff_id = %s", (person_id,))[0]
    return {"id": st[0], "name": st[1], "email": st[2],
            "department": DEPARTMENTS.get(st[3], st[3]), "password": st[4], "actions": actions}


def get_instructor_students(instructor_id):
    """Все студенты преподавателя: [{'id','name','course_year','course'}]."""
    rows = fetch_all(
        """
        SELECT s.student_id, s.name, s.course_year, e.course_code
        FROM enrollment e
        JOIN student s ON s.student_id = e.student_id
        WHERE e.course_code IN (SELECT course_code FROM teacher WHERE instructor_id = %s)
        ORDER BY s.student_id, e.course_code
        """, (instructor_id,))
    return [{"id": r[0], "name": r[1], "course_year": r[2], "course": r[3]} for r in rows]


# ----------------------------------------------------------------- история ----

def get_history(kind, person_id, limit=300):
    """
    Все события человека, новые сверху. Каждое событие:
      {'time', 'title', 'short' (кратко в списке), 'details' (полный текст)}
    """
    events = []

    # входы в систему
    for (t,) in fetch_all(
            "SELECT logged_at FROM login_log WHERE role = %s AND user_id = %s "
            "ORDER BY logged_at DESC LIMIT %s", (kind, person_id, limit)):
        events.append({"time": t, "title": "Вход в систему", "short": "",
                       "details": "Вход в систему"})

    # преподаватель: изменения оценок (было → стало)
    if kind == "instructor":
        for r in fetch_all(
                """
                SELECT changed_at, student_id, student_name, course_code, semester,
                       old_grade, new_grade, instructor_name
                FROM grade_change_log WHERE instructor_id = %s
                ORDER BY changed_at DESC LIMIT %s
                """, (person_id, limit)):
            t, sid, sname, code, sem, old, new, iname = r
            events.append({
                "time": t,
                "title": "Изменена оценка",
                "short": f"{sname} (ID {sid}) · {code}: {format_grade(old)} → {format_grade(new)}",
                "details": (f"Преподаватель: {iname} (ID {person_id})\nСтудент: {sname} (ID {sid})\n"
                            f"Курс: {code} ({sem})\n\nБыло: {format_grade(old)}\nСтало: {format_grade(new)}"),
            })

    # действия сотрудников
    if kind == "staff":
        rows = fetch_all(
            """
            SELECT acted_at, action, target_name, details, staff_name, department
            FROM staff_action_log WHERE staff_id = %s ORDER BY acted_at DESC LIMIT %s
            """, (person_id, limit))
        for t, action, tname, details, sname, dep in rows:
            label = ACTION_LABELS.get(action, action)
            events.append({
                "time": t, "title": label, "short": tname or "",
                "details": f"Сотрудник: {sname} ({DEPARTMENTS.get(dep, dep)})\n"
                           f"Действие: {label}\n\n{details or ''}",
            })
    else:
        # что сотрудники делали с этим студентом / преподавателем
        rows = fetch_all(
            """
            SELECT acted_at, action, staff_name, department, details
            FROM staff_action_log WHERE target_type = %s AND target_id = %s
            ORDER BY acted_at DESC LIMIT %s
            """, (kind, person_id, limit))
        for t, action, sname, dep, details in rows:
            label = ACTION_LABELS.get(action, action)
            events.append({
                "time": t, "title": label, "short": f"{sname} ({DEPARTMENTS.get(dep, dep)})",
                "details": f"Сотрудник: {sname} ({DEPARTMENTS.get(dep, dep)})\n"
                           f"Действие: {label}\n\n{details or ''}",
            })

    events.sort(key=lambda e: e["time"], reverse=True)
    return events[:limit]


# ----------------------------------------------------------- изменения IT ----

def update_name(staff, kind, person_id, new_name):
    """Исправляет имя (если написали неправильно). Почта остаётся прежней."""
    new_name = " ".join(new_name.split())
    if not new_name:
        raise ValueError("Имя не может быть пустым.")
    table, id_col = _TABLES[kind]
    with transaction() as cur:
        cur.execute(f"SELECT name FROM {table} WHERE {id_col} = %s FOR UPDATE", (person_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Такой записи нет в базе.")
        old = row[0]
        if old == new_name:
            return False
        cur.execute(f"UPDATE {table} SET name = %s WHERE {id_col} = %s", (new_name, person_id))
        log_staff_action(cur, staff, "EDIT_NAME", kind, person_id, new_name,
                         f"Было: {old}\nСтало: {new_name}")
    return True


def change_password(staff, kind, person_id, new_password):
    """Меняет пароль (проверяются правила). Сам пароль в журнал НЕ записывается."""
    error = validate_password(new_password)
    if error:
        raise ValueError(error)
    table, id_col = _TABLES[kind]
    try:
        with transaction() as cur:
            cur.execute(f"SELECT name FROM {table} WHERE {id_col} = %s FOR UPDATE", (person_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError("Такой записи нет в базе.")
            cur.execute(f"UPDATE {table} SET password = %s WHERE {id_col} = %s", (new_password, person_id))
            log_staff_action(cur, staff, "CHANGE_PASSWORD", kind, person_id, row[0],
                             "Пароль изменён (сам пароль в журнал не записывается)")
    except psycopg2.errors.UniqueViolation:
        raise ValueError("Такой пароль уже используется у другого человека. Придумай другой.")
