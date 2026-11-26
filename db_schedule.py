"""
db_schedule.py
--------------
Расписание и регистрация на курсы с «бронированием времени» (как билеты в корзине).

Как это работает:
  1. Студент (или регистратор от его имени) выбирает курс и нажимает на нужные времена.
     Каждое выбранное время сразу УДЕРЖИВАЕТСЯ за ним (status = 'held') на hold_minutes минут:
     другой студент его выбрать не может.
  2. Когда набрано нужное число лекций и практик (2+1 или 3+2), регистрацию подтверждают:
     брони становятся 'confirmed', студент записывается на курс (таблица enrollment).
  3. Если не подтвердить, удержание истекает и время снова свободно.
Все проверки (места, пересечения, лимиты) выполняет триггер в базе данных (update_db_6.sql),
поэтому они работают одинаково для студента и регистратора и не зависят от сайта.
"""

import psycopg2

from constants import MAX_COURSES
from db_core import fetch_all, fetch_one, log_staff_action, transaction
from utils import current_semester

DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт"]
DAYS_FULL = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"]
HOURS = [13, 14, 15, 16, 17]                     # 13:00–14:00 … 17:00–18:00
KIND_SHORT = {"lecture": "Л", "practice": "П"}
KIND_RU = {"lecture": "Лекция", "practice": "Практика"}

_NOW = "timezone('UTC', now())"
_ACTIVE = f"(b.status = 'confirmed' OR b.held_until > {_NOW})"      # бронь действует


def hour_label(h):
    return f"{h}:00"


def _human(exc):
    """Ошибки триггера (RAISE EXCEPTION) -> понятный текст."""
    if isinstance(exc, psycopg2.errors.UniqueViolation):
        return ValueError("Это время уже выбрано.")
    if isinstance(exc, psycopg2.errors.RaiseException):
        return ValueError(exc.diag.message_primary or str(exc))
    return exc


def get_settings():
    cap = fetch_one("SELECT slot_capacity(), hold_minutes()")
    return {"capacity": cap[0], "hold_minutes": cap[1]}


# ------------------------------------------------------------------ курсы ----

def search_courses(student_id, query="", limit=12):
    """Курсы, на которые студента ещё можно записать. Поиск понимает синонимы и опечатки."""
    rows = fetch_all(
        """
        SELECT c.course_code, c.course_name, c.credits, p.lectures, p.practices
        FROM course c JOIN course_plan p ON p.course_code = c.course_code
        WHERE c.course_code NOT IN (SELECT course_code FROM enrollment WHERE student_id = %s)
        ORDER BY c.course_code
        """, (student_id,))
    courses = {r[0]: {"course_code": r[0], "course_name": r[1], "credits": r[2],
                      "lectures": r[3], "practices": r[4]} for r in rows}
    query = " ".join((query or "").split())
    if len(query) < 2:
        return list(courses.values())[:limit]
    ranked = fetch_all(
        "SELECT course_code FROM search_docs(%s, ARRAY(SELECT course_code FROM course), 100) "
        "WHERE doc_type = 'course'", (query,))
    return [courses[r[0]] for r in ranked if r[0] in courses][:limit]


def get_plan(course_code):
    row = fetch_one("SELECT c.course_name, c.credits, p.lectures, p.practices FROM course c "
                    "JOIN course_plan p ON p.course_code = c.course_code WHERE c.course_code = %s",
                    (course_code,))
    if row is None:
        return None
    return {"course_code": course_code, "course_name": row[0], "credits": row[1],
            "lectures": row[2], "practices": row[3]}


def course_slots(student_id, course_code):
    """Все времена курса и их состояние для этого студента."""
    rows = fetch_all(
        f"""
        SELECT s.slot_id, s.kind, s.weekday, s.start_hour, s.room, coalesce(i.name, '—'),
               (SELECT count(*) FROM slot_booking b WHERE b.slot_id = s.slot_id AND {_ACTIVE}),
               (SELECT b.status FROM slot_booking b
                 WHERE b.slot_id = s.slot_id AND b.student_id = %s AND {_ACTIVE}),
               EXISTS (SELECT 1 FROM slot_booking b JOIN class_slot o ON o.slot_id = b.slot_id
                        WHERE b.student_id = %s AND o.course_code <> s.course_code
                          AND o.weekday = s.weekday AND o.start_hour = s.start_hour AND {_ACTIVE})
        FROM class_slot s LEFT JOIN instructor i ON i.instructor_id = s.instructor_id
        WHERE s.course_code = %s ORDER BY s.weekday, s.start_hour
        """, (student_id, student_id, course_code))
    return [{"slot_id": r[0], "kind": r[1], "weekday": r[2], "hour": r[3], "room": r[4],
             "instructor": r[5], "used": r[6], "mine": r[7], "conflict": r[8]} for r in rows]


def course_holds(student_id, course_code):
    """Что студент уже выбрал по курсу: {'lectures': n, 'practices': n, 'seconds_left': сек | None}."""
    rows = fetch_all(
        f"""
        SELECT s.kind, extract(epoch FROM (b.held_until - {_NOW}))::int
        FROM slot_booking b JOIN class_slot s ON s.slot_id = b.slot_id
        WHERE b.student_id = %s AND s.course_code = %s AND b.status = 'held' AND b.held_until > {_NOW}
        """, (student_id, course_code))
    return {"lectures": sum(1 for r in rows if r[0] == "lecture"),
            "practices": sum(1 for r in rows if r[0] == "practice"),
            "seconds_left": min((r[1] for r in rows), default=None)}


# ------------------------------------------------------------- бронирование ----

def hold_slot(student_id, slot_id):
    """Удерживает время за студентом. Если занято — ValueError с понятным текстом."""
    try:
        with transaction() as cur:
            cur.execute("INSERT INTO slot_booking (slot_id, student_id, status) VALUES (%s, %s, 'held')",
                        (slot_id, student_id))
            # таймер общий на весь курс: каждый новый выбор продлевает удержание остальных
            cur.execute(
                f"""
                UPDATE slot_booking b SET held_until = {_NOW} + hold_minutes() * interval '1 minute'
                WHERE b.student_id = %s AND b.status = 'held'
                  AND b.slot_id IN (SELECT s2.slot_id FROM class_slot s2
                                    WHERE s2.course_code = (SELECT course_code FROM class_slot WHERE slot_id = %s))
                """, (student_id, slot_id))
    except Exception as exc:
        raise _human(exc)


def release_slot(student_id, slot_id):
    with transaction() as cur:
        cur.execute("DELETE FROM slot_booking WHERE slot_id = %s AND student_id = %s AND status = 'held'",
                    (slot_id, student_id))


def cancel_registration(student_id, course_code):
    """Снять все удержания по курсу (студент передумал)."""
    with transaction() as cur:
        cur.execute(
            """
            DELETE FROM slot_booking b USING class_slot s
            WHERE b.slot_id = s.slot_id AND s.course_code = %s AND b.student_id = %s AND b.status = 'held'
            """, (course_code, student_id))


def confirm_course(student_id, course_code, staff=None):
    """
    Подтверждает регистрацию: брони -> 'confirmed', студент записывается на курс.
    staff — сотрудник, если регистрирует регистратор (действие попадёт в журнал).
    """
    try:
        with transaction() as cur:
            cur.execute("SELECT name FROM student WHERE student_id = %s FOR UPDATE", (student_id,))
            st = cur.fetchone()
            if st is None:
                raise ValueError("Такого студента нет в базе.")
            cur.execute("DELETE FROM slot_booking WHERE student_id = %s AND status = 'held' "
                        f"AND held_until < {_NOW}", (student_id,))
            cur.execute("SELECT lectures, practices FROM course_plan WHERE course_code = %s", (course_code,))
            plan = cur.fetchone()
            if plan is None:
                raise ValueError("Для этого курса не составлено расписание.")
            cur.execute(
                """
                SELECT b.booking_id, s.kind, s.weekday, s.start_hour, s.room
                FROM slot_booking b JOIN class_slot s ON s.slot_id = b.slot_id
                WHERE b.student_id = %s AND s.course_code = %s AND b.status = 'held'
                ORDER BY s.weekday, s.start_hour
                """, (student_id, course_code))
            held = cur.fetchall()
            lec = sum(1 for h in held if h[1] == "lecture")
            pra = sum(1 for h in held if h[1] == "practice")
            if lec != plan[0] or pra != plan[1]:
                raise ValueError(f"Нужно выбрать: лекций — {plan[0]} (выбрано {lec}), "
                                 f"практик — {plan[1]} (выбрано {pra}). "
                                 "Если время выбора истекло, выбери заново.")
            cur.execute("SELECT count(*) FROM enrollment WHERE student_id = %s", (student_id,))
            if cur.fetchone()[0] >= MAX_COURSES:
                raise ValueError(f"У студента уже {MAX_COURSES} курсов — это максимум.")
            cur.execute("SELECT 1 FROM enrollment WHERE student_id = %s AND course_code = %s",
                        (student_id, course_code))
            if cur.fetchone():
                raise ValueError("Студент уже записан на этот курс.")
            cur.execute("UPDATE slot_booking SET status = 'confirmed', held_until = NULL "
                        "WHERE booking_id = ANY(%s)", ([h[0] for h in held],))
            semester = current_semester()
            cur.execute("INSERT INTO enrollment (student_id, course_code, semester, grade) "
                        "VALUES (%s, %s, %s, NULL)", (student_id, course_code, semester))
            if staff is not None:
                cur.execute("SELECT course_name FROM course WHERE course_code = %s", (course_code,))
                cname = cur.fetchone()[0]
                times = "\n".join(f"  • {KIND_RU[h[1]]}: {DAYS_FULL[h[2] - 1]} {hour_label(h[3])}, {h[4]}"
                                  for h in held)
                log_staff_action(cur, staff, "ADD_COURSE", "student", student_id, st[0],
                                 f"Студент: {st[0]} (ID {student_id})\nКурс: {course_code} — {cname}\n"
                                 f"Семестр: {semester}\nРегистрация через расписание:\n{times}")
    except Exception as exc:
        raise _human(exc)


# ----------------------------------------------------------------- расписание ----

def student_timetable(student_id):
    """Занятия студента: подтверждённые и удерживаемые."""
    rows = fetch_all(
        f"""
        SELECT s.weekday, s.start_hour, s.course_code, c.course_name, s.kind, s.room, b.status
        FROM slot_booking b JOIN class_slot s ON s.slot_id = b.slot_id
        JOIN course c ON c.course_code = s.course_code
        WHERE b.student_id = %s AND {_ACTIVE} ORDER BY s.weekday, s.start_hour
        """, (student_id,))
    return [{"weekday": r[0], "hour": r[1], "course_code": r[2], "course_name": r[3],
             "kind": r[4], "room": r[5], "status": r[6]} for r in rows]


def instructor_timetable(instructor_id):
    """Занятия преподавателя и сколько студентов записано."""
    rows = fetch_all(
        f"""
        SELECT s.weekday, s.start_hour, s.course_code, c.course_name, s.kind, s.room,
               (SELECT count(*) FROM slot_booking b WHERE b.slot_id = s.slot_id AND b.status = 'confirmed')
        FROM class_slot s JOIN course c ON c.course_code = s.course_code
        WHERE s.instructor_id = %s ORDER BY s.weekday, s.start_hour
        """, (instructor_id,))
    return [{"weekday": r[0], "hour": r[1], "course_code": r[2], "course_name": r[3],
             "kind": r[4], "room": r[5], "students": r[6]} for r in rows]
