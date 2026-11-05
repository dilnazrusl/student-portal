# Student Portal (веб-версия)

Запуск на своём компьютере:
    pip install -r requirements.txt
    streamlit run app.py

Файлы:
- app.py — весь интерфейс (замена main.py + pages_*.py + ui.py)
- db.py, db_hr.py, db_it.py, db_registrar.py — запросы к базе (без изменений)
- db_core.py — подключение; пароль берётся из секретов, а не из кода
- colors.py, constants.py, utils.py — без изменений
- update_db_neon.sql — исправленный SQL, load_sql.py — загрузка SQL в Neon одной командой
- .streamlit/config.toml — розовая тема; secrets.toml.example — образец секретов

Деплой: Streamlit Community Cloud (share.streamlit.io) -> New app -> репозиторий -> app.py -> Advanced settings -> Secrets.
