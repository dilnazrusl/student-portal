"""
db_nlp.py
---------
Умный поиск (NLP) по курсам, материалам и домашним заданиям.

Что умеет (всё на стороне PostgreSQL, функция search_docs из update_db_4.sql):
  • стемминг: «задания» находит «задание», «networks» находит «network» (русский + английский);
  • опечатки: «databse» найдёт «Database Systems» (триграммы pg_trgm);
  • синонимы: запрос «базы данных» находит курс Database Systems (таблица search_synonym);
  • ранжирование: самые подходящие результаты сверху.

Студент и преподаватель видят материалы и задания ТОЛЬКО своих курсов;
названия курсов в каталоге видны всем.
"""

import re

from db_core import fetch_all

DOC_LABELS = {"course": "Курс", "material": "Материал", "assignment": "Задание"}


def _my_courses(role, user_id):
    if role == "student":
        sql = "SELECT DISTINCT course_code FROM enrollment WHERE student_id = %s"
    elif role == "instructor":
        sql = "SELECT DISTINCT course_code FROM teacher WHERE instructor_id = %s"
    else:
        return None                      # None = все курсы
    return {r[0] for r in fetch_all(sql, (user_id,))}


def search(query, role, user_id, limit=15):
    """[{'type','course_code','course_name','title','body','score','mine'}], лучшие сверху."""
    query = " ".join((query or "").split())[:100]
    if len(query) < 2:
        return []
    mine = _my_courses(role, user_id)
    rows = fetch_all(
        "SELECT doc_type, course_code, title, body, ref_id, score "
        "FROM search_docs(%s, ARRAY(SELECT course_code FROM course), 120)", (query,))
    names = dict(fetch_all("SELECT course_code, course_name FROM course"))
    out = []
    for doc_type, code, title, body, ref_id, score in rows:
        is_mine = mine is None or code in mine
        if doc_type != "course" and not is_mine:
            continue                      # чужие материалы и задания не показываем
        out.append({"type": doc_type, "label": DOC_LABELS.get(doc_type, doc_type),
                    "course_code": code, "course_name": names.get(code, ""),
                    "title": title, "body": body or "", "score": float(score), "mine": is_mine})
    return out[:limit]


def highlight_words(query):
    """Слова запроса для подсветки (по началу слова, чтобы цеплять формы: задани -> задание)."""
    words = re.findall(r"\w+", query.lower())
    return [w[:max(3, len(w) - 2)] for w in words if len(w) >= 3]
