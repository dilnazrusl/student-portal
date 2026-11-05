"""
db_registrar.py
---------------
Запросы офиса регистратора: список студентов и подключение/отключение курсов.
Регистратор НЕ видит оценок и почты — только ID, имя и названия курсов.
"""

from constants import MAX_COURSES
from db_core import fetch_all, transaction, log_staff_action
from utils import current_semester


def list_students():
    """[(id, имя), ...] по алфавиту."""
    return [(r[0], r[1]) for r in fetch_all(
        "SELECT student_id, name FROM student ORDER BY name, student_id")]


def get_student_courses(student_id):
    """Курсы студента: [{'course_code','course_name','semester'}] (без оценок)."""
    rows = fetch_all(
        """
        SELECT e.course_code, c.course_name, e.semester
        FROM enrollment e JOIN course c ON c.course_code = e.course_code
        WHERE e.student_id = %s ORDER BY e.semester DESC, e.course_code
        """, (student_id,))
    return [{"course_code": r[0], "course_name": r[1], "semester": r[2]} for r in rows]


def get_available_courses(student_id):
    """Курсы, на которые студент ещё не записан: [(код, название), ...]."""
    return [(r[0], r[1]) for r in fetch_all(
        """
        SELECT course_code, course_name FROM course
        WHERE course_code NOT IN (SELECT course_code FROM enrollment WHERE student_id = %s)
        ORDER BY course_code
        """, (student_id,))]


def add_course(staff, student_id, course_code):
    """Записывает студента на курс в текущем семестре (максимум MAX_COURSES курсов)."""
    semester = current_semester()
    with transaction() as cur:
        cur.execute("SELECT name FROM student WHERE student_id = %s FOR UPDATE", (student_id,))
        s = cur.fetchone()
        if s is None:
            raise ValueError("Такого студента нет в базе.")
        cur.execute("SELECT course_name FROM course WHERE course_code = %s", (course_code,))
        c = cur.fetchone()
        if c is None:
            raise ValueError("Такого курса нет в базе.")

        cur.execute("SELECT COUNT(*) FROM enrollment WHERE student_id = %s", (student_id,))
        if cur.fetchone()[0] >= MAX_COURSES:
            raise ValueError(f"У студента уже {MAX_COURSES} курсов — это максимум.")
        cur.execute("SELECT 1 FROM enrollment WHERE student_id = %s AND course_code = %s",
                    (student_id, course_code))
        if cur.fetchone():
            raise ValueError("Студент уже записан на этот курс.")

        cur.execute(
            "INSERT INTO enrollment (student_id, course_code, semester, grade) "
            "VALUES (%s, %s, %s, NULL)", (student_id, course_code, semester))
        details = (f"Студент: {s[0]} (ID {student_id})\nКурс: {course_code} — {c[0]}\n"
                   f"Семестр: {semester}")
        log_staff_action(cur, staff, "ADD_COURSE", "student", student_id, s[0], details)


def remove_course(staff, student_id, course_code, semester):
    """Отключает студента от курса (запись об оценке по нему тоже исчезает)."""
    with transaction() as cur:
        cur.execute(
            """
            SELECT s.name, c.course_name, e.grade
            FROM enrollment e
            JOIN student s ON s.student_id = e.student_id
            JOIN course c ON c.course_code = e.course_code
            WHERE e.student_id = %s AND e.course_code = %s AND e.semester = %s
            FOR UPDATE OF e
            """, (student_id, course_code, semester))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Этой записи уже нет.")
        name, course_name, grade = row
        cur.execute(
            "DELETE FROM enrollment WHERE student_id = %s AND course_code = %s AND semester = %s",
            (student_id, course_code, semester))
        g = "не выставлена" if grade is None else f"{float(grade):g}%"
        details = (f"Студент: {name} (ID {student_id})\nКурс: {course_code} — {course_name}\n"
                   f"Семестр: {semester}\nОценка на момент удаления: {g}")
        log_staff_action(cur, staff, "REMOVE_COURSE", "student", student_id, name, details)
