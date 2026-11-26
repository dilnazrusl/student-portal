# Student Portal

Университетский портал на Python + Streamlit + PostgreSQL (Neon). Роли: студент, преподаватель, сотрудники
(HR, регистратор, IT, бухгалтерия). Сайт открывается по ссылке из браузера, в том числе с телефона.

## Что внутри
- **Умный поиск** (стемминг, опечатки, синонимы) — ищет и внутри PDF, DOCX, PPTX, XLSX, CSV, TXT, MD и показывает фрагмент.
- **Материалы курсов**: файлы до 10 МБ, хранятся в базе Neon (`STORAGE_BACKEND=db`, по умолчанию).
- **Финансы**, **задания с дедлайнами**, **расписание и регистрация на курсы** с бронированием времени.
- **AI-помощник** для IT и бухгалтерии: вопрос обычным языком → безопасный SQL (только чтение) → ответ. Модель — Claude.

## Файлы
- `app.py` — сайт; `db_*.py` — работа с базой; `storage.py` — где лежат файлы; `doc_text.py` — текст из документов.
- `sql/` — SQL-файлы по порядку 01 → 05 (для новой базы); для готовой базы Neon нужен только `neon_update_5_6.sql`.
- `seed_documents.py` — один раз кладёт в базу 365 тестовых документов.
- `.streamlit/secrets.toml.example` — образец настроек (настоящий `secrets.toml` на GitHub не загружается).

## Настройки (Streamlit Cloud → Settings → Secrets)
`DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SSLMODE="require", ANTHROPIC_API_KEY, AI_PROVIDER="anthropic"`.

## Запуск на компьютере (для разработки)
```
pip install -r requirements.txt
streamlit run app.py
```
Настройки берутся из `.streamlit/secrets.toml` (скопируй из `secrets.toml.example`).
