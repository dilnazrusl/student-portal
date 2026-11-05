"""
db.py
-----
Вход в систему (студент / преподаватель / сотрудник), данные студента
и данные преподавателя (включая изменение оценок с записью в журнал).

Остальные запросы:
  db_hr.py        — HR: создание аккаунтов, статусы, удаление студентов
  db_registrar.py — офис регистратора: курсы студентов
  db_it.py        — IT: списки людей, профили, история, имя и пароль
"""

from db_core import fetch_all, fetch_one, transaction


def _to_int(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------- вход ----

def verify_student(student_id, password):
    """Проверяет ID + пароль студента. Возвращает словарь с данными или None."""
    sid = _to_int(student_id)
    if sid is None:
        return None
    row = fetch_one(
        """
        SELECT student_id, name, email, iin, course_year, status
        FROM student WHERE student_id = %s AND password = %s
        """,
        (sid, password),
    )
    if row is None:
        return None
    return {"student_id": row[0], "name": row[1], "email": row[2],
            "iin": row[3], "course_year": row[4], "status": row[5]}


def verify_instructor(instructor_id, password):
    """Проверяет ID + пароль преподавателя. Возвращает словарь с данными или None."""
    iid = _to_int(instructor_id)
    if iid is None:
        return None
    row = fetch_one(
        """
        SELECT instructor_id, name, email, department, status
        FROM instructor WHERE instructor_id = %s AND password = %s
        """,
        (iid, password),
    )
    if row is None:
        return None
    return {"instructor_id": row[0], "name": row[1], "email": row[2],
            "department": row[3], "status": row[4]}


def verify_staff(staff_id, password):
    """Проверяет ID + пароль сотрудника (HR / Registrar / IT)."""
    sid = _to_int(staff_id)
    if sid is None:
        return None
    row = fetch_one(
        """
        SELECT staff_id, name, email, department
        FROM staff WHERE staff_id = %s AND password = %s
        """,
        (sid, password),
    )
    if row is None:
        return None
    return {"staff_id": row[0], "name": row[1], "email": row[2], "department": row[3]}


def log_login(role, user_id, user_name):
    """Записывает успешный вход в журнал login_log (время ставит сама база)."""
    with transaction() as cur:
        cur.execute(
            "INSERT INTO login_log (role, user_id, user_name) VALUES (%s, %s, %s)",
            (role, user_id, user_name),
        )


# ------------------------------------------------------------ студент ----

def get_student_status(student_id):
    row = fetch_one("SELECT status FROM student WHERE student_id = %s", (student_id,))
    return row[0] if row else None


def get_emergency_contact(student_id):
    """Экстренный контакт студента: student -> has -> emergency_contact."""
    row = fetch_one(
        """
        SELECT ec.contact_name, ec.phone, ec.relationship
        FROM has h
        JOIN emergency_contact ec ON h.contact_name = ec.contact_name
        WHERE h.student_id = %s
        LIMIT 1
        """,
        (student_id,),
    )
    if row is None:
        return None
    return {"contact_name": row[0], "phone": row[1], "relationship": row[2]}


def get_grades(student_id):
    """Все курсы студента с оценками."""
    rows = fetch_all(
        """
        SELECT c.course_name, e.course_code, e.semester, e.grade
        FROM enrollment e
        JOIN course c ON e.course_code = c.course_code
        WHERE e.student_id = %s
        ORDER BY e.semester, c.course_name
        """,
        (student_id,),
    )
    return [{"course_name": r[0], "course_code": r[1], "semester": r[2], "grade": r[3]}
            for r in rows]


# ------------------------------------------------------- преподаватель ----

def get_instructor_status(instructor_id):
    row = fetch_one("SELECT status FROM instructor WHERE instructor_id = %s", (instructor_id,))
    return row[0] if row else None


def get_instructor_courses(instructor_id):
    """Курсы, которые ведёт преподаватель."""
    rows = fetch_all(
        """
        SELECT c.course_code, c.course_name
        FROM teacher t JOIN course c ON t.course_code = c.course_code
        WHERE t.instructor_id = %s
        ORDER BY c.course_code
        """,
        (instructor_id,),
    )
    return [{"course_code": r[0], "course_name": r[1]} for r in rows]


def get_course_students(instructor_id, course_code):
    """Студенты курса и их оценки (только если курс ведёт этот преподаватель)."""
    rows = fetch_all(
        """
        SELECT s.student_id, s.name, s.course_year, e.semester, e.grade
        FROM enrollment e
        JOIN student s ON s.student_id = e.student_id
        WHERE e.course_code = %s
          AND e.course_code IN (SELECT course_code FROM teacher WHERE instructor_id = %s)
        ORDER BY s.student_id, e.semester
        """,
        (course_code, instructor_id),
    )
    return [{"student_id": r[0], "name": r[1], "course_year": r[2],
             "semester": r[3], "grade": r[4]} for r in rows]


def update_grade(instructor_id, student_id, course_code, semester, new_grade):
    """
    Меняет оценку и записывает «было → стало» в журнал grade_change_log
    (всё в одной транзакции).
    Получится только если преподаватель ведёт этот курс И его статус «Работает».
    Возвращает 1 при успехе, 0 если менять нельзя.
    """
    with transaction() as cur:
        cur.execute(
            """
            SELECT e.grade, s.name, i.name
            FROM enrollment e
            JOIN student s ON s.student_id = e.student_id
            JOIN instructor i ON i.instructor_id = %s AND i.status = 'Working'
            WHERE e.student_id = %s AND e.course_code = %s AND e.semester = %s
              AND e.course_code IN (SELECT course_code FROM teacher WHERE instructor_id = %s)
            FOR UPDATE OF e
            """,
            (instructor_id, student_id, course_code, semester, instructor_id),
        )
        row = cur.fetchone()
        if row is None:
            return 0
        old_grade, student_name, instructor_name = row
        if old_grade is not None and float(old_grade) == float(new_grade):
            return 1  # ничего не изменилось

        cur.execute(
            "UPDATE enrollment SET grade = %s "
            "WHERE student_id = %s AND course_code = %s AND semester = %s",
            (new_grade, student_id, course_code, semester),
        )
        cur.execute(
            """
            INSERT INTO grade_change_log
                (instructor_id, instructor_name, student_id, student_name,
                 course_code, semester, old_grade, new_grade)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (instructor_id, instructor_name, student_id, student_name,
             course_code, semester, old_grade, new_grade),
        )
        return 1
