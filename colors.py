"""
colors.py
---------
Все цвета и шрифты интерфейса собраны здесь в одном месте.
Если захочешь поменять оттенок розового или шрифт — меняй только тут,
остальные файлы ничего знать об этом не должны.
"""

# ---- Цвета ----
WHITE = "#FFFFFF"

PINK_MAIN = "#FF5FA2"     # основной розовый — цвет кнопок
PINK_DARK = "#E0458C"     # чуть темнее розовый — для наведения мыши на кнопку
PINK_BG = "#FFD6E8"       # светло-розовый — фон страниц аккаунта
PINK_AVATAR = "#FF8FC2"   # розовый — цвет круга-аватарки

TEXT_DARK = "#333333"     # тёмно-серый текст на светлом фоне
TEXT_WHITE = "#FFFFFF"    # белый текст на розовых кнопках/фоне

# ---- Шрифты ----
FONT_TITLE = ("Segoe UI", 22, "bold")
FONT_SUBTITLE = ("Segoe UI", 14)
FONT_BUTTON = ("Segoe UI", 14, "bold")
FONT_LABEL = ("Segoe UI", 12)
FONT_LABEL_BOLD = ("Segoe UI", 12, "bold")
FONT_AVATAR_INITIALS = ("Segoe UI", 28, "bold")

# ---- Дополнительные серые тона (для линий, неактивных полей и кнопки «Отмена») ----
GRAY_LIGHT = "#EEEEEE"
GRAY_FIELD = "#F4F4F4"
GRAY_TEXT = "#777777"
GRAY_LINE = "#EDEDED"
