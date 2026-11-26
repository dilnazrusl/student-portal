"""
doc_text.py
-----------
Достаёт текст из загруженных материалов, чтобы умный поиск находил слова ВНУТРИ файлов:
PDF, DOCX, PPTX, XLSX, TXT, MD, CSV. Для картинок и архивов текста нет — ищем по названию.
Всё работает локально, ничего никуда не отправляется. Ошибка чтения файла не мешает загрузке.
"""

import io
import zipfile

MAX_CHARS = 100_000      # больше в базу для поиска не кладём


def _pdf(data):
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


def _docx(data):
    import docx
    d = docx.Document(io.BytesIO(data))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append(" ".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def _pptx(data):
    from pptx import Presentation
    parts = []
    for slide in Presentation(io.BytesIO(data)).slides:
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                parts.append(shape.text_frame.text)
    return "\n".join(parts)


def _xlsx(data):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(ws.title)
        for row in ws.iter_rows(values_only=True):
            parts.append(" ".join(str(v) for v in row if v is not None))
    return "\n".join(parts)


def _plain(data):
    for enc in ("utf-8", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return ""


def _zip(data):
    """Для архива берём только список имён файлов внутри."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return " ".join(z.namelist())


_READERS = {"pdf": _pdf, "docx": _docx, "pptx": _pptx, "xlsx": _xlsx,
            "txt": _plain, "md": _plain, "csv": _plain, "zip": _zip}


def extract_text(file_name, data):
    """Текст файла для поиска или None, если извлечь нечего."""
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    reader = _READERS.get(ext)
    if reader is None:
        return None
    try:
        text = " ".join(reader(data).split())
    except Exception as exc:
        print(f"Не удалось прочитать текст из {file_name}: {exc}")
        return None
    text = text.replace("\x00", "")
    return text[:MAX_CHARS] or None
