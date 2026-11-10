"""
constants.py
------------
Списки статусов, названия ролей/департаментов и другие справочники.
Если нужно переименовать статус или добавить вариант в выпадающий список —
меняй только здесь (и в CHECK-ограничении в базе данных).
Формат: (значение в базе данных, текст на экране).
"""

# Статусы студентов
STUDENT_STATUSES = [
    ("Active", "Активный"),
    ("Expelled", "Исключён"),
    ("Graduated", "Выпускник"),
    ("Academic leave", "Академический отпуск"),
    ("Academic mobility", "Академическая мобильность (обмен)"),
]

# Статусы преподавателей
INSTRUCTOR_STATUSES = [
    ("Working", "Работает"),
    ("Dismissed", "Уволен"),
    ("Retired", "На пенсии"),
    ("Parental leave", "В декрете"),
    ("Military service", "В армии (место сохранено)"),
]

ACTIVE_STUDENT = "Active"
ACTIVE_INSTRUCTOR = "Working"

STATUSES = {"student": STUDENT_STATUSES, "instructor": INSTRUCTOR_STATUSES}


def status_label(kind, value):
    """'Retired' -> 'На пенсии' (для kind='instructor')."""
    return dict(STATUSES.get(kind, [])).get(value, value or "—")


# Департаменты сотрудников
DEPARTMENTS = {
    "HR": "HR-департамент",
    "Registrar": "Офис регистратора",
    "IT": "IT-департамент",
    "Accounting": "Бухгалтерия",
}

DEPARTMENTS_SHORT = {"HR": "HR", "Registrar": "Регистратор", "IT": "IT", "Accounting": "Бухгалтерия"}

KIND_LABELS = {"student": "Студент", "instructor": "Преподаватель", "staff": "Сотрудник"}
KIND_PLURAL = {"student": "Студенты", "instructor": "Преподаватели", "staff": "Сотрудники"}

# Кем приходится экстренный контакт: (текст в списке, значение в базе)
RELATIONSHIPS = [
    ("Дедушка", "Grandfather"),
    ("Бабушка", "Grandmother"),
    ("Сестра", "Sister"),
    ("Мама", "Mother"),
    ("Папа", "Father"),
    ("Тётя", "Aunt"),
    ("Брат", "Brother"),
    ("Дядя", "Uncle"),
    ("Супруг(а)", "Spouse"),
]
RELATIONSHIP_RU = {en: ru for ru, en in RELATIONSHIPS}
RELATIONSHIP_RU["Guardian"] = "Опекун"

MAX_COURSES = 6  # максимум курсов у одного студента

# Названия действий сотрудников в журнале
ACTION_LABELS = {
    "CREATE_STUDENT": "Добавлен студент",
    "CREATE_INSTRUCTOR": "Добавлен преподаватель",
    "CHANGE_STATUS": "Изменён статус",
    "DELETE_STUDENT": "Удалён студент",
    "ADD_COURSE": "Студенту добавлен курс",
    "REMOVE_COURSE": "У студента удалён курс",
    "EDIT_NAME": "Исправлено имя",
    "CHANGE_PASSWORD": "Изменён пароль",
    "ADD_PAYMENT": "Записана оплата",
    "SET_FUNDING": "Изменена форма обучения",
}

WEEKDAYS_RU = [
    "Понедельник", "Вторник", "Среда", "Четверг",
    "Пятница", "Суббота", "Воскресенье",
]

PASSWORD_RULES_TEXT = (
    "Пароль: минимум 8 символов, хотя бы 1 заглавная (A–Z), 1 строчная (a–z),\n"
    "1 цифра (0–9) и 1 спецсимвол (! @ # $ %)."
)


# ---- Финансы и файлы (веб-версия) ----
FUNDING = [("paid", "Платное"), ("grant", "Грант")]   # форма обучения студента
FUNDING_RU = dict(FUNDING)

PAYMENT_METHODS = [("Kaspi", "Kaspi"), ("Card", "Банковская карта"),
                   ("Cash", "Наличные"), ("Transfer", "Банковский перевод")]
PAYMENT_METHOD_RU = dict(PAYMENT_METHODS)

MAX_FILE_MB = 5   # максимальный размер ЛЮБОГО файла (для всех ролей); тот же лимит в .streamlit/config.toml

# какие расширения можно загружать
ALLOWED_TYPES = {
    "material": ["pdf", "docx", "pptx", "txt", "png", "jpg", "jpeg"],
    "homework": ["pdf", "docx", "txt", "zip", "png", "jpg", "jpeg"],
    "receipt": ["pdf", "png", "jpg", "jpeg"],
}
