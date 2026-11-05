"""
utils.py
--------
Мелкие функции, которые нужны в разных местах: учебная неделя, форматирование
дат и оценок, генерация и проверка паролей, поиск, создание почты.
"""

import re
import secrets
from datetime import date

from constants import PASSWORD_RULES_TEXT


def get_academic_week(today=None):
    """Номер учебной недели от 1 сентября."""
    if today is None:
        today = date.today()
    sept1 = date(today.year, 9, 1)
    start = sept1 if today >= sept1 else date(today.year - 1, 9, 1)
    return (today - start).days // 7 + 1


def current_semester(today=None):
    """Текущий семестр в формате базы: Fall2026 (сент–янв) или Spring2027 (фев–авг)."""
    if today is None:
        today = date.today()
    if today.month >= 9:
        return f"Fall{today.year}"
    if today.month == 1:
        return f"Fall{today.year - 1}"
    return f"Spring{today.year}"


def format_grade(value):
    """85.00 -> '85%', 72.5 -> '72.5%', None -> '—'."""
    if value is None:
        return "—"
    return f"{float(value):g}%"


def format_dt(value):
    """Дата и время в виде 14.10.2026 15:30."""
    return value.strftime("%d.%m.%Y %H:%M") if value else "—"


# ---------------------------------------------------------------- пароли ----

_UP, _LOW, _DIG, _SPEC = "ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnopqrstuvwxyz", "23456789", "!@#$%"


def generate_password():
    """Случайный пароль (12 символов), подходящий под все правила."""
    rnd = secrets.SystemRandom()
    chars = [rnd.choice(_UP), rnd.choice(_UP), rnd.choice(_LOW), rnd.choice(_LOW),
             rnd.choice(_DIG), rnd.choice(_DIG), rnd.choice(_SPEC)]
    chars += [rnd.choice(_UP + _LOW + _DIG + _SPEC) for _ in range(5)]
    rnd.shuffle(chars)
    return "".join(chars)


def validate_password(pw):
    """Возвращает текст ошибки или None, если пароль подходит."""
    ok = (
        len(pw) >= 8
        and re.search(r"[A-Z]", pw)
        and re.search(r"[a-z]", pw)
        and re.search(r"[0-9]", pw)
        and re.search(r"[!@#$%]", pw)
    )
    return None if ok else PASSWORD_RULES_TEXT


# ------------------------------------------------------------ почта/поиск ----

_TRANSLIT = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюяәіңғүұқөһ",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s",
     "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya",
     "a", "i", "n", "g", "u", "u", "k", "o", "h"],
))


def email_local_part(first, last):
    """'Айгерим' 'Касымова' -> 'aigerim.kasymova' (латиницей, без пробелов)."""
    def clean(s):
        s = "".join(_TRANSLIT.get(ch, ch) for ch in s.strip().lower())
        return re.sub(r"[^a-z0-9]", "", s)
    return f"{clean(first)}.{clean(last)}"


def matches(query, person_id, name):
    """Поиск по ID (начало номера) или по части имени."""
    q = query.strip().lower()
    if not q:
        return True
    if q.isdigit():
        return str(person_id).startswith(q)
    return q in name.lower()
