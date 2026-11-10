"""
storage.py
----------
«Шкаф для файлов». Здесь решается, ГДЕ лежит содержимое файла:

  STORAGE_BACKEND = "db"  (по умолчанию) — прямо в базе Neon, ничего настраивать не нужно;
  STORAGE_BACKEND = "s3"  — в облачном объектном хранилище (Cloudflare R2, Backblaze B2,
                            Supabase Storage, AWS S3 — все понимают протокол S3).

Переключение — только через Secrets (см. README), код менять не нужно.
В базе при любом варианте остаётся «карточка» файла (таблица stored_file).
Для S3 в Secrets нужны: S3_BUCKET, S3_KEY_ID, S3_SECRET, S3_ENDPOINT, S3_REGION.
"""

import os
import re
import uuid

from constants import ALLOWED_TYPES, MAX_FILE_MB
from db_core import _get

_client = None


def backend():
    return (_get("STORAGE_BACKEND", "db") or "db").strip().lower()


def check_upload(kind, name, data):
    """Проверка размера и типа. Ошибки — ValueError с понятным текстом."""
    if not data:
        raise ValueError("Файл пустой.")
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise ValueError(f"Файл слишком большой. Максимум — {MAX_FILE_MB} МБ.")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_TYPES[kind]:
        raise ValueError("Такой тип файла не подходит. Можно: " +
                         ", ".join(ALLOWED_TYPES[kind]) + ".")


def safe_name(name):
    base = os.path.basename(name.replace("\\", "/"))
    base = re.sub(r"[^\w.\- ()]", "_", base, flags=re.UNICODE).strip()
    return (base or "file")[:150]


def _s3():
    global _client
    if _client is None:
        import boto3
        _client = boto3.client(
            "s3",
            endpoint_url=_get("S3_ENDPOINT") or None,
            aws_access_key_id=_get("S3_KEY_ID"),
            aws_secret_access_key=_get("S3_SECRET"),
            region_name=_get("S3_REGION", "auto"),
        )
    return _client


def _bucket():
    return _get("S3_BUCKET")


def put(kind, name, data, content_type):
    """Кладёт файл в выбранное хранилище. Возвращает поля для таблицы stored_file."""
    if backend() == "s3":
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else "bin"
        key = f"{kind}/{uuid.uuid4().hex}.{ext}"
        _s3().put_object(Bucket=_bucket(), Key=key, Body=data,
                         ContentType=content_type or "application/octet-stream")
        return {"storage_backend": "s3", "storage_key": key, "content": None}
    return {"storage_backend": "db", "storage_key": None, "content": data}


def get(storage_backend, storage_key, content):
    """Достаёт содержимое файла (по тому, где он лежит на самом деле)."""
    if storage_backend == "s3":
        return _s3().get_object(Bucket=_bucket(), Key=storage_key)["Body"].read()
    return bytes(content) if content is not None else b""


def delete(storage_backend, storage_key):
    """Удаляет объект из облака (для варианта «в базе» ничего делать не нужно)."""
    if storage_backend == "s3" and storage_key:
        try:
            _s3().delete_object(Bucket=_bucket(), Key=storage_key)
        except Exception as exc:
            print("Не удалось удалить файл из хранилища:", exc)
