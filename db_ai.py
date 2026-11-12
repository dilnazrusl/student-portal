"""
db_ai.py
--------
AI-помощник для сотрудников (IT и бухгалтерия): вопрос обычным языком -> SQL -> таблица + ответ.

Как это защищено (несколько слоёв, чтобы помощник физически не мог ничего сломать или утащить):
  1) помощник видит только схему ai (представления БЕЗ паролей и ИИН), см. update_db_4.sql;
  2) запрос выполняется от имени роли, у которой есть ТОЛЬКО SELECT на нужные представления
     (IT — все, бухгалтерия — студенты, курсы, оплаты, баланс);
  3) транзакция READ ONLY, лимит времени 5 секунд, максимум 200 строк;
  4) перед запуском SQL проверяется: один оператор, только SELECT/WITH, без комментариев и
     опасных слов.
Ключ Claude API берётся из Secrets: ANTHROPIC_API_KEY (модель можно сменить в AI_MODEL).
"""

import json
import re

from db_core import _get, get_connection

MODEL_DEFAULT = "claude-sonnet-5-5"
MAX_ROWS = 200

TABLE_DOCS = {
    "student": "student(student_id, name, email, course_year 1-4, status, funding 'paid'|'grant')",
    "instructor": "instructor(instructor_id, name, email, department, status)",
    "course": "course(course_code, course_name, credits, price_kzt)",
    "teacher": "teacher(instructor_id, course_code) — какой преподаватель ведёт какой курс",
    "enrollment": "enrollment(student_id, course_code, semester 'Fall2025', grade 0-100 или NULL)",
    "assessment": "assessment(student_id, course_code, semester, kind 'midterm'|'endterm'|'final', score 0-100, "
                  "course_avg, diff_from_avg, z_score) — оценки за работы и их нормализация",
    "gpa": "gpa(student_id, semester, gpa 0-4, avg_grade, credits)",
    "payment": "payment(payment_id, student_id, amount KZT, method 'Kaspi'|'Card'|'Cash'|'Transfer', note, paid_at)",
    "balance": "balance(student_id, name, funding, total_kzt стоимость курсов, paid_kzt оплачено, debt_kzt долг)",
    "assignment": "assignment(assignment_id, course_code, instructor_id, title, deadline)",
    "submission": "submission(submission_id, assignment_id, student_id, submitted_at, on_time boolean)",
}

ROLES = {
    "IT": {"pg_role": "portal_ai_it", "tables": list(TABLE_DOCS)},
    "Accounting": {"pg_role": "portal_ai_acc", "tables": ["student", "course", "payment", "balance"]},
}

EXAMPLES = {
    "IT": ["Сколько студентов в каждом статусе?",
           "Топ-5 курсов по среднему баллу",
           "У каких студентов GPA ниже 2 в последнем семестре?"],
    "Accounting": ["У кого долг больше 200 000 ₸?",
                   "Сколько поступило оплат по месяцам?",
                   "Какой способ оплаты самый популярный?"],
}

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|call|do|execute|"
    r"set|reset|listen|notify|vacuum|lock|merge|into)\b|pg_|information_schema|\bpublic\s*\.",
    re.IGNORECASE)


def available(department):
    return department in ROLES


def examples(department):
    return EXAMPLES.get(department, [])


def validate_sql(sql):
    """Возвращает чистый SQL или поднимает ValueError."""
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise ValueError("Пустой запрос.")
    if ";" in sql:
        raise ValueError("Можно только один запрос.")
    if "--" in sql or "/*" in sql:
        raise ValueError("Комментарии в запросе не допускаются.")
    if not re.match(r"(?is)^\s*(select|with)\b", sql):
        raise ValueError("Разрешены только запросы на чтение (SELECT).")
    bad = _FORBIDDEN.search(sql)
    if bad:
        raise ValueError(f"В запросе есть запрещённое выражение: «{bad.group(0)}».")
    return sql


# ------------------------------------------------------------------ Claude ----

def _client():
    key = _get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("AI-помощник не настроен: добавь ANTHROPIC_API_KEY в Secrets.")
    import anthropic
    return anthropic.Anthropic(api_key=key)


def _call(system, messages, max_tokens=700):
    resp = _client().messages.create(model=_get("AI_MODEL", MODEL_DEFAULT), max_tokens=max_tokens,
                                     system=system, messages=messages)
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


def _system_prompt(department):
    docs = "\n".join("  " + TABLE_DOCS[t] for t in ROLES[department]["tables"])
    return (
        "Ты помощник университетского портала. Превращай вопрос пользователя в ОДИН SQL-запрос "
        "PostgreSQL только на чтение.\n"
        "Доступные таблицы (других нет):\n" + docs + "\n"
        "Правила: только SELECT/WITH; без комментариев и точки с запятой; давай колонкам понятные "
        "английские алиасы; для 'последнего семестра' используй самый поздний semester в данных "
        "(семестры вида Spring2025, Fall2025); деньги в тенге. Если вопрос не про эти данные или "
        "нужны недоступные данные — откажись.\n"
        'Ответ СТРОГО в JSON без пояснений: {"sql": "..."} либо {"refuse": "причина по-русски"}.')


def _parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("Помощник ответил непонятно. Попробуй переформулировать вопрос.")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        raise ValueError("Помощник ответил непонятно. Попробуй переформулировать вопрос.")


# --------------------------------------------------------------- выполнение ----

def run_readonly(department, sql):
    """Выполняет проверенный SELECT от имени роли только на чтение. -> (колонки, строки)."""
    role = ROLES[department]["pg_role"]
    sql = validate_sql(sql)
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '5s'")
            cur.execute("SAVEPOINT use_role")
            try:
                cur.execute(f"SET LOCAL ROLE {role}")
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT use_role")
                raise ValueError("Роли AI не настроены в базе. Запусти update_db_4.sql ещё раз "
                                 "(нужны права на создание ролей).")
            cur.execute("SET LOCAL search_path TO ai, pg_catalog")
            cur.execute(f"SELECT * FROM ({sql}) AS t LIMIT {MAX_ROWS}")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        conn.rollback()
        return cols, rows
    finally:
        conn.close()


def ask(department, question):
    """
    -> {'sql', 'columns', 'rows', 'answer'}. Ошибки, понятные человеку, — ValueError.
    """
    if department not in ROLES:
        raise ValueError("Для твоего отдела AI-помощник не подключён.")
    question = " ".join((question or "").split())[:500]
    if len(question) < 3:
        raise ValueError("Напиши вопрос подробнее.")

    system = _system_prompt(department)
    messages = [{"role": "user", "content": question}]
    cols = rows = sql = None
    last_error = None
    for _attempt in range(2):                       # одна попытка исправить ошибку SQL
        data = _parse_json(_call(system, messages))
        if data.get("refuse"):
            raise ValueError(str(data["refuse"]))
        sql = data.get("sql", "")
        try:
            cols, rows = run_readonly(department, sql)
            last_error = None
            break
        except ValueError as exc:
            if "Роли AI" in str(exc):
                raise
            last_error = exc
        except Exception as exc:
            last_error = exc
        messages += [{"role": "assistant", "content": json.dumps({"sql": sql}, ensure_ascii=False)},
                     {"role": "user", "content": f"Запрос не сработал: {last_error}. Исправь и верни JSON."}]
    if last_error is not None:
        raise ValueError("Не получилось составить рабочий запрос. Попробуй спросить иначе.")

    sample = [dict(zip(cols, r)) for r in rows[:30]]
    answer = _call(
        "Ты помощник университетского портала. Коротко (1–3 предложения) ответь по-русски на вопрос, "
        "опираясь ТОЛЬКО на данные таблицы. Не выдумывай. Если строк нет — скажи, что данных нет.",
        [{"role": "user", "content": f"Вопрос: {question}\nВсего строк: {len(rows)}\n"
                                     f"Данные (первые 30): {json.dumps(sample, ensure_ascii=False, default=str)}"}],
        max_tokens=300)
    return {"sql": sql, "columns": cols, "rows": rows, "answer": answer}
