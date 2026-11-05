"""
app.py
------
Веб-версия Student Portal (Streamlit). Запуск локально:  streamlit run app.py

Это замена main.py + pages_*.py + ui.py (их можно оставить рядом — десктопная
версия на Tkinter по-прежнему работает). Вся работа с базой остаётся в db*.py,
цвета — в colors.py, списки — в constants.py: здесь только интерфейс.
"""

import html
import os
from datetime import date, timedelta

import streamlit as st

import colors as c
import db
import db_hr
import db_it
import db_registrar
from constants import (ACTIVE_INSTRUCTOR, DEPARTMENTS, DEPARTMENTS_SHORT, KIND_LABELS,
                       KIND_PLURAL, MAX_COURSES, PASSWORD_RULES_TEXT, RELATIONSHIP_RU,
                       RELATIONSHIPS, STATUSES, WEEKDAYS_RU, status_label)
from db_core import _get
from utils import format_grade, get_academic_week, matches

st.set_page_config(page_title="Student Portal", page_icon="🎓", layout="centered",
                   initial_sidebar_state="collapsed")

ss = st.session_state
RELATIONSHIP_BY_RU = dict(RELATIONSHIPS)

# Время в журналах база хранит по UTC (Neon). Казахстан сейчас UTC+5.
TZ_OFFSET_HOURS = int(_get("TZ_OFFSET_HOURS", 5))

STAFF_START_PAGE = {"HR": "hr_home", "Registrar": "reg_list", "IT": "it_home"}
LIST_PAGE_BY_KIND = {"student": "it_students", "instructor": "it_instructors", "staff": "it_staff"}
PINK_PAGES = {"student_home", "instructor_home", "hr_home", "it_home", "status_role", "it_menu"}


# =============================================================== состояние ====

def _init():
    ss.setdefault("page", "login")
    ss.setdefault("user", None)
    ss.setdefault("role", None)
    ss.setdefault("ctx", {})
    ss.setdefault("_data", {})
    ss.setdefault("flash", None)
    ss.setdefault("confirm", None)


def go(page, **ctx):
    """Открывает страницу. Именованные аргументы сохраняются в ss.ctx (как раньше в Tkinter)."""
    ss.page = page
    ss.ctx.update(ctx)
    ss._data = {}
    ss.confirm = None


def logout():
    for key in list(ss.keys()):
        del ss[key]


def flash(kind, text):
    ss.flash = (kind, text)


def show_flash():
    if ss.flash:
        kind, text = ss.flash
        ss.flash = None
        {"success": st.success, "info": st.info, "warning": st.warning,
         "error": st.error}.get(kind, st.info)(text)


def set_confirm(value):
    ss.confirm = value


def clear_confirm():
    ss.confirm = None


def refresh():
    """Сбросить загруженные данные и перерисовать страницу."""
    ss._data = {}
    st.rerun()


def q(key, fn, *args, default=None):
    """Данные из базы. Загружаются один раз за открытие страницы (поиск не дёргает базу)."""
    if key in ss._data:
        return ss._data[key]
    try:
        ss._data[key] = fn(*args)
        return ss._data[key]
    except Exception as exc:
        st.error(f"Ошибка подключения к базе данных.\n\n{exc}")
        return default


# ============================================================== оформление ====

def esc(text):
    """Безопасный текст для HTML (и без случайных формул из знака $)."""
    return html.escape("" if text is None else str(text)).replace("$", "&#36;")


def md(text):
    """Экранирует текст для подписей кнопок и markdown."""
    out = "" if text is None else str(text)
    for ch in ("\\", "*", "_", "`", "$", "[", "]", "<", ">", "#"):
        out = out.replace(ch, "\\" + ch)
    return out


def fmt_dt(value):
    """Дата и время 14.10.2026 15:30 (с поправкой на часовой пояс)."""
    if not value:
        return "—"
    return (value + timedelta(hours=TZ_OFFSET_HOURS)).strftime("%d.%m.%Y %H:%M")


def inject_css(pink):
    bg = c.PINK_BG if pink else c.WHITE
    sec_bg = c.WHITE if pink else c.GRAY_LIGHT
    st.markdown(f"""<style>
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"] {{display:none !important;}}
header[data-testid="stHeader"] {{background:transparent;}}
.stApp {{background:{bg};}}
.block-container {{max-width:640px; padding:1rem 1rem 3rem 1rem;}}
html, body, .stApp, .stMarkdown, label, p, li {{
  font-family:'Segoe UI', system-ui, -apple-system, Roboto, 'Helvetica Neue', Arial, sans-serif;
  color:{c.TEXT_DARK};}}
button[data-testid^="stBaseButton-primary"] {{
  background:{c.PINK_MAIN}; color:{c.TEXT_WHITE}; border:none; border-radius:10px;
  font-weight:700; padding:.7rem 1rem; width:100%;}}
button[data-testid^="stBaseButton-primary"]:hover, button[data-testid^="stBaseButton-primary"]:active {{
  background:{c.PINK_DARK}; color:{c.TEXT_WHITE};}}
button[data-testid^="stBaseButton-primary"] p {{color:{c.TEXT_WHITE} !important; font-weight:700;}}
button[data-testid^="stBaseButton-secondary"] {{
  background:{sec_bg}; color:{c.TEXT_DARK}; border:none; border-radius:10px;
  padding:.7rem 1rem; width:100%;}}
button[data-testid^="stBaseButton-secondary"]:hover {{background:{c.PINK_BG}; color:{c.TEXT_DARK};}}
button[data-testid^="stBaseButton-secondary"] p {{color:{c.TEXT_DARK} !important;}}
.st-key-backbar button, .st-key-logout button {{
  background:transparent !important; width:auto; padding:.2rem 0; font-weight:700;}}
.st-key-backbar button:hover, .st-key-logout button:hover {{background:transparent !important;}}
.st-key-backbar button p {{color:{c.TEXT_DARK} !important; font-weight:700;}}
.st-key-logout {{text-align:center;}}
.st-key-rows button {{
  background:{c.WHITE}; border:1px solid {c.GRAY_LINE}; justify-content:flex-start; text-align:left;
  padding:.6rem .8rem; border-radius:8px;}}
.st-key-rows button p {{white-space:normal; font-weight:400;}}
.st-key-rows button:hover {{background:{c.PINK_BG};}}
.ttl {{text-align:center; font-size:1.7rem; font-weight:700; margin:.4rem 0 .6rem; color:{c.TEXT_DARK};}}
.sub {{text-align:center; font-size:1.05rem; color:{c.TEXT_DARK}; margin-bottom:1.4rem;}}
.sub.gray {{color:{c.GRAY_TEXT}; font-size:.95rem; margin-bottom:.8rem;}}
.avatar {{width:120px; height:120px; border-radius:50%; background:{c.PINK_AVATAR}; color:{c.TEXT_WHITE};
  font-size:2.4rem; font-weight:700; display:flex; align-items:center; justify-content:center;
  margin:1.2rem auto .8rem;}}
.badge {{background:{c.PINK_BG}; color:{c.TEXT_DARK}; font-weight:700; text-align:center;
  padding:.6rem 1rem; border-radius:10px; margin:.2rem auto 1rem; width:fit-content;}}
.sect {{font-weight:700; margin:1.2rem 0 .3rem;}}
table.info {{border-collapse:collapse; width:100%; margin:.3rem 0 .8rem;}}
table.info td {{padding:.45rem .3rem; vertical-align:top; border-bottom:1px solid {c.GRAY_LINE};}}
table.info td.k {{color:{c.GRAY_TEXT}; width:42%;}}
table.info td.v {{font-weight:700; word-break:break-word;}}
.tbl-wrap {{overflow-x:auto; margin-bottom:1rem;}}
table.grid {{border-collapse:collapse; width:100%; font-size:.95rem;}}
table.grid th {{background:{c.PINK_BG}; text-align:left; padding:.5rem .5rem; white-space:nowrap;}}
table.grid td {{padding:.5rem .5rem; border-bottom:1px solid {c.GRAY_LINE}; vertical-align:top;}}
.detail {{white-space:pre-wrap; background:{c.GRAY_FIELD}; padding:.7rem .8rem; border-radius:8px;}}
div[data-testid="stForm"] {{border:none; padding:0; background:transparent;}}
</style>""", unsafe_allow_html=True)


def title(text):
    st.markdown(f'<div class="ttl">{esc(text)}</div>', unsafe_allow_html=True)


def subtitle(lines, gray=False):
    if isinstance(lines, str):
        lines = [lines]
    cls = "sub gray" if gray else "sub"
    st.markdown(f'<div class="{cls}">{"<br>".join(esc(x) for x in lines)}</div>',
                unsafe_allow_html=True)


def badge(text):
    st.markdown(f'<div class="badge">{esc(text)}</div>', unsafe_allow_html=True)


def section(text):
    st.markdown(f'<div class="sect">{esc(text)}</div>', unsafe_allow_html=True)


def avatar(name):
    parts = (name or "").split()
    initials = "".join(p[0].upper() for p in parts[:2]) if parts else "?"
    st.markdown(f'<div class="avatar">{esc(initials)}</div>', unsafe_allow_html=True)


def info_table(rows):
    body = "".join(
        f'<tr><td class="k">{esc(k)}</td><td class="v">{esc(v).replace(chr(10), "<br>")}</td></tr>'
        for k, v in rows)
    st.markdown(f'<table class="info">{body}</table>', unsafe_allow_html=True)


def grid_table(headers, rows):
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in r) + "</tr>" for r in rows)
    st.markdown(f'<div class="tbl-wrap"><table class="grid"><thead><tr>{head}</tr></thead>'
                f'<tbody>{body}</tbody></table></div>', unsafe_allow_html=True)


def back_bar(text, page=None, **ctx):
    with st.container(key="backbar"):
        if page is None:
            st.button(text, key="back_btn", on_click=logout)
        else:
            st.button(text, key="back_btn", on_click=go, args=(page,), kwargs=ctx)


def search_box():
    return st.text_input("Поиск", placeholder="🔍 Поиск по ID или имени", key="search",
                         label_visibility="collapsed")


def row_list(items):
    """items: [(метка, страница, ctx), ...] — нажимаемые строки."""
    with st.container(key="rows"):
        for i, (label, page, ctx) in enumerate(items):
            st.button(label, key=f"row_{i}", on_click=go, args=(page,), kwargs=ctx)


def home(name, lines, buttons):
    """Розовый экран: аватарка, имя, подпись и кнопки (как BaseHomeFrame)."""
    avatar(name)
    title(name)
    subtitle(lines)
    for text, page in buttons:
        st.button(text, key=f"nav_{page}", on_click=go, args=(page,))
    st.write("")
    with st.container(key="logout"):
        st.button("Выйти", key="logout_btn", on_click=logout)


def show_error(exc):
    """ValueError — понятная подсказка, остальное — ошибка базы."""
    if isinstance(exc, ValueError):
        st.warning(str(exc))
    else:
        st.error(f"Не получилось выполнить действие.\n\n{exc}")


# ================================================================== вход =====

def p_login():
    title("Student Portal")
    st.write("")
    with st.form("login"):
        role = st.radio("Роль", ["student", "instructor", "staff"], horizontal=True,
                        format_func=lambda r: {"student": "Студент", "instructor": "Преподаватель",
                                               "staff": "Сотрудник"}[r])
        user_id = st.text_input("ID")
        password = st.text_input("Пароль", type="password")
        submitted = st.form_submit_button("REGISTRATION", type="primary")

    if not submitted:
        return
    user_id = user_id.strip()
    if not user_id or not password:
        st.warning("Заполни оба поля: ID и пароль.")
        return

    verify = {"student": db.verify_student, "instructor": db.verify_instructor,
              "staff": db.verify_staff}[role]
    try:
        user = verify(user_id, password)
    except Exception as exc:
        st.error(f"Не получилось подключиться к базе данных.\n\n{exc}")
        return
    if user is None:
        st.error("Неверный ID или пароль.")
        return

    id_key = {"student": "student_id", "instructor": "instructor_id", "staff": "staff_id"}[role]
    try:
        db.log_login(role, user[id_key], user["name"])
    except Exception as exc:
        print("Не удалось записать вход в журнал:", exc)

    ss.user, ss.role = user, role
    go({"student": "student_home", "instructor": "instructor_home"}.get(
        role) or STAFF_START_PAGE[user["department"]])
    st.rerun()


# ============================================================== студент ======

def p_student_home():
    u = ss.user
    home(u["name"], [f"Текущая учебная неделя: {get_academic_week()}"],
         [("Личная информация", "student_info"), ("Оценки", "student_grades")])


def p_student_info():
    u = ss.user
    back_bar("← Назад", "student_home")
    title("Личная информация")
    status = q("status", db.get_student_status, u["student_id"], default=u.get("status"))
    contact = q("contact", db.get_emergency_contact, u["student_id"])
    year = u.get("course_year")
    info_table([
        ("ID студента", u["student_id"]),
        ("Имя и фамилия", u["name"]),
        ("Курс обучения", f"{year} курс" if year else "не указан"),
        ("Статус", status_label("student", status)),
    ])
    section("Экстренный контакт")
    if contact:
        info_table([
            ("Контактное лицо", contact["contact_name"]),
            ("Кем приходится", RELATIONSHIP_RU.get(contact["relationship"], contact["relationship"])),
            ("Телефон", contact["phone"]),
        ])
    else:
        info_table([("Контактное лицо", "—"), ("Кем приходится", "—"), ("Телефон", "—")])


def p_student_grades():
    back_bar("← Назад", "student_home")
    title("Оценки")
    grades = q("grades", db.get_grades, ss.user["student_id"], default=[])
    if not grades:
        badge("Средний балл: —")
        subtitle("Нет данных об оценках.", gray=True)
        return
    numeric = [float(g["grade"]) for g in grades if g["grade"] is not None]
    badge(f"Средний балл: {sum(numeric) / len(numeric):.1f}" if numeric else "Средний балл: —")
    grid_table(["Курс", "Семестр", "Оценка"],
               [(g["course_name"], g["semester"], format_grade(g["grade"])) for g in grades])


# ========================================================== преподаватель ====

def p_instructor_home():
    u = ss.user
    today = date.today()
    home(u["name"], [f"Текущая учебная неделя: {get_academic_week(today)}",
                     f"Сегодня: {WEEKDAYS_RU[today.weekday()]}"],
         [("Личная информация", "instructor_info"), ("Предмет", "instructor_subject")])


def p_instructor_info():
    u = ss.user
    back_bar("← Назад", "instructor_home")
    title("Личная информация")
    info_table([("Почта", u["email"]), ("Департамент", u["department"])])


def p_instructor_subject():
    ins = ss.user
    back_bar("← Назад", "instructor_home")
    title("Предмет")
    courses = q("courses", db.get_instructor_courses, ins["instructor_id"], default=[])
    status = q("istatus", db.get_instructor_status, ins["instructor_id"], default=ins.get("status"))
    can_edit = status == ACTIVE_INSTRUCTOR
    if not courses:
        subtitle("У вас пока нет предметов.", gray=True)
        return

    labels = [f"{x['course_code']} — {x['course_name']}" for x in courses]
    choice = st.selectbox("Предмет", labels, key="subj_course")
    code = courses[labels.index(choice)]["course_code"]

    if can_edit:
        subtitle("Выбери студента ниже, чтобы изменить оценку", gray=True)
    else:
        subtitle(f"Статус: {status_label('instructor', status)}. "
                 f"Режим просмотра — оценки менять нельзя.", gray=True)

    students = q(f"students_{code}", db.get_course_students, ins["instructor_id"], code, default=[])
    if not students:
        subtitle("На этом предмете пока нет студентов.", gray=True)
        return
    grid_table(["ID", "Имя и фамилия", "Курс", "Семестр", "Оценка"],
               [(s["student_id"], s["name"],
                 f"{s['course_year']} курс" if s["course_year"] else "—",
                 s["semester"], format_grade(s["grade"])) for s in students])
    if not can_edit:
        return

    section("Изменить оценку")
    idx = st.selectbox(
        "Студент", range(len(students)), key=f"subj_student_{code}",
        format_func=lambda k: f"{students[k]['student_id']} · {students[k]['name']} · "
                              f"{students[k]['semester']} · {format_grade(students[k]['grade'])}")
    s = students[idx]
    current = float(s["grade"]) if s["grade"] is not None else None
    with st.form(f"grade_{code}_{s['student_id']}_{s['semester']}"):
        new_grade = st.number_input("Новая оценка в процентах (0–100)", min_value=0.0,
                                    max_value=100.0, value=current, step=0.5, format="%.2f")
        saved = st.form_submit_button("Сохранить", type="primary")
    if not saved:
        return
    if new_grade is None:
        st.warning("Введи оценку от 0 до 100.")
        return
    try:
        changed = db.update_grade(ins["instructor_id"], s["student_id"], code, s["semester"],
                                  round(float(new_grade), 2))
    except Exception as exc:
        st.error(f"Не удалось сохранить оценку.\n\n{exc}")
        return
    if changed == 0:
        flash("error", "Оценку изменить нельзя: статус не «Работает» или это не ваш предмет.")
    else:
        flash("success", f"Оценка сохранена: {s['name']} — {format_grade(round(float(new_grade), 2))}.")
    refresh()


# ==================================================================== HR =====

def p_hr_home():
    staff = ss.user
    home(staff["name"], [DEPARTMENTS.get(staff["department"], staff["department"]),
                         f"Текущая учебная неделя: {get_academic_week()}"],
         [("Добавить студента", "hr_add_student"), ("Добавить преподавателя", "hr_add_instructor"),
          ("Изменить статус", "status_role")])


def _next_id_text(table, id_col):
    try:
        return f"{db_hr.peek_next_id(table, id_col)}  (присваивается автоматически)"
    except Exception:
        return "присваивается автоматически"


def p_hr_add_student():
    back_bar("← Главное меню", "hr_home")
    title("Новый студент")
    next_id = q("next_id", _next_id_text, "student", "student_id")
    with st.form("add_student"):
        first = st.text_input("Имя")
        last = st.text_input("Фамилия")
        iin = st.text_input("ИИН (12 цифр)", max_chars=12)
        year = st.selectbox("Курс обучения", [1, 2, 3, 4], index=None, placeholder="Выбери курс")
        st.text_input("ID студента", value=next_id, disabled=True)
        st.text_input("Почта", value="создаётся автоматически", disabled=True)
        st.text_input("Пароль", value="********", disabled=True)
        section("Экстренный контакт")
        contact_name = st.text_input("Имя и фамилия контакта")
        relation = st.selectbox("Кем приходится", [ru for ru, _ in RELATIONSHIPS], index=None,
                                placeholder="Выбери из списка")
        phone = st.text_input("Телефон", placeholder="+7-701-123-4567")
        col1, col2 = st.columns(2)
        save = col1.form_submit_button("Сохранить", type="primary")
        cancel = col2.form_submit_button("Отменить")

    if cancel:
        go("hr_home")
        st.rerun()
    if not save:
        return
    try:
        result = db_hr.create_student(ss.user, first, last, iin.strip(), year, contact_name,
                                      RELATIONSHIP_BY_RU.get(relation), phone)
    except Exception as exc:
        show_error(exc)
        return
    note = (" Экстренный контакт с таким именем уже был в системе — студент привязан к нему."
            if result["contact_reused"] else "")
    flash("success", f"Студент добавлен: {md(result['name'])} · ID {result['student_id']} · "
                     f"почта {md(result['email'])}. Пароль создан автоматически "
                     f"(его видит только IT-департамент).{note}")
    go("hr_home")
    st.rerun()


def p_hr_add_instructor():
    back_bar("← Главное меню", "hr_home")
    title("Новый преподаватель")
    departments = q("deps", db_hr.get_academic_departments, default=[])
    courses = q("all_courses", db_hr.get_all_courses, default=[])
    next_id = q("next_id", _next_id_text, "instructor", "instructor_id")
    labels = [f"{code} — {name}" for code, name in courses]
    with st.form("add_instructor"):
        first = st.text_input("Имя")
        last = st.text_input("Фамилия")
        department = st.selectbox("Департамент", departments, index=None, placeholder="Выбери департамент")
        course = st.selectbox("Предмет", range(len(courses)), index=None, placeholder="Выбери предмет",
                              format_func=lambda k: labels[k])
        st.text_input("ID преподавателя", value=next_id, disabled=True)
        st.text_input("Почта", value="создаётся автоматически", disabled=True)
        st.text_input("Пароль", value="********", disabled=True)
        col1, col2 = st.columns(2)
        save = col1.form_submit_button("Сохранить", type="primary")
        cancel = col2.form_submit_button("Отменить")

    if cancel:
        go("hr_home")
        st.rerun()
    if not save:
        return
    course_code = courses[course][0] if course is not None else None
    try:
        result = db_hr.create_instructor(ss.user, first, last, department, course_code)
    except Exception as exc:
        show_error(exc)
        return
    flash("success", f"Преподаватель добавлен: {md(result['name'])} · ID {result['instructor_id']} · "
                     f"почта {md(result['email'])}. Пароль создан автоматически "
                     f"(его видит только IT-департамент).")
    go("hr_home")
    st.rerun()


def p_status_role():
    back_bar("← Главное меню", "hr_home")
    title("Изменить статус")
    subtitle("Кого выбрать?")
    for text, kind in (("Студент", "student"), ("Преподаватель", "instructor")):
        st.button(text, key=f"kind_{kind}", on_click=go, args=("status_list",),
                  kwargs={"status_kind": kind})


def p_status_list():
    kind = ss.ctx.get("status_kind", "student")
    back_bar("← Назад", "status_role")
    title(KIND_PLURAL[kind])
    people = q(f"people_{kind}", db_hr.list_people_for_status, kind, default=[])
    query = search_box()
    found = [p for p in people if matches(query, p[0], p[1])]
    if not found:
        subtitle("Никого не найдено.", gray=True)
        return
    row_list([(f"{md(name)}  ·  ID {pid}  ·  {status_label(kind, status)}", "status_edit",
               {"status_person": {"kind": kind, "id": pid, "name": name}})
              for pid, name, status in found])


def p_status_edit():
    ctx = ss.ctx.get("status_person")
    back_bar("← Назад", "status_list")
    if not ctx:
        return
    kind = ctx["kind"]
    person = q("person", db_hr.get_person, kind, ctx["id"])
    if person is None:
        st.warning("Такой записи уже нет в базе.")
        return

    title(person["name"])
    subtitle(f"ID {person['id']} · {'Студент' if kind == 'student' else 'Преподаватель'}", gray=True)
    badge(f"Сейчас: {status_label(kind, person['status'])}")

    values = [value for value, _ in STATUSES[kind]]
    labels = [ru for _, ru in STATUSES[kind]]
    current = values.index(person["status"]) if person["status"] in values else None
    pick = st.selectbox("Новый статус", range(len(values)), index=current,
                        format_func=lambda k: labels[k], key=f"status_sel_{kind}_{person['id']}",
                        placeholder="Выбери статус")
    if st.button("Сохранить", key="status_save", type="primary"):
        if pick is None:
            st.warning("Выбери статус из списка.")
        else:
            try:
                changed = db_hr.change_status(ss.user, kind, person["id"], values[pick])
            except Exception as exc:
                show_error(exc)
            else:
                if not changed:
                    st.info("Этот статус уже установлен.")
                else:
                    flash("success", f"Статус изменён: {labels[pick]}.")
                    go("status_list")
                    st.rerun()

    if kind != "student":          # преподавателей удалять нельзя — только менять статус
        return
    if ss.confirm == ("delete", person["id"]):
        st.warning(f"Удалить студента {person['name']} (ID {person['id']}) из системы?\n\n"
                   f"Вместе с ним удалятся его записи на курсы и оценки. "
                   f"Действие запишется в журнал и его нельзя отменить.")
        col1, col2 = st.columns(2)
        if col1.button("Да, удалить", key="del_yes", type="primary"):
            try:
                db_hr.delete_student(ss.user, person["id"])
            except Exception as exc:
                show_error(exc)
            else:
                flash("success", f"Студент {md(person['name'])} удалён из системы.")
                go("status_list")
                st.rerun()
        col2.button("Отмена", key="del_no", on_click=clear_confirm)
    else:
        st.button("Удалить студента", key="del_ask", on_click=set_confirm,
                  args=(("delete", person["id"]),))


# ============================================================ регистратор ====

def p_reg_list():
    staff = ss.user
    back_bar("← Выйти")
    title("Студенты")
    subtitle(f"{staff['name']} · {DEPARTMENTS.get(staff['department'], staff['department'])}", gray=True)
    students = q("students", db_registrar.list_students, default=[])
    query = search_box()
    found = [s for s in students if matches(query, s[0], s[1])]
    if not found:
        subtitle("Никого не найдено.", gray=True)
        return
    row_list([(f"{sid}  ·  {md(name)}", "reg_student", {"reg_student": {"id": sid, "name": name}})
              for sid, name in found])


def p_reg_student():
    student = ss.ctx.get("reg_student")
    back_bar("← Назад", "reg_list")
    if not student:
        return
    title(student["name"])
    subtitle(f"ID {student['id']}", gray=True)

    courses = q("courses", db_registrar.get_student_courses, student["id"], default=[])
    available = q("available", db_registrar.get_available_courses, student["id"], default=[])
    badge(f"Курсы: {len(courses)} из {MAX_COURSES}")

    pending = ss.confirm
    if pending and pending[0] == "remove":
        _, code, sem = pending
        item = next((x for x in courses if x["course_code"] == code and x["semester"] == sem), None)
        if item:
            st.warning(f"Отключить студента {student['name']} от курса "
                       f"{code} — {item['course_name']} ({sem})?\n\n"
                       f"Запись об оценке по этому курсу тоже исчезнет.")
            col1, col2 = st.columns(2)
            if col1.button("Да, удалить", key="rm_yes", type="primary"):
                try:
                    db_registrar.remove_course(ss.user, student["id"], code, sem)
                except Exception as exc:
                    show_error(exc)
                else:
                    flash("success", "Курс удалён.")
                    ss.confirm = None
                    refresh()
            col2.button("Отмена", key="rm_no", on_click=clear_confirm)

    if not courses:
        subtitle("Пока нет ни одного курса.", gray=True)
    for it in courses:
        with st.container(border=True):
            st.markdown(f"**{md(it['course_code'])}** — {md(it['course_name'])}  \n{md(it['semester'])}")
            st.button("Удалить", key=f"rm_{it['course_code']}_{it['semester']}", on_click=set_confirm,
                      args=(("remove", it["course_code"], it["semester"]),))

    section("Добавить курс")
    pick = st.selectbox("Курс", range(len(available)), index=None, placeholder="Выбери курс",
                        format_func=lambda k: f"{available[k][0]} — {available[k][1]}",
                        key=f"add_course_{student['id']}", label_visibility="collapsed")
    if st.button("Добавить", key="add_course_btn", type="primary"):
        if pick is None:
            st.warning("Выбери курс из списка.")
        else:
            try:
                db_registrar.add_course(ss.user, student["id"], available[pick][0])
            except ValueError as exc:
                st.warning(str(exc))
            except Exception as exc:
                st.error(str(exc))
            else:
                flash("success", "Курс добавлен.")
                refresh()


# ==================================================================== IT =====

def p_it_home():
    staff = ss.user
    home(staff["name"], [DEPARTMENTS.get(staff["department"], staff["department"]),
                         f"Текущая учебная неделя: {get_academic_week()}"],
         [("Студенты", "it_students"), ("Преподаватели", "it_instructors"), ("Сотрудники", "it_staff")])


def _it_row_label(kind, p):
    if kind == "student":
        return f"{p['id']}  ·  {md(p['name'])}  ·  вход: {fmt_dt(p['last_login'])}"
    if kind == "instructor":
        return (f"{p['id']}  ·  {md(p['name'])}  ·  вход: {fmt_dt(p['last_login'])}  ·  "
                f"оценка изменена: {fmt_dt(p['last_change'])}")
    dep = DEPARTMENTS_SHORT.get(p["department"], p["department"])
    return (f"{p['id']}  ·  {md(p['name'])}  ·  {dep}  ·  {md(p['last_action'] or '—')}  ·  "
            f"{fmt_dt(p['last_action_time'])}")


def p_it_list(kind):
    back_bar("← Главное меню", "it_home")
    title(KIND_PLURAL[kind])
    subtitle("Поиск по ID или имени. Нажми на имя, чтобы открыть профиль или историю.", gray=True)
    people = q(f"people_{kind}", db_it.list_people, kind, default=[])
    query = search_box()
    found = [p for p in people if matches(query, p["id"], p["name"])]
    if not found:
        subtitle("Никого не найдено.", gray=True)
        return
    row_list([(_it_row_label(kind, p), "it_menu",
               {"it_person": {"kind": kind, "id": p["id"], "name": p["name"]}}) for p in found])


def p_it_menu():
    person = ss.ctx.get("it_person")
    if not person:
        go("it_home")
        st.rerun()
    back_bar("← Назад", LIST_PAGE_BY_KIND[person["kind"]])
    avatar(person["name"])
    title(person["name"])
    subtitle(f"ID {person['id']} · {KIND_LABELS[person['kind']]}")
    st.button("Профиль", key="it_profile_btn", on_click=go, args=("it_profile",))
    st.button("История", key="it_history_btn", on_click=go, args=("it_history",))


def p_it_profile():
    person = ss.ctx.get("it_person")
    back_bar("← Назад", "it_menu")
    if not person:
        return
    kind = person["kind"]
    profile = q("profile", db_it.get_profile, kind, person["id"])
    title("Профиль")
    if profile is None:
        subtitle("Запись не найдена (возможно, её удалили).", gray=True)
        return
    person["name"] = profile["name"]

    rows = [("ID", profile["id"]), ("Имя", profile["name"]), ("Почта", profile["email"])]
    if kind == "student":
        rows += [("ИИН", profile["iin"]), ("Курс обучения", f"{profile['course_year']} курс"),
                 ("Статус", profile["status"]), ("Пароль", profile["password"]),
                 ("Экстренный контакт", profile["contact"] or "—"),
                 ("Курсы", "\n".join(profile["courses"]) or "нет")]
    elif kind == "instructor":
        rows += [("Департамент", profile["department"]), ("Статус", profile["status"]),
                 ("Пароль", profile["password"]),
                 ("Предмет", "\n".join(profile["courses"]) or "нет"),
                 ("Количество студентов", profile["student_count"])]
    else:
        rows += [("Департамент", profile["department"]), ("Пароль", profile["password"]),
                 ("Действий в журнале", profile["actions"])]
    info_table(rows)

    if kind == "instructor":
        st.button("Студенты преподавателя", key="it_students_btn", on_click=go, args=("it_inst_students",))

    with st.expander("Изменить имя"):
        with st.form("edit_name"):
            new_name = st.text_input("Правильное имя и фамилия", value=profile["name"])
            ok = st.form_submit_button("Сохранить имя", type="primary")
        if ok:
            try:
                changed = db_it.update_name(ss.user, kind, person["id"], new_name)
            except Exception as exc:
                show_error(exc)
            else:
                if changed:
                    flash("success", "Имя исправлено. Изменение записано в журнал.")
                refresh()

    with st.expander("Изменить пароль"):
        st.caption(PASSWORD_RULES_TEXT)
        with st.form("edit_password"):
            new_pw = st.text_input(f"Новый пароль для {profile['name']}")
            ok = st.form_submit_button("Сохранить пароль", type="primary")
        if ok:
            try:
                db_it.change_password(ss.user, kind, person["id"], new_pw.strip())
            except Exception as exc:
                show_error(exc)
            else:
                flash("success", "Пароль изменён. Действие записано в журнал.")
                refresh()


def p_it_history():
    person = ss.ctx.get("it_person")
    back_bar("← Назад", "it_menu")
    if not person:
        return
    title("История")
    subtitle(f"{person['name']} · {KIND_LABELS[person['kind']]} · нажми на строку, чтобы увидеть всё",
             gray=True)
    events = q("history", db_it.get_history, person["kind"], person["id"], default=[])
    if not events:
        subtitle("Пока нет записей.", gray=True)
        return
    for i, e in enumerate(events):
        label = f"{fmt_dt(e['time'])} — {md(e['title'])}" + (f" · {md(e['short'])}" if e["short"] else "")
        with st.expander(label):
            st.markdown(f'<div class="detail">{esc(e["details"])}</div>', unsafe_allow_html=True)


def p_it_inst_students():
    person = ss.ctx.get("it_person")
    back_bar("← Назад", "it_profile")
    if not person:
        return
    title("Студенты преподавателя")
    students = q("inst_students", db_it.get_instructor_students, person["id"], default=[])
    subtitle(f"{person['name']} · всего студентов: {len({s['id'] for s in students})}", gray=True)
    if not students:
        subtitle("У этого преподавателя пока нет студентов.", gray=True)
        return
    grid_table(["ID", "Имя и фамилия", "Курс обучения", "Предмет"],
               [(s["id"], s["name"], f"{s['course_year']} курс" if s["course_year"] else "—", s["course"])
                for s in students])


# ============================================================== маршрутизация ==

PAGES = {
    "login": p_login,
    "student_home": p_student_home, "student_info": p_student_info, "student_grades": p_student_grades,
    "instructor_home": p_instructor_home, "instructor_info": p_instructor_info,
    "instructor_subject": p_instructor_subject,
    "hr_home": p_hr_home, "hr_add_student": p_hr_add_student, "hr_add_instructor": p_hr_add_instructor,
    "status_role": p_status_role, "status_list": p_status_list, "status_edit": p_status_edit,
    "reg_list": p_reg_list, "reg_student": p_reg_student,
    "it_home": p_it_home,
    "it_students": lambda: p_it_list("student"),
    "it_instructors": lambda: p_it_list("instructor"),
    "it_staff": lambda: p_it_list("staff"),
    "it_menu": p_it_menu, "it_profile": p_it_profile, "it_history": p_it_history,
    "it_inst_students": p_it_inst_students,
}


def allowed(page):
    """Страница доступна только своей роли (и своему департаменту у сотрудников)."""
    if page == "login":
        return True
    if ss.user is None:
        return False
    if page.startswith("student_"):
        return ss.role == "student"
    if page.startswith("instructor_"):
        return ss.role == "instructor"
    dep = {"hr_": "HR", "status_": "HR", "reg_": "Registrar", "it_": "IT"}
    for prefix, department in dep.items():
        if page.startswith(prefix):
            return ss.role == "staff" and ss.user["department"] == department
    return False


def main():
    _init()
    if ss.page not in PAGES or not allowed(ss.page):
        ss.page = "login"
    inject_css(ss.page in PINK_PAGES)
    show_flash()
    PAGES[ss.page]()


main()
