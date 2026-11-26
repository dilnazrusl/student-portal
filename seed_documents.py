"""
seed_documents.py
-----------------
Заполняет материалы курсов тестовыми документами РАЗНЫХ форматов и в РАЗНОМ количестве
(у одного курса 1 файл, у другого 6): PDF, DOCX, PPTX, XLSX, CSV, TXT, MD, PNG, ZIP.
Внутри файлов настоящий текст по теме курса, поэтому умный поиск находит слова ВНУТРИ PDF и DOCX.

Файлы загружаются тем же кодом, что и с сайта (db_files.add_material), поэтому кладутся туда,
куда указывает STORAGE_BACKEND (в Docker-версии — в папку на диске).
Запускается один раз (флаг seed_v5 в таблице app_setting). Принудительно: python seed_documents.py --force
"""

import io
import os
import sys
import zipfile

from db_core import fetch_all, fetch_one, transaction
import db_files

FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "C:/Windows/Fonts/arial.ttf", "/Library/Fonts/Arial.ttf"]
FORMATS = ["pdf", "docx", "pptx", "xlsx", "txt", "csv", "png", "zip", "md"]   # 9 — шаг 2 даёт без повторов
KIND_TITLE = {"pdf": "Лекция", "docx": "Конспект", "pptx": "Презентация", "xlsx": "Таблица с примерами",
              "txt": "Краткие заметки", "csv": "Набор данных", "png": "Схема", "zip": "Архив с примерами",
              "md": "Шпаргалка"}

TOPICS = {
    "database": ["SQL: запросы SELECT, JOIN, GROUP BY и подзапросы", "нормализация: 1NF, 2NF, 3NF и BCNF",
                 "транзакции и свойства ACID", "индексы и ускорение запросов", "ER-диаграммы и ключи"],
    "programming": ["переменные, условия и циклы", "функции и рекурсия", "классы и объектно-ориентированное "
                    "программирование", "работа с файлами и исключениями", "тестирование и отладка кода"],
    "ai": ["поиск в пространстве состояний", "экспертные системы и логика", "нейронные сети и обучение",
           "обработка естественного языка", "этика искусственного интеллекта"],
    "web": ["HTML, CSS и вёрстка страниц", "JavaScript и работа с DOM", "REST API и JSON",
            "аутентификация и безопасность сайтов", "развёртывание веб-приложений"],
    "data structures": ["массивы и связные списки", "стеки и очереди", "деревья и хеш-таблицы", "графы",
                        "оценка сложности операций"],
    "algorithms": ["сортировка и поиск", "жадные алгоритмы", "динамическое программирование",
                   "алгоритмы на графах", "O-нотация и сложность"],
    "operating": ["процессы и потоки", "планирование процессов", "управление памятью", "файловые системы",
                  "синхронизация и взаимные блокировки"],
    "network": ["модель OSI и TCP/IP", "IP-адресация и маршрутизация", "протоколы HTTP и DNS",
                "безопасность сетей", "беспроводные сети"],
    "machine learning": ["линейная и логистическая регрессия", "деревья решений и ансамбли",
                         "нейронные сети", "переобучение и валидация", "метрики качества моделей"],
    "discrete": ["множества и отношения", "логика высказываний", "комбинаторика", "графы и деревья",
                 "булева алгебра"],
    "linear algebra": ["векторы и матрицы", "определители", "системы линейных уравнений",
                       "собственные значения и векторы", "линейные преобразования"],
    "statistics": ["описательная статистика", "вероятность и распределения", "проверка гипотез",
                   "доверительные интервалы", "корреляция и регрессия"],
    "calculus": ["пределы и непрерывность", "производные", "интегралы", "ряды", "дифференциальные уравнения"],
    "software": ["жизненный цикл разработки", "требования и UML", "паттерны проектирования",
                 "тестирование и CI/CD", "agile и scrum"],
    "business": ["сбор и очистка данных", "KPI и дашборды", "A/B-тесты", "прогнозирование спроса",
                 "визуализация данных"],
    "marketing": ["сегментация аудитории", "SEO и контент", "реклама в социальных сетях", "email-рассылки",
                  "аналитика конверсии"],
    "economics": ["спрос и предложение", "эластичность", "рыночные структуры", "инфляция и ВВП",
                  "фискальная и монетарная политика"],
}
GENERIC = ["основные понятия", "ключевые методы", "практические примеры", "типичные ошибки", "итоги и вопросы"]


def _topics(course_name):
    low = course_name.lower()
    for key, topics in TOPICS.items():
        if key in low:
            return topics
    return GENERIC


def _font():
    return next((p for p in FONT_PATHS if os.path.exists(p)), None)


def _paragraphs(course_name, j, topics):
    t = topics[(j - 1) % len(topics)]
    t2 = topics[j % len(topics)]
    return [
        f"{course_name}. Тема {j}: {t}.",
        f"В этом материале разобраны основные понятия по теме «{t}». Сначала даётся определение, "
        f"затем несколько примеров, после этого — типичные ошибки студентов и способы их избежать.",
        f"Связь с другими темами курса: {t2}. Рекомендуется повторить предыдущую лекцию перед "
        f"выполнением домашнего задания.",
        f"Вопросы для самопроверки: что такое {t}? Где это применяется на практике? "
        f"Какие ограничения у подхода?",
    ]


# ------------------------------------------------------------ построители ----

def b_pdf(title, paras):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    path = _font()
    name = "Helvetica"
    if path:
        pdfmetrics.registerFont(TTFont("DejaVu", path))
        name = "DejaVu"
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(title)
    c.setFont(name, 16)
    c.drawString(50, 790, title[:70])
    c.setFont(name, 11)
    y = 755
    for p in paras:
        words, line = p.split(), ""
        for w in words:
            if c.stringWidth(line + " " + w, name, 11) > 495:
                c.drawString(50, y, line)
                y -= 16
                line = w
            else:
                line = (line + " " + w).strip()
        c.drawString(50, y, line)
        y -= 26
    c.save()
    return buf.getvalue()


def b_docx(title, paras):
    import docx
    d = docx.Document()
    d.add_heading(title, level=1)
    for p in paras:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def b_pptx(title, paras):
    from pptx import Presentation
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = title
    s.placeholders[1].text = paras[0]
    for p in paras[1:]:
        sl = prs.slides.add_slide(prs.slide_layouts[1])
        sl.shapes.title.text = p.split(".")[0][:60]
        sl.placeholders[1].text = p
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def b_xlsx(title, paras):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Примеры"
    ws.append(["№", "Описание", "Баллы"])
    for i, p in enumerate(paras, 1):
        ws.append([i, p[:120], 10 * i])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def b_txt(title, paras):
    return (title + "\n\n" + "\n\n".join(paras)).encode("utf-8")


def b_md(title, paras):
    return ("# " + title + "\n\n" + "\n\n".join("- " + p for p in paras)).encode("utf-8")


def b_csv(title, paras):
    rows = ["id;описание;баллы"] + [f"{i};{p.replace(';', ',')};{10 * i}" for i, p in enumerate(paras, 1)]
    return ("\n".join(rows)).encode("utf-8")


def b_png(title, paras):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (900, 420), "#FFD6E8")
    dr = ImageDraw.Draw(img)
    path = _font()
    big = ImageFont.truetype(path, 30) if path else ImageFont.load_default()
    small = ImageFont.truetype(path, 18) if path else ImageFont.load_default()
    dr.rectangle([20, 20, 880, 400], outline="#FF5FA2", width=4)
    dr.text((40, 40), title[:50], fill="#333333", font=big)
    dr.text((40, 120), paras[0][:80], fill="#333333", font=small)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def b_zip(title, paras):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", title + "\n\n" + paras[0])
        z.writestr("example_1.txt", paras[1])
        z.writestr("example_2.txt", paras[2])
    return buf.getvalue()


BUILDERS = {"pdf": b_pdf, "docx": b_docx, "pptx": b_pptx, "xlsx": b_xlsx, "txt": b_txt, "csv": b_csv,
            "png": b_png, "zip": b_zip, "md": b_md}


def main(force=False):
    if not force and fetch_one("SELECT 1 FROM app_setting WHERE setting_key = 'seed_v5'"):
        print("Тестовые документы уже загружены (seed_v5). Для повтора: --force")
        return
    courses = fetch_all(
        """
        SELECT t.course_code, c.course_name, min(t.instructor_id)
        FROM teacher t JOIN course c ON c.course_code = t.course_code
        JOIN instructor i ON i.instructor_id = t.instructor_id AND i.status = 'Working'
        GROUP BY t.course_code, c.course_name ORDER BY t.course_code
        """)
    total, per_format = 0, {}
    for idx, (code, cname, iid) in enumerate(courses):
        topics = _topics(cname)
        count = 1 + (idx * 5 + len(cname)) % 6                 # 1..6 документов, у разных курсов по-разному
        for j in range(1, count + 1):
            ext = FORMATS[(idx + j * 2) % len(FORMATS)]
            title = f"{KIND_TITLE[ext]} {j} — {cname}"
            data = BUILDERS[ext](title, _paragraphs(cname, j, topics))
            try:
                db_files.add_material(iid, code, title, f"{ext}_{code}_{j}.{ext}", data)
            except Exception as exc:
                print(f"Пропущен {code} / {ext}: {exc}")
                continue
            total += 1
            per_format[ext] = per_format.get(ext, 0) + 1
    with transaction() as cur:
        cur.execute("INSERT INTO app_setting (setting_key, setting_value) VALUES ('seed_v5', 'done') "
                    "ON CONFLICT (setting_key) DO NOTHING")
    print(f"Загружено документов: {total}. По форматам: {per_format}")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
