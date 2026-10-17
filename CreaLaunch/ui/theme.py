"""Оформление интерфейса: тёмная минималистичная тема.

Принципы: приглушённые цвета (ничего не «светит»), один акцентный цвет —
фиолетовый, минимум рамок и объёмных элементов, ровные поверхности вместо
коробочек.
"""

from __future__ import annotations

import tkinter as tk

from core import png

FONT = "Segoe UI"

COLORS = {
    "bg": "#16131e",           # фон окна (тёмный, с фиолетовым отливом)
    "card": "#1e1a2a",         # поверхность карточек
    "card_alt": "#262033",     # поверхность второго уровня (шапки таблиц и т.п.)
    "hover": "#2b2438",        # наведение
    "border": "#312a44",       # тонкие границы
    "text": "#d9d4e2",         # основной текст (не чистый белый — мягче)
    "text_strong": "#efecf5",
    "muted": "#8b819a",        # второстепенный текст
    "accent": "#6f55c8",       # приглушённый фиолетовый
    "accent_active": "#8065db",
    "accent_soft": "#2b2344",  # фон выбранной строки
    "accent_text": "#b6a3ee",  # акцентный текст
    "console_bg": "#110e18",
    "console_fg": "#c3bdd0",
    "field": "#221d30",        # фон полей ввода
    "field_border": "#332c47",
    "disabled": "#544c63",
}


def setup(style) -> None:
    """Настраивает ttk-стили. Имена стилей совпадают с прежней светлой темой."""
    try:
        setup_option_db(style.master)
    except tk.TclError:
        pass
    style.theme_use("clam")
    base = (FONT, 10)

    style.configure(".", background=COLORS["bg"], foreground=COLORS["text"], font=base,
                    bordercolor=COLORS["border"], lightcolor=COLORS["card"],
                    darkcolor=COLORS["bg"], troughcolor=COLORS["card_alt"],
                    focuscolor=COLORS["card"], relief="flat", borderwidth=0)

    style.configure("TFrame", background=COLORS["bg"])
    style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
    style.configure("Title.TLabel", font=(FONT, 15, "bold"), foreground=COLORS["text_strong"])
    style.configure("Sub.TLabel", foreground=COLORS["muted"], font=(FONT, 9))
    style.configure("Muted.TLabel", foreground=COLORS["muted"], font=(FONT, 9))
    style.configure("Kicker.TLabel", foreground=COLORS["text_strong"], font=(FONT, 10, "bold"))
    style.configure("H1.TLabel", font=(FONT, 10, "bold"), foreground=COLORS["text"])
    style.configure("Stage.TLabel", foreground=COLORS["accent_text"], font=(FONT, 10, "bold"))

    # --- карточки: без рамок, только чуть более светлая поверхность
    style.configure("Card.TFrame", background=COLORS["card"])
    style.configure("Card.TLabel", background=COLORS["card"])
    style.configure("CardMuted.TLabel", background=COLORS["card"], foreground=COLORS["muted"],
                    font=(FONT, 9))
    style.configure("CardH1.TLabel", background=COLORS["card"], foreground=COLORS["text"],
                    font=(FONT, 10, "bold"))
    style.configure("Card.TCheckbutton", background=COLORS["card"])
    style.configure("Card.TRadiobutton", background=COLORS["card"])
    style.configure("Card.TLabelframe", background=COLORS["card"], borderwidth=0, relief="flat")
    style.configure("Card.TLabelframe.Label", background=COLORS["card"],
                    foreground=COLORS["muted"], font=(FONT, 9))

    # --- кнопки
    style.configure("TButton", background=COLORS["card"], foreground=COLORS["text"],
                    padding=(10, 6), borderwidth=0, focusthickness=0,
                    lightcolor=COLORS["card"], darkcolor=COLORS["card"])
    style.map("TButton",
              background=[("active", COLORS["hover"]), ("pressed", COLORS["hover"]),
                          ("disabled", COLORS["card"])],
              lightcolor=[("active", COLORS["hover"])],
              darkcolor=[("active", COLORS["hover"])],
              foreground=[("disabled", COLORS["disabled"])])
    style.configure("Accent.TButton", background=COLORS["accent"], foreground="#f6f3ff",
                    font=(FONT, 12, "bold"), padding=(12, 12), borderwidth=0,
                    lightcolor=COLORS["accent"], darkcolor=COLORS["accent"])
    style.map("Accent.TButton",
              background=[("active", COLORS["accent_active"]), ("pressed", COLORS["accent_active"]),
                          ("disabled", "#312a4d")],
              lightcolor=[("active", COLORS["accent_active"]), ("disabled", "#312a4d")],
              darkcolor=[("active", COLORS["accent_active"]), ("disabled", "#312a4d")],
              foreground=[("disabled", "#7a7292")])
    # большая кнопка «ИГРАТЬ» на баннере
    style.configure("Play.TButton", background=COLORS["accent"], foreground="#f8f5ff",
                    font=(FONT, 14, "bold"), padding=(54, 12), borderwidth=0,
                    lightcolor=COLORS["accent"], darkcolor=COLORS["accent"])
    style.map("Play.TButton",
              background=[("active", COLORS["accent_active"]), ("pressed", COLORS["accent_active"]),
                          ("disabled", "#37305c")],
              lightcolor=[("active", COLORS["accent_active"]), ("disabled", "#37305c")],
              darkcolor=[("active", COLORS["accent_active"]), ("disabled", "#37305c")],
              foreground=[("disabled", "#8a83a5")])
    style.configure("Small.TButton", padding=(8, 4), font=(FONT, 9))

    # --- поля и переключатели
    style.configure("TCombobox", fieldbackground=COLORS["field"], background=COLORS["field"],
                    foreground=COLORS["text"], arrowcolor=COLORS["muted"],
                    bordercolor=COLORS["field_border"], lightcolor=COLORS["field"],
                    darkcolor=COLORS["field"], padding=4, selectbackground=COLORS["field"],
                    selectforeground=COLORS["text"])
    style.map("TCombobox",
              fieldbackground=[("readonly", COLORS["field"])],
              foreground=[("readonly", COLORS["text"])],
              bordercolor=[("focus", COLORS["accent"])])
    for name in ("TCheckbutton", "Card.TCheckbutton", "TRadiobutton", "Card.TRadiobutton"):
        background = COLORS["card"] if name.startswith("Card") else COLORS["bg"]
        style.configure(name, background=background, foreground=COLORS["text"],
                        indicatorbackground=COLORS["field"], indicatorforeground=COLORS["accent"],
                        upperbordercolor=COLORS["field_border"],
                        lowerbordercolor=COLORS["field_border"], focuscolor=background)

    # --- таблицы
    style.configure("Treeview", background=COLORS["card"], fieldbackground=COLORS["card"],
                    foreground=COLORS["text"], rowheight=26, borderwidth=0, relief="flat")
    style.map("Treeview",
              background=[("selected", COLORS["accent_soft"])],
              foreground=[("selected", COLORS["text_strong"])])
    style.configure("Treeview.Heading", background=COLORS["card_alt"], foreground=COLORS["muted"],
                    font=(FONT, 9, "bold"), relief="flat", borderwidth=0, padding=(6, 5))
    style.map("Treeview.Heading", background=[("active", COLORS["hover"])])

    # --- прогресс и полосы прокрутки
    style.configure("Horizontal.TProgressbar", background=COLORS["accent"],
                    troughcolor=COLORS["card_alt"], bordercolor=COLORS["card_alt"],
                    lightcolor=COLORS["accent"], darkcolor=COLORS["accent"],
                    borderwidth=0, thickness=8)
    for orient in ("Vertical", "Horizontal"):
        name = "%s.TScrollbar" % orient
        style.configure(name, background="#2e2740", troughcolor=COLORS["bg"],
                        bordercolor=COLORS["bg"], arrowcolor=COLORS["muted"],
                        lightcolor="#372f4c", darkcolor="#241f33", borderwidth=0,
                        arrowsize=12, relief="flat")
        style.map(name, background=[("active", "#3d3455")])

    # --- ползунок ОЗУ: скопировать раскладку под имя с ориентацией
    for orient in ("Horizontal", "Vertical"):
        name = "%s.Card.TScale" % orient
        try:
            style.layout(name, style.layout("%s.TScale" % orient))
        except tk.TclError:
            pass
        style.configure(name, background=COLORS["accent"], troughcolor=COLORS["field"],
                        bordercolor=COLORS["field"], lightcolor=COLORS["accent"],
                        darkcolor=COLORS["accent"], sliderlength=16, gripsize=0,
                        borderwidth=0, arrowcolor=COLORS["accent"])
    style.configure("TSeparator", background=COLORS["border"])


def setup_option_db(root) -> None:
    """Цвета выпадающего списка ttk.Combobox (он рисуется обычным Tk-listbox)."""
    for pattern in ("*TCombobox*Listbox", "*TCombobox*Listbox*"):
        root.option_add(pattern + ".background", COLORS["card"])
        root.option_add(pattern + ".foreground", COLORS["text"])
        root.option_add(pattern + ".selectBackground", COLORS["accent"])
        root.option_add(pattern + ".selectForeground", "#f6f3ff")
        root.option_add(pattern + ".font", (FONT, 10))


def entry(parent, textvariable=None, width=None, readonly: bool = False, field: str = "field"):
    """Поле ввода: классический tk.Entry — у него можно задать цвет каретки."""
    widget = tk.Entry(
        parent, textvariable=textvariable, font=(FONT, 10), relief="flat", borderwidth=0,
        highlightthickness=1, highlightbackground=COLORS["field_border"],
        highlightcolor=COLORS["accent"], background=COLORS[field], foreground=COLORS["text"],
        insertbackground=COLORS["text"], selectbackground=COLORS["accent"],
        selectforeground="#ffffff", disabledbackground=COLORS["field"],
        disabledforeground=COLORS["disabled"], readonlybackground=COLORS["card_alt"],
    )
    if width:
        widget.configure(width=width)
    if readonly:
        widget.configure(state="readonly", foreground=COLORS["muted"])
    return widget


# ------------------------------------------------ галочки и радиокнопки
# В теме clam «галочка» нарисована крестиком, поэтому рисуем свои индикаторы тем же
# PNG-кодеком и подставляем в классические Checkbutton/Radiobutton (indicatoron=False).

ICON_WIDTH = 21          # 16 пикселей индикатора + 5 пикселей отступа до текста
ICON_HEIGHT = 16
_IMAGES = {}


def _hex(color: str):
    color = color.lstrip("#")
    return tuple(int(color[index:index + 2], 16) for index in (0, 2, 4))


def _paint(data, x, y, color):
    if 0 <= x < ICON_WIDTH and 0 <= y < ICON_HEIGHT:
        index = (y * ICON_WIDTH + x) * 4
        data[index:index + 3] = bytes(color)
        data[index + 3] = 255


def _line(data, x0, y0, x1, y1, color, thickness=2):
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)
    for step in range(steps + 1):
        x = round(x0 + (x1 - x0) * step / steps)
        y = round(y0 + (y1 - y0) * step / steps)
        for offset in range(thickness):
            _paint(data, x + offset, y + offset, color)


def _checkbox_rgba(checked: bool) -> bytes:
    data = bytearray(ICON_WIDTH * ICON_HEIGHT * 4)
    fill = _hex(COLORS["accent"] if checked else COLORS["field"])
    edge = _hex(COLORS["accent"] if checked else COLORS["field_border"])
    for y in range(15):
        for x in range(15):
            inner = 0 < x < 14 and 0 < y < 14
            _paint(data, x, y, fill if inner else edge)
    if checked:
        mark = _hex("#f2eeff")
        _line(data, 3, 7, 6, 10, mark)
        _line(data, 6, 10, 11, 4, mark)
    return bytes(data)


def _radio_rgba(selected: bool) -> bytes:
    data = bytearray(ICON_WIDTH * ICON_HEIGHT * 4)
    ring = _hex(COLORS["accent"] if selected else COLORS["field_border"])
    inside = _hex(COLORS["field"])
    for y in range(ICON_HEIGHT):
        for x in range(ICON_HEIGHT):
            distance = ((x + 0.5 - 7.5) ** 2 + (y + 0.5 - 7.5) ** 2) ** 0.5
            if distance > 7.2:
                continue
            if distance >= 5.7:
                _paint(data, x, y, ring)
            elif selected and distance <= 3.1:
                _paint(data, x, y, ring)
            else:
                _paint(data, x, y, inside)
    return bytes(data)


def _photo(key, rgba):
    if key not in _IMAGES:
        _IMAGES[key] = tk.PhotoImage(data=png.to_photo(ICON_WIDTH, ICON_HEIGHT, rgba))
    return _IMAGES[key]


def check(parent, text, variable, command=None, background=None):
    """Галочка: свой индикатор — квадрат с настоящей галочкой."""
    background = background or COLORS["bg"]
    return tk.Checkbutton(
        parent, text=text, variable=variable, command=command, indicatoron=False,
        image=_photo("check-off", _checkbox_rgba(False)),
        selectimage=_photo("check-on", _checkbox_rgba(True)), compound="left",
        background=background, foreground=COLORS["text"], activebackground=background,
        activeforeground=COLORS["text_strong"], selectcolor=background, borderwidth=0,
        highlightthickness=0, anchor="w", cursor="hand2", font=(FONT, 10))


def radio(parent, text, variable, value, command=None, background=None):
    """Радиокнопка: свой индикатор — кольцо с точкой."""
    background = background or COLORS["bg"]
    return tk.Radiobutton(
        parent, text=text, variable=variable, value=value, command=command, indicatoron=False,
        image=_photo("radio-off", _radio_rgba(False)),
        selectimage=_photo("radio-on", _radio_rgba(True)), compound="left",
        background=background, foreground=COLORS["text"], activebackground=background,
        activeforeground=COLORS["text_strong"], selectcolor=background, borderwidth=0,
        highlightthickness=0, anchor="w", cursor="hand2", font=(FONT, 10))
