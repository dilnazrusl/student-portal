"""
db_files.py
-----------
Файлы и домашние задания:
  • материалы курса (загружает преподаватель, видят студенты ЭТОГО курса),
  • задания с дедлайном и сдача работ студентами.

Проверка прав сделана здесь, в запросах: даже если кто-то подменит кнопку на сайте,
чужой файл база не отдаст. Ошибки, понятные человеку, поднимаются как ValueError.
Все даты — по UTC (naive datetime); сайт сам добавляет часовой пояс.
"""

import mimetypes

import psycopg2

import storage
from db_core import fetch_all, fetch_one, transaction


# ------------------------------------------------------------ служебное ----

def _insert_file(cur, kind, name, data, role, uid):
    """Проверяет файл, кладёт его в хранилище и создаёт карточку. Возвращает file_id."""
    storage.check_upload(kind, name, data)
    name = storage.safe_name(name)
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    stored = storage.put(kind, name, data, ctype)
    try:
        content = psycopg2.Binary(stored["content"]) if stored["content"] is not None else None
        cur.execute(
            """
            INSERT INTO stored_file (kind, file_name, content_type, size_bytes, storage_backend,
                                     storage_key, content, uploaded_by_role, uploaded_by_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING file_id
            """,
            (kind, name, ctype, len(data), stored["storage_backend"], stored["storage_key"],
             content, role, uid),
        )
        return cur.fetchone()[0], stored
    except Exception:
        storage.delete(stored["storage_backend"], stored["storage_key"])
        raise


def _read_file(file_id):
    """(имя, тип, байты) по file_id. Права проверяет вызывающая функция."""
    row = fetch_one(
        "SELECT file_name, content_type, storage_backend, storage_key, content "
        "FROM stored_file WHERE file_id = %s", (file_id,))
    if row is None:
        raise ValueError("Файл не найден.")
    return row[0], row[1], storage.get(row[2], row[3], row[4])


def _teaches(cur, instructor_id, course_code):
    """Преподаватель ведёт этот курс И его статус «Работает»."""
    cur.execute(
        """
        SELECT 1 FROM teacher t JOIN instructor i ON i.instructor_id = t.instructor_id
        WHERE t.instructor_id = %s AND t.course_code = %s AND i.status = 'Working'
        """, (instructor_id, course_code))
    return cur.fetchone() is not None


def _file_info(cur, file_id):
    cur.execute("SELECT storage_backend, storage_key FROM stored_file WHERE file_id = %s", (file_id,))
    return cur.fetchone()


# --------------------------------------------------------------- материалы ----

def list_course_materials(course_code):
    rows = fetch_all(
        """
        SELECT m.material_id, m.title, f.file_name, f.size_bytes, m.uploaded_at
        FROM course_material m JOIN stored_file f ON f.file_id = m.file_id
        WHERE m.course_code = %s ORDER BY m.uploaded_at DESC, m.material_id DESC
        """, (course_code,))
    return [{"material_id": r[0], "title": r[1], "file_name": r[2], "size": r[3], "uploaded_at": r[4]}
            for r in rows]


def list_student_materials(student_id):
    """Материалы только тех курсов, на которые записан студент."""
    rows = fetch_all(
        """
        SELECT c.course_code, c.course_name, m.material_id, m.title, f.file_name, f.size_bytes,
               m.uploaded_at, i.name
        FROM course_material m
        JOIN stored_file f ON f.file_id = m.file_id
        JOIN course c ON c.course_code = m.course_code
        JOIN instructor i ON i.instructor_id = m.instructor_id
        WHERE m.course_code IN (SELECT course_code FROM enrollment WHERE student_id = %s)
        ORDER BY c.course_code, m.uploaded_at DESC, m.material_id DESC
        """, (student_id,))
    return [{"course_code": r[0], "course_name": r[1], "material_id": r[2], "title": r[3],
             "file_name": r[4], "size": r[5], "uploaded_at": r[6], "instructor": r[7]} for r in rows]


def add_material(instructor_id, course_code, title, file_name, data):
    title = (title or "").strip()
    if not title:
        raise ValueError("Напиши название материала.")
    stored = None
    try:
        with transaction() as cur:
            if not _teaches(cur, instructor_id, course_code):
                raise ValueError("Загружать материалы может только работающий преподаватель этого курса.")
            file_id, stored = _insert_file(cur, "material", file_name, data, "instructor", instructor_id)
            cur.execute(
                "INSERT INTO course_material (course_code, instructor_id, title, file_id) "
                "VALUES (%s, %s, %s, %s)", (course_code, instructor_id, title[:150], file_id))
    except Exception:
        if stored:
            storage.delete(stored["storage_backend"], stored["storage_key"])
        raise


def delete_material(instructor_id, material_id):
    with transaction() as cur:
        cur.execute("SELECT course_code, file_id FROM course_material WHERE material_id = %s FOR UPDATE",
                    (material_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Материала уже нет.")
        if not _teaches(cur, instructor_id, row[0]):
            raise ValueError("Удалять материалы может только работающий преподаватель этого курса.")
        info = _file_info(cur, row[1])
        cur.execute("DELETE FROM course_material WHERE material_id = %s", (material_id,))  # файл — триггером
    storage.delete(*info)


def open_material(role, user_id, material_id):
    """Скачать материал: студент этого курса или преподаватель этого курса."""
    if role == "student":
        row = fetch_one(
            """
            SELECT m.file_id FROM course_material m
            WHERE m.material_id = %s
              AND m.course_code IN (SELECT course_code FROM enrollment WHERE student_id = %s)
            """, (material_id, user_id))
    elif role == "instructor":
        row = fetch_one(
            """
            SELECT m.file_id FROM course_material m
            WHERE m.material_id = %s
              AND m.course_code IN (SELECT course_code FROM teacher WHERE instructor_id = %s)
            """, (material_id, user_id))
    else:
        row = None
    if row is None:
        raise ValueError("Нет доступа к этому файлу.")
    return _read_file(row[0])


# ------------------------------------------------------------------ задания ----

def create_assignment(instructor_id, course_code, title, description, deadline_utc):
    title = (title or "").strip()
    if not title:
        raise ValueError("Напиши название задания.")
    with transaction() as cur:
        if not _teaches(cur, instructor_id, course_code):
            raise ValueError("Создавать задания может только работающий преподаватель этого курса.")
        cur.execute(
            "INSERT INTO assignment (course_code, instructor_id, title, description, deadline) "
            "VALUES (%s, %s, %s, %s, %s)",
            (course_code, instructor_id, title[:150], (description or "").strip(), deadline_utc))


def list_course_assignments(instructor_id, course_code):
    """Задания курса + сколько студентов сдали и сколько — вовремя."""
    rows = fetch_all(
        """
        SELECT a.assignment_id, a.title, a.description, a.deadline,
               (SELECT COUNT(DISTINCT student_id) FROM enrollment e WHERE e.course_code = a.course_code),
               (SELECT COUNT(*) FROM submission s WHERE s.assignment_id = a.assignment_id),
               (SELECT COUNT(*) FROM submission s WHERE s.assignment_id = a.assignment_id
                                                    AND s.submitted_at <= a.deadline)
        FROM assignment a
        WHERE a.course_code = %s
          AND a.course_code IN (SELECT course_code FROM teacher WHERE instructor_id = %s)
        ORDER BY a.deadline DESC, a.assignment_id DESC
        """, (course_code, instructor_id))
    return [{"assignment_id": r[0], "title": r[1], "description": r[2], "deadline": r[3],
             "students": r[4], "submitted": r[5], "on_time": r[6]} for r in rows]


def assignment_overview(instructor_id, assignment_id):
    """Все студенты курса и статус их сдачи по заданию."""
    rows = fetch_all(
        """
        SELECT st.student_id, st.name, sub.submission_id, sub.submitted_at, f.file_name,
               (sub.submitted_at <= a.deadline)
        FROM assignment a
        JOIN (SELECT DISTINCT student_id, course_code FROM enrollment) e ON e.course_code = a.course_code
        JOIN student st ON st.student_id = e.student_id
        LEFT JOIN submission sub ON sub.assignment_id = a.assignment_id AND sub.student_id = st.student_id
        LEFT JOIN stored_file f ON f.file_id = sub.file_id
        WHERE a.assignment_id = %s
          AND a.course_code IN (SELECT course_code FROM teacher WHERE instructor_id = %s)
        ORDER BY st.student_id
        """, (assignment_id, instructor_id))
    return [{"student_id": r[0], "name": r[1], "submission_id": r[2], "submitted_at": r[3],
             "file_name": r[4], "on_time": r[5]} for r in rows]


def delete_assignment(instructor_id, assignment_id):
    with transaction() as cur:
        cur.execute("SELECT course_code FROM assignment WHERE assignment_id = %s FOR UPDATE", (assignment_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Задания уже нет.")
        if not _teaches(cur, instructor_id, row[0]):
            raise ValueError("Удалять задания может только работающий преподаватель этого курса.")
        cur.execute(
            "SELECT f.storage_backend, f.storage_key FROM submission s "
            "JOIN stored_file f ON f.file_id = s.file_id WHERE s.assignment_id = %s", (assignment_id,))
        infos = cur.fetchall()
        cur.execute("DELETE FROM assignment WHERE assignment_id = %s", (assignment_id,))  # работы — каскадом
    for info in infos:
        storage.delete(*info)


def list_student_assignments(student_id):
    """Задания всех курсов студента и его сдачи."""
    rows = fetch_all(
        """
        SELECT a.assignment_id, a.title, a.description, a.deadline, c.course_code, c.course_name,
               sub.submission_id, sub.submitted_at, f.file_name, (sub.submitted_at <= a.deadline)
        FROM assignment a
        JOIN course c ON c.course_code = a.course_code
        LEFT JOIN submission sub ON sub.assignment_id = a.assignment_id AND sub.student_id = %s
        LEFT JOIN stored_file f ON f.file_id = sub.file_id
        WHERE a.course_code IN (SELECT course_code FROM enrollment WHERE student_id = %s)
        ORDER BY a.deadline DESC, a.assignment_id DESC
        """, (student_id, student_id))
    return [{"assignment_id": r[0], "title": r[1], "description": r[2], "deadline": r[3],
             "course_code": r[4], "course_name": r[5], "submission_id": r[6], "submitted_at": r[7],
             "file_name": r[8], "on_time": r[9]} for r in rows]


def submit_homework(student_id, assignment_id, file_name, data):
    """Сдать (или заменить) работу. Опоздание не запрещено — оно просто будет «красным»."""
    stored = None
    old_info = None
    try:
        with transaction() as cur:
            cur.execute("SELECT status FROM student WHERE student_id = %s FOR UPDATE", (student_id,))
            st = cur.fetchone()
            if st is None or st[0] != "Active":
                raise ValueError("Сдавать работы могут только студенты со статусом «Активный».")
            cur.execute(
                """
                SELECT 1 FROM assignment a
                WHERE a.assignment_id = %s
                  AND a.course_code IN (SELECT course_code FROM enrollment WHERE student_id = %s)
                """, (assignment_id, student_id))
            if cur.fetchone() is None:
                raise ValueError("Этого задания нет среди твоих курсов.")

            cur.execute("SELECT f.storage_backend, f.storage_key FROM submission s "
                        "JOIN stored_file f ON f.file_id = s.file_id "
                        "WHERE s.assignment_id = %s AND s.student_id = %s", (assignment_id, student_id))
            old_info = cur.fetchone()
            cur.execute("DELETE FROM submission WHERE assignment_id = %s AND student_id = %s",
                        (assignment_id, student_id))     # старый файл удалит триггер
            file_id, stored = _insert_file(cur, "homework", file_name, data, "student", student_id)
            cur.execute("INSERT INTO submission (assignment_id, student_id, file_id) VALUES (%s, %s, %s)",
                        (assignment_id, student_id, file_id))
    except Exception:
        if stored:
            storage.delete(stored["storage_backend"], stored["storage_key"])
        raise
    if old_info:
        storage.delete(*old_info)


def open_submission(role, user_id, submission_id):
    """Скачать работу: сам студент или преподаватель этого курса."""
    if role == "student":
        row = fetch_one("SELECT file_id FROM submission WHERE submission_id = %s AND student_id = %s",
                        (submission_id, user_id))
    elif role == "instructor":
        row = fetch_one(
            """
            SELECT s.file_id FROM submission s JOIN assignment a ON a.assignment_id = s.assignment_id
            WHERE s.submission_id = %s
              AND a.course_code IN (SELECT course_code FROM teacher WHERE instructor_id = %s)
            """, (submission_id, user_id))
    else:
        row = None
    if row is None:
        raise ValueError("Нет доступа к этому файлу.")
    return _read_file(row[0])


# ------------------------------------------------------------- уборка ----

def purge_student_objects(student_id):
    """
    Перед удалением студента: убирает его файлы из облачного хранилища
    (в базе они удалятся сами каскадом и триггерами).
    """
    infos = fetch_all(
        """
        SELECT f.storage_backend, f.storage_key FROM stored_file f
        WHERE f.storage_backend = 's3' AND f.file_id IN (
            SELECT file_id FROM submission WHERE student_id = %s
            UNION SELECT file_id FROM payment_receipt WHERE student_id = %s)
        """, (student_id, student_id))
    for info in infos:
        storage.delete(*info)
