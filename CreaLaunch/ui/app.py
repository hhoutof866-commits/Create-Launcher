"""Окно лаунчера на tkinter: профиль, моды, каталог, скины, настройки."""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, simpledialog, ttk

from core import (auth, branding, config, install, javas, launch, modrinth, mods,
                  neoforge, options, paths, png, shortcut, skins)
from core.config import Config
from core.down import DownloadCancelled, Downloader

from . import theme

APP_TITLE = "NeoForge Launcher — Minecraft 1.21.1"
WORLD_GLOBAL = "‹общая папка (все миры)›"
MODELS = {"Широкие руки (Steve)": "wide", "Тонкие руки (Alex)": "slim"}


def human_size(value: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if abs(value) < 1024 or unit == "ГБ":
            return "%.0f %s" % (value, unit) if unit == "Б" else "%.1f %s" % (value, unit)
        value /= 1024.0
    return "%.1f ГБ" % value


class LauncherApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = Config.load()
        self.queue = queue.Queue()
        self.process = None
        self.busy = False
        self.downloader = None
        self.launcher_mods = []
        self.java_list = []
        self.neo_versions = []
        self.results = []
        self.skin_data = b""
        self.search_offset = 0

        theme.setup(ttk.Style())
        self._build_ui()
        self._apply_config()

        root.title(APP_TITLE)
        root.minsize(900, 620)
        height = max(620, min(850, root.winfo_screenheight() - 90))
        root.geometry("1000x%d" % height)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(80, self._pump)
        threading.Thread(target=self._probe, daemon=True).start()

    # =============================================================== интерфейс
    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=(14, 12, 14, 10))
        outer.pack(fill="both", expand=True)

        self._build_header(outer)
        self._build_profile(outer)
        self._build_run(outer)

        self._build_tabs(outer)

        self.footer = ttk.Label(outer, style="Muted.TLabel", anchor="w")
        self.footer.pack(fill="x", pady=(8, 0))

    def _build_tabs(self, outer):
        """Своя полоса вкладок: плоские подписи, у активной — акцентная черта."""
        self.tab_bar = tk.Frame(outer, background=theme.COLORS["bg"])
        self.tab_bar.pack(fill="x", pady=(12, 0))
        separator = tk.Frame(outer, height=1, background=theme.COLORS["border"])
        separator.pack(fill="x")
        self.tab_body = ttk.Frame(outer)
        self.tab_body.pack(fill="both", expand=True, pady=(8, 0))
        self.tab_body.rowconfigure(0, weight=1)
        self.tab_body.columnconfigure(0, weight=1)

        self.tabs = {}          # имя -> (рамка, подпись, черта)
        self.tab_order = []
        self._build_console_tab(self.tab_body)
        self._build_mods_tab(self.tab_body)
        self._build_content_tab(self.tab_body)
        self._build_skins_tab(self.tab_body)
        self._build_settings_tab(self.tab_body)
        self.show_tab(self.tab_order[0])

    def _add_tab(self, name, frame):
        frame.grid(row=0, column=0, sticky="nsew")
        holder = tk.Frame(self.tab_bar, background=theme.COLORS["bg"], cursor="hand2")
        holder.pack(side="left", padx=(0, 4))
        label = tk.Label(holder, text=name, background=theme.COLORS["bg"],
                         foreground=theme.COLORS["muted"], font=(theme.FONT, 10),
                         padx=12, pady=6)
        label.pack()
        line = tk.Frame(holder, height=2, background=theme.COLORS["bg"])
        line.pack(fill="x")
        for widget in (holder, label):
            widget.bind("<Button-1>", lambda _event, item=name: self.show_tab(item))
        self.tabs[name] = (frame, label, line)
        self.tab_order.append(name)

    def show_tab(self, name):
        """Показывает вкладку по имени (или по номеру)."""
        if isinstance(name, int) and 0 <= name < len(self.tab_order):
            name = self.tab_order[name]
        if name not in self.tabs:
            return
        for item, (_frame, label, line) in self.tabs.items():
            active = item == name
            label.configure(font=(theme.FONT, 10, "bold") if active else (theme.FONT, 10),
                            foreground=theme.COLORS["text"] if active else theme.COLORS["muted"])
            line.configure(background=theme.COLORS["accent"] if active else theme.COLORS["bg"])
        self.tabs[name][0].tkraise()
        self.current_tab = name

    def _build_header(self, outer):
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 8))
        icon, logo = branding.ensure()
        self.logo_image = None
        if logo and os.path.exists(logo):
            try:
                self.logo_image = tk.PhotoImage(file=logo)
            except tk.TclError:
                self.logo_image = None
        if self.logo_image is not None:
            ttk.Label(header, image=self.logo_image).pack(side="left", padx=(0, 10))
        titles = ttk.Frame(header)
        titles.pack(side="left", fill="x", expand=True)
        ttk.Label(titles, text="NeoForge Launcher", style="Title.TLabel").pack(anchor="w")
        ttk.Label(titles, text="Minecraft 1.21.1 + NeoForge — установка, моды, скины",
                  style="Sub.TLabel").pack(anchor="w")

    def _build_profile(self, outer):
        card = ttk.Labelframe(outer, text=" Профиль ", style="Card.TLabelframe", padding=10)
        card.pack(fill="x")
        for column in (1, 3, 5):
            card.columnconfigure(column, weight=1)

        ttk.Label(card, text="Никнейм:", style="Card.TLabel").grid(row=0, column=0, sticky="w",
                                                                 padx=(0, 6))
        self.user_var = tk.StringVar()
        theme.entry(card, textvariable=self.user_var, width=16).grid(
            row=0, column=1, sticky="ew", ipady=3)

        ttk.Label(card, text="Режим:", style="Card.TLabel").grid(row=0, column=2, sticky="w",
                                                                padx=(14, 6))
        self.mode_var = tk.StringVar()
        mode_box = ttk.Combobox(card, textvariable=self.mode_var, state="readonly", width=18,
                                values=["NeoForge (моды)", "Ванильный (без модов)"])
        mode_box.grid(row=0, column=3, sticky="ew")
        mode_box.bind("<<ComboboxSelected>>", lambda _e: self._on_mode_change())

        ttk.Label(card, text="NeoForge:", style="Card.TLabel").grid(row=0, column=4, sticky="w",
                                                                   padx=(14, 6))
        self.neo_var = tk.StringVar()
        self.neo_box = ttk.Combobox(card, textvariable=self.neo_var, width=16)
        self.neo_box.grid(row=0, column=5, sticky="ew")

        ttk.Label(card, text="Оперативная память:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", pady=(9, 0), padx=(0, 6))
        ram_frame = ttk.Frame(card, style="Card.TFrame")
        ram_frame.grid(row=1, column=1, columnspan=3, sticky="ew", pady=(9, 0))
        ram_frame.columnconfigure(0, weight=1)
        self.ram_var = tk.IntVar(value=4096)
        self.ram_scale = ttk.Scale(ram_frame, from_=1024, to=16384, orient="horizontal",
                                   style="Card.TScale", command=self._on_ram_change)
        self.ram_scale.grid(row=0, column=0, sticky="ew")
        self.ram_label = ttk.Label(ram_frame, text="4096 МБ", style="CardMuted.TLabel", width=24)
        self.ram_label.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.mc_var = tk.StringVar(value="1.21.1")
        ttk.Label(card, text="Minecraft:", style="Card.TLabel").grid(row=1, column=4, sticky="w",
                                                                     padx=(14, 6), pady=(9, 0))
        ttk.Label(card, textvariable=self.mc_var, style="CardMuted.TLabel").grid(
            row=1, column=5, sticky="w", pady=(9, 0))

        ttk.Label(card, text="Папка игры:", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", pady=(9, 0), padx=(0, 6))
        self.dir_var = tk.StringVar()
        theme.entry(card, textvariable=self.dir_var, readonly=True).grid(
            row=2, column=1, columnspan=4, sticky="ew", pady=(9, 0), ipady=3)
        ttk.Button(card, text="Изменить…", style="Small.TButton",
                   command=self._choose_dir).grid(row=2, column=5, sticky="e", padx=(8, 0),
                                                  pady=(9, 0))

    def _build_run(self, outer):
        frame = ttk.Frame(outer, padding=(0, 10, 0, 0))
        frame.pack(fill="x")
        frame.columnconfigure(0, weight=1)
        self.play_button = ttk.Button(frame, text="ИГРАТЬ", style="Accent.TButton",
                                      command=self._on_play)
        self.play_button.grid(row=0, column=0, sticky="ew")

        right = ttk.Frame(frame)
        right.grid(row=0, column=1, sticky="n", padx=(10, 0))
        self.install_button = ttk.Button(right, text="Установить / проверить",
                                         command=self._on_install)
        self.install_button.pack(fill="x")
        self.cancel_button = ttk.Button(right, text="Отменить", command=self._on_cancel,
                                        state="disabled")
        self.cancel_button.pack(fill="x", pady=(6, 0))

        status = ttk.Frame(outer)
        status.pack(fill="x", pady=(8, 0))
        status.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Готово к запуску")
        ttk.Label(status, textvariable=self.status_var, style="Stage.TLabel").grid(
            row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=1000)
        self.progress.pack(fill="x", pady=(5, 0))

    # ------------------------------------------------------------- консоль
    def _build_console_tab(self, parent):
        frame = ttk.Frame(parent, padding=(0, 12, 0, 0))
        self._add_tab("Консоль", frame)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.console = tk.Text(frame, height=14, wrap="none", background=theme.COLORS["console_bg"],
                               foreground=theme.COLORS["console_fg"],
                               insertbackground=theme.COLORS["console_fg"],
                               selectbackground=theme.COLORS["accent"],
                               selectforeground="#eef2ee", font=("Consolas", 9),
                               borderwidth=0, highlightthickness=0, padx=8, pady=6)
        self.console.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, command=self.console.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.console.configure(yscrollcommand=scroll.set, state="disabled")
        controls = ttk.Frame(frame)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.autoscroll_var = tk.BooleanVar(value=True)
        theme.check(controls, "Автопрокрутка", self.autoscroll_var).pack(side="left")
        ttk.Button(controls, text="Очистить", style="Small.TButton",
                   command=self._clear_console).pack(side="right")

    # ---------------------------------------------------------------- моды
    def _build_mods_tab(self, parent):
        frame = ttk.Frame(parent, padding=(0, 12, 0, 0))
        self._add_tab("Моды", frame)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)

        top = ttk.Frame(frame)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.mods_info = ttk.Label(top, text="Модов: 0", style="H1.TLabel")
        self.mods_info.pack(side="left")
        ttk.Button(top, text="Открыть папку mods", style="Small.TButton",
                   command=self._open_mods_dir).pack(side="right")

        ttk.Label(frame, text="Галочка = мод загрузится в игру. Снятая галочка переносит файл "
                              "в .disabled.", style="Muted.TLabel").grid(row=1, column=0,
                                                                         sticky="w", pady=(4, 6))
        self.mods_tree = ttk.Treeview(frame, columns=("name", "state", "size"),
                                      show="headings", selectmode="browse")
        self.mods_tree.heading("name", text="Мод")
        self.mods_tree.heading("state", text="Состояние")
        self.mods_tree.heading("size", text="Размер")
        self.mods_tree.column("name", width=460, anchor="w")
        self.mods_tree.column("state", width=140, anchor="center")
        self.mods_tree.column("size", width=110, anchor="e")
        self.mods_tree.grid(row=2, column=0, sticky="nsew")
        self.mods_tree.bind("<Double-1>", lambda _e: self._toggle_mod())
        scroll = ttk.Scrollbar(frame, command=self.mods_tree.yview)
        scroll.grid(row=2, column=1, sticky="ns")
        self.mods_tree.configure(yscrollcommand=scroll.set)

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="Обновить", style="Small.TButton",
                   command=self._refresh_mods).pack(side="left")
        ttk.Button(buttons, text="Вкл / выкл", style="Small.TButton",
                   command=self._toggle_mod).pack(side="left", padx=4)
        ttk.Button(buttons, text="Добавить .jar…", style="Small.TButton",
                   command=self._add_mods).pack(side="left")
        ttk.Button(buttons, text="Удалить", style="Small.TButton",
                   command=self._delete_mod).pack(side="left", padx=4)

    # -------------------------------------------------------------- каталог
    def _build_content_tab(self, parent):
        frame = ttk.Frame(parent, padding=(0, 12, 0, 0))
        self._add_tab("Каталог", frame)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)

        row = ttk.Frame(frame)
        row.grid(row=0, column=0, columnspan=2, sticky="ew")
        row.columnconfigure(0, weight=1)
        self.search_var = tk.StringVar()
        entry = theme.entry(row, textvariable=self.search_var)
        entry.grid(row=0, column=0, sticky="ew", ipady=3)
        entry.bind("<Return>", lambda _e: self._on_search(False))
        self.content_type = tk.StringVar(value="mod")
        ttk.Combobox(row, textvariable=self.content_type, state="readonly", width=12,
                     values=["Моды", "Датапаки", "Ресурспаки"]).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(row, text="Найти", command=lambda: self._on_search(False)).grid(
            row=0, column=2, padx=(8, 0))

        row2 = ttk.Frame(frame)
        row2.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 6))
        row2.columnconfigure(4, weight=1)
        self.create_only_var = tk.BooleanVar(value=True)
        theme.check(row2, "Только контент для Create", self.create_only_var,
                    command=lambda: self._on_search(False)).grid(row=0, column=0, sticky="w")
        self.rp_enable_var = tk.BooleanVar(value=True)
        theme.check(row2, "Включать ресурспак сразу", self.rp_enable_var).grid(
            row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Label(row2, text="Мир для датапаков:", style="Muted.TLabel").grid(row=0, column=2,
                                                                             sticky="e",
                                                                             padx=(24, 0))
        self.world_var = tk.StringVar()
        self.world_box = ttk.Combobox(row2, textvariable=self.world_var, state="readonly",
                                      width=22)
        self.world_box.grid(row=0, column=3, sticky="w", padx=(6, 0))

        self.content_info = ttk.Label(frame, text="Введите запрос и нажмите «Найти».",
                                      style="Muted.TLabel")
        self.content_info.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 4))

        self.content_tree = ttk.Treeview(frame, columns=("title", "author", "downloads", "desc"),
                                         show="headings", selectmode="browse")
        for key, title, width, anchor in (("title", "Название", 250, "w"),
                                          ("author", "Автор", 120, "w"),
                                          ("downloads", "Загрузок", 90, "e"),
                                          ("desc", "Описание", 380, "w")):
            self.content_tree.heading(key, text=title)
            self.content_tree.column(key, width=width, anchor=anchor)
        self.content_tree.grid(row=3, column=0, sticky="nsew")
        self.content_tree.bind("<Double-1>", lambda _e: self._on_install_content())
        scroll = ttk.Scrollbar(frame, command=self.content_tree.yview)
        scroll.grid(row=3, column=1, sticky="ns")
        self.content_tree.configure(yscrollcommand=scroll.set)

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="Установить выбранное", style="Small.TButton",
                   command=self._on_install_content).pack(side="left")
        ttk.Button(buttons, text="Ещё 20", style="Small.TButton",
                   command=lambda: self._on_search(True)).pack(side="left", padx=4)
        ttk.Button(buttons, text="Установить Create", style="Small.TButton",
                   command=self._install_create).pack(side="left", padx=(16, 0))
        ttk.Button(buttons, text="Страница в браузере", style="Small.TButton",
                   command=self._open_page).pack(side="right")

    # --------------------------------------------------------------- скины
    def _build_skins_tab(self, parent):
        frame = ttk.Frame(parent, padding=(0, 12, 0, 0))
        self._add_tab("Скины", frame)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)

        left = ttk.Frame(frame)
        left.grid(row=0, column=0, sticky="n")
        self.skin_player_image = None
        self.skin_head_image = None
        previews = ttk.Frame(left)
        previews.pack()
        self.skin_player_label = ttk.Label(previews, background=theme.COLORS["card"])
        self.skin_player_label.pack(side="left")
        self.skin_head_label = ttk.Label(previews)
        self.skin_head_label.pack(side="left", anchor="n", padx=(10, 0))

        right = ttk.Frame(frame)
        right.grid(row=0, column=1, sticky="nsew", padx=(18, 0))
        right.columnconfigure(0, weight=1)

        ttk.Label(right, text="Ник игрока", style="H1.TLabel").grid(row=0, column=0, sticky="w")
        theme.entry(right, textvariable=self.user_var, width=24).grid(
            row=1, column=0, sticky="ew", pady=(4, 10), ipady=3)

        ttk.Label(right, text="Модель рук", style="H1.TLabel").grid(row=2, column=0, sticky="w")
        self.skin_model = tk.StringVar(value="wide")
        models = ttk.Frame(right)
        models.grid(row=3, column=0, sticky="w", pady=(4, 10))
        for label, value in MODELS.items():
            theme.radio(models, label, self.skin_model, value,
                        command=self._refresh_skin).pack(anchor="w")

        buttons = ttk.Frame(right)
        buttons.grid(row=4, column=0, sticky="ew")
        ttk.Button(buttons, text="Скачать по нику (Мойанг)",
                   command=self._skin_fetch_nick).grid(row=0, column=0, sticky="ew")
        ttk.Button(buttons, text="Выбрать файл…", command=self._skin_from_file).grid(
            row=0, column=1, sticky="ew", padx=6)
        ttk.Button(buttons, text="По ссылке…", command=self._skin_from_url).grid(
            row=0, column=2, sticky="ew")
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        buttons.columnconfigure(2, weight=1)

        actions = ttk.Frame(right)
        actions.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(actions, text="Применить скин к игре", style="Accent.TButton",
                   command=self._skin_apply).pack(fill="x")
        extra = ttk.Frame(right)
        extra.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(extra, text="Убрать скин", style="Small.TButton",
                   command=self._skin_remove).pack(side="left")
        ttk.Button(extra, text="Открыть папку скинов", style="Small.TButton",
                   command=self._open_skins_dir).pack(side="left", padx=6)

        self.skin_info = ttk.Label(right, text="", style="Muted.TLabel", wraplength=420,
                                   justify="left")
        self.skin_info.grid(row=7, column=0, sticky="w", pady=(12, 0))
        ttk.Label(right, justify="left", wraplength=420, style="Muted.TLabel",
                  text="Как это работает: лаунчер складывает скин в ресурспак и включает его — "
                       "мод не нужен. Скин виден в одиночной игре и на серверах без лицензии. "
                       "Скин по нику можно скачать только для лицензионного ника, иначе выберите "
                       "PNG-файл (64x64, как в формате Minecraft).").grid(
            row=8, column=0, sticky="w", pady=(8, 0))

    # ------------------------------------------------------------ настройки
    def _build_settings_tab(self, parent):
        frame = ttk.Frame(parent, padding=(0, 12, 0, 0))
        self._add_tab("Настройки", frame)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Java:", style="H1.TLabel").grid(row=0, column=0, sticky="w",
                                                               pady=(0, 4))
        self.java_var = tk.StringVar()
        self.java_box = ttk.Combobox(frame, textvariable=self.java_var, values=[])
        self.java_box.grid(row=1, column=0, columnspan=2, sticky="ew")
        java_buttons = ttk.Frame(frame)
        java_buttons.grid(row=1, column=2, sticky="e", padx=(8, 0))
        ttk.Button(java_buttons, text="Обзор…", style="Small.TButton",
                   command=self._choose_java).pack(side="left")
        ttk.Button(java_buttons, text="Скачать Java 21", style="Small.TButton",
                   command=self._download_java).pack(side="left", padx=4)

        ttk.Label(frame, text="Доп. аргументы JVM:", style="H1.TLabel").grid(
            row=2, column=0, sticky="w", pady=(12, 4))
        self.jvm_var = tk.StringVar()
        theme.entry(frame, textvariable=self.jvm_var).grid(row=3, column=0, columnspan=3,
                                                           sticky="ew", ipady=3)

        self.skip_sounds_var = tk.BooleanVar()
        theme.check(frame, "Не скачивать звуки (~700 МБ меньше, игра будет без звука)",
                    self.skip_sounds_var).grid(row=4, column=0, columnspan=3,
                                               sticky="w", pady=(10, 2))
        self.close_on_start_var = tk.BooleanVar()
        theme.check(frame, "Закрывать лаунчер после запуска игры",
                    self.close_on_start_var).grid(row=5, column=0, columnspan=3,
                                                  sticky="w", pady=2)
        ttk.Button(frame, text="Сохранить настройки", command=self._save_settings).grid(
            row=6, column=0, sticky="w", pady=(12, 0))

        tools = ttk.Labelframe(frame, text=" Сервис ", style="Card.TLabelframe", padding=10)
        tools.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        ttk.Button(tools, text="Создать ярлык на рабочем столе", style="Small.TButton",
                   command=self._create_shortcut).pack(side="left")
        ttk.Button(tools, text="Ярлык в папке лаунчера", style="Small.TButton",
                   command=lambda: self._create_shortcut(False)).pack(side="left", padx=6)
        ttk.Button(tools, text="Открыть папку игры", style="Small.TButton",
                   command=self._open_game_dir).pack(side="left")

        ttk.Label(frame, justify="left", wraplength=760, style="Muted.TLabel",
                  text="Вход выполняется в офлайн-режиме по нику (без аккаунта Microsoft). "
                       "Для игры на серверах с проверкой лицензии нужен лицензионный аккаунт — "
                       "эта версия лаунчера его не поддерживает.\n"
                       "Моды должны быть для NeoForge 1.21.1: старые моды для Forge не подойдут.").grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(16, 0))

    # ============================================================ инфраструктура
    def post(self, callback):
        self.queue.put(callback)

    def log(self, message):
        text = str(message).rstrip()
        self.post(lambda: self._append_console(text))

    def _append_console(self, text: str):
        self.console.configure(state="normal")
        self.console.insert("end", text + "\n")
        if int(self.console.index("end-1c").split(".")[0]) > 3000:
            self.console.delete("1.0", "1000.0")
        self.console.configure(state="disabled")
        if self.autoscroll_var.get():
            self.console.see("end")

    def _clear_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def stage(self, text):
        self.post(lambda: self.status_var.set(text))

    def _progress(self, done, total, byte_done, byte_total, label):
        def update():
            if byte_total:
                fraction = min(1.0, byte_done / float(byte_total))
                text = "%s — %.1f%% (%s из %s, %d/%d файлов)" % (
                    label or "Загрузка", fraction * 100, human_size(byte_done),
                    human_size(byte_total), done, total)
            elif total:
                fraction = min(1.0, done / float(total))
                text = "%s — %.0f%% (%d/%d файлов)" % (label or "Загрузка", fraction * 100,
                                                       done, total)
            else:
                fraction, text = 0.0, label or "Готово"
            self.progress.configure(value=int(fraction * 1000))
            self.status_var.set(text)
        self.post(update)

    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self.play_button.configure(state=state)
        self.install_button.configure(state=state)
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.busy = busy

    def _make_downloader(self) -> Downloader:
        return Downloader(workers=int(self.cfg.get("download_workers", 8)),
                          on_progress=self._progress, on_log=self.log)

    def _pump(self):
        while True:
            try:
                callback = self.queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except tk.TclError:
                pass
        try:
            self.root.after(80, self._pump)
        except tk.TclError:      # окно уже закрыто
            pass

    # ================================================================ окружение
    def _probe(self):
        try:
            found = javas.find_all(self.cfg.get("java_path", ""))
            self.java_list = found
            labels = ["%s — %s" % (info.path, info.version or ("Java %d" % info.major))
                      for info in found]
            self.post(lambda: self.java_box.configure(values=labels))
            usable = next((info for info in found if info.major >= javas.REQUIRED_MAJOR), None)
            if usable:
                self.post(lambda: self.java_var.set(
                    "%s — %s" % (usable.path, usable.version or usable.major)))
                self.log("Java: %s" % usable)
            else:
                self.log("Java %d+ не найдена — лаунчер скачает её сам"
                         % javas.REQUIRED_MAJOR)
        except Exception as exc:  # noqa: BLE001
            self.log("Проверка Java: %s" % exc)

        try:
            versions = neoforge.list_versions(self.cfg.get("mc_version", "1.21.1"))
            self.neo_versions = versions
            ordered = list(reversed(versions))
            self.post(lambda: self.neo_box.configure(values=ordered))
            if versions and not (self.cfg.get("neoforge_version") or "").strip():
                self.post(lambda: self.neo_var.set(versions[-1]))
        except Exception as exc:  # noqa: BLE001
            self.log("Список версий NeoForge: %s" % exc)

        self.post(self._refresh_all)
        self.log("Готово. Ник: %s" % self.cfg.get("username", "Player"))

    def _refresh_all(self):
        self._refresh_mods()
        self._refresh_worlds()
        self._refresh_skin()
        self._refresh_footer()

    def _refresh_footer(self):
        mc_version = self.cfg.get("mc_version", "1.21.1")
        neoforge_mode = self.mode_var.get().startswith("NeoForge")
        neo = (self.neo_var.get() or "").strip() if neoforge_mode else ""
        usable = next((info for info in self.java_list if info.major >= javas.REQUIRED_MAJOR), None)
        state = "установлено" if install.installed(
            self.cfg.game_dir, mc_version, "neoforge" if neoforge_mode else "vanilla", neo,
            bool(self.skip_sounds_var.get())) else "не установлено"
        java_text = ("Java %s" % (usable.version or usable.major)) if usable else \
            ("Java %d не найдена" % javas.REQUIRED_MAJOR)
        target = ("NeoForge " + neo) if neo else "без модов"
        self.footer.configure(text="Minecraft %s  •  %s  •  %s  •  %s" % (
            mc_version, target, state, java_text))

    # ================================================================ настройки
    def _apply_config(self):
        self.user_var.set(self.cfg.get("username", "Player"))
        self.mode_var.set("NeoForge (моды)" if self.cfg.get("mode", "neoforge") == "neoforge"
                          else "Ванильный (без модов)")
        self.neo_var.set(self.cfg.get("neoforge_version", ""))
        self.mc_var.set(self.cfg.get("mc_version", "1.21.1"))
        self.dir_var.set(self.cfg.game_dir)
        self.jvm_var.set(self.cfg.get("jvm_args", ""))
        self.skip_sounds_var.set(bool(self.cfg.get("skip_sounds")))
        self.close_on_start_var.set(bool(self.cfg.get("close_launcher_on_start")))
        self.create_only_var.set(bool(self.cfg.get("content_create_only")))
        self.rp_enable_var.set(bool(self.cfg.get("enable_resource_packs")))
        self.search_var.set(self.cfg.get("content_query", ""))
        self.skin_model.set(self.cfg.get("skin_model", "wide"))
        self.content_type.set({"mod": "Моды", "datapack": "Датапаки",
                               "resourcepack": "Ресурспаки"}.get(
            self.cfg.get("content_type", "mod"), "Моды"))
        total = paths.system_memory_mb()
        upper = max(2048, min(total - 1024, 16384)) if total else 16384
        self.ram_scale.configure(to=upper)
        self.ram_scale.set(min(max(1024, int(self.cfg.get("ram_mb", 4096))), upper))
        self._on_ram_change()

    def _collect_config(self) -> Config:
        self.cfg["username"] = auth.sanitize_username(self.user_var.get())
        self.cfg["mode"] = "neoforge" if self.mode_var.get().startswith("NeoForge") else "vanilla"
        self.cfg["neoforge_version"] = (self.neo_var.get() or "").strip()
        self.cfg["mc_version"] = (self.mc_var.get() or "1.21.1").strip()
        self.cfg["game_dir"] = self.dir_var.get()
        self.cfg["jvm_args"] = self.jvm_var.get()
        self.cfg["ram_mb"] = int(round(self.ram_scale.get() / 512.0) * 512)
        self.cfg["skip_sounds"] = bool(self.skip_sounds_var.get())
        self.cfg["close_launcher_on_start"] = bool(self.close_on_start_var.get())
        self.cfg["skin_model"] = self.skin_model.get()
        self.cfg["content_type"] = {"Моды": "mod", "Датапаки": "datapack",
                                    "Ресурспаки": "resourcepack"}.get(
            self.content_type.get(), "mod")
        self.cfg["content_create_only"] = bool(self.create_only_var.get())
        self.cfg["enable_resource_packs"] = bool(self.rp_enable_var.get())
        self.cfg["content_query"] = self.search_var.get()
        java_value = (self.java_var.get() or "").split(" — ")[0].strip()
        if java_value.lower().endswith((".exe", "java")):
            self.cfg["java_path"] = java_value
        return self.cfg

    def _save_settings(self):
        self._collect_config().save()
        self.log("Настройки сохранены")
        self._refresh_footer()

    def _on_ram_change(self, _value=None):
        value = int(round(float(self.ram_scale.get()) / 512.0) * 512)
        self.ram_var.set(value)
        total = paths.system_memory_mb()
        suffix = "  (в системе %d МБ)" % total if total else ""
        self.ram_label.configure(text="%d МБ%s" % (value, suffix))

    def _on_mode_change(self):
        neoforge_mode = self.mode_var.get().startswith("NeoForge")
        self.neo_box.configure(state="normal" if neoforge_mode else "disabled")
        self._refresh_footer()

    def _choose_dir(self):
        initial = self.dir_var.get() if os.path.isdir(self.dir_var.get()) else os.path.expanduser("~")
        chosen = filedialog.askdirectory(title="Выберите папку игры", initialdir=initial)
        if chosen:
            self.dir_var.set(os.path.normpath(chosen))
            self.cfg["game_dir"] = self.dir_var.get()
            self._refresh_all()

    def _choose_java(self):
        path = filedialog.askopenfilename(
            title="Укажите java.exe",
            filetypes=[("Java", "java.exe" if paths.WINDOWS else "java"), ("Все файлы", "*.*")])
        if path:
            self.java_var.set(path)
            self.cfg["java_path"] = path
            self.log("Выбрана Java: %s" % path)

    def _download_java(self):
        if self.busy:
            return
        self._set_busy(True)
        self.stage("Загрузка Java %d" % javas.REQUIRED_MAJOR)

        def worker():
            try:
                downloader = self._make_downloader()
                path = javas.install_jre(downloader, javas.REQUIRED_MAJOR, self.log)
                info = javas.probe(path)
                self.post(lambda: self.java_var.set("%s — %s" % (path, info.version if info else "21")))
                self.post(lambda: self.status_var.set("Java готова"))
            except Exception as exc:  # noqa: BLE001
                self._fail(exc)
            finally:
                self.post(lambda: self._set_busy(False))
                self.post(self._refresh_footer)

        threading.Thread(target=worker, daemon=True).start()

    def _create_shortcut(self, desktop=True):
        created = shortcut.create(desktop=desktop, in_folder=not desktop)
        if created:
            self.log("Ярлык создан: %s" % "; ".join(created))
            messagebox.showinfo("Ярлык", "Готово:\n" + "\n".join(created), parent=self.root)
        else:
            messagebox.showwarning("Ярлык", "Не удалось создать ярлык", parent=self.root)

    def _open_game_dir(self):
        self._open_path(self.cfg.game_dir)

    def _open_path(self, directory):
        try:
            os.makedirs(directory, exist_ok=True)
            if paths.WINDOWS:
                os.startfile(directory)  # noqa: S606
            elif paths.MACOS:
                subprocess.Popen(["open", directory])
            else:
                subprocess.Popen(["xdg-open", directory])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Ошибка", str(exc), parent=self.root)

    # ==================================================================== моды
    def _refresh_mods(self):
        self._load_mods()
        self._refresh_footer()

    def _load_mods(self):
        try:
            self.launcher_mods = mods.list_mods(self.cfg.game_dir)
        except Exception as exc:  # noqa: BLE001
            self.log("Ошибка чтения папки модов: %s" % exc)
            self.launcher_mods = []
        self.mods_tree.delete(*self.mods_tree.get_children())
        for index, mod in enumerate(self.launcher_mods):
            self.mods_tree.insert("", "end", iid=str(index),
                                  values=(mod.display_name, "включён" if mod.enabled else "выключен",
                                          human_size(mod.size)))
        enabled = sum(1 for mod in self.launcher_mods if mod.enabled)
        self.mods_info.configure(text="Модов: %d (включено: %d)" % (len(self.launcher_mods), enabled))

    def _selected_mod(self):
        selection = self.mods_tree.selection()
        if not selection:
            return None
        try:
            return self.launcher_mods[int(selection[0])]
        except (ValueError, IndexError):
            return None

    def _toggle_mod(self):
        mod = self._selected_mod()
        if not mod:
            return
        try:
            mods.set_enabled(mod.path, not mod.enabled)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Ошибка", str(exc), parent=self.root)
        self._load_mods()

    def _add_mods(self):
        files = filedialog.askopenfilenames(
            title="Выберите моды (.jar)",
            filetypes=[("Моды Minecraft", "*.jar *.zip"), ("Все файлы", "*.*")])
        if not files:
            return
        try:
            added = mods.add(self.cfg.game_dir, files)
            self.log("Добавлено модов: %d" % len(added))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Ошибка", str(exc), parent=self.root)
        self._load_mods()

    def _delete_mod(self):
        mod = self._selected_mod()
        if not mod:
            return
        if not messagebox.askyesno("Удаление", "Удалить «%s»?" % mod.display_name, parent=self.root):
            return
        try:
            mods.delete(mod.path)
        except OSError as exc:
            messagebox.showerror("Ошибка", str(exc), parent=self.root)
        self._load_mods()

    def _open_mods_dir(self):
        self._open_path(mods.mods_dir(self.cfg.game_dir))

    # ================================================================= каталог
    def _refresh_worlds(self):
        worlds = []
        saves = os.path.join(self.cfg.game_dir, "saves")
        if os.path.isdir(saves):
            worlds = sorted(name for name in os.listdir(saves)
                            if os.path.isdir(os.path.join(saves, name)))
        values = worlds + [WORLD_GLOBAL]
        self.world_box.configure(values=values)
        current = self.world_var.get()
        if current not in values:
            self.world_var.set(worlds[0] if worlds else WORLD_GLOBAL)

    def _on_search(self, more: bool):
        if self.busy:
            return
        query = self.search_var.get()
        kind = {"Моды": "mod", "Датапаки": "datapack",
                "Ресурспаки": "resourcepack"}.get(self.content_type.get(), "mod")
        create_only = bool(self.create_only_var.get())
        offset = self.search_offset + 20 if more else 0
        if not more:
            self.content_tree.delete(*self.content_tree.get_children())
            self.results = []
        self.content_info.configure(text="Ищу…")

        def worker():
            try:
                result = modrinth.search(query, kind, self.cfg.get("mc_version", "1.21.1"),
                                         "neoforge", 20, offset, create_only)
                self.post(lambda: self._fill_results(result, more))
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                self.post(lambda: self.content_info.configure(text="Ошибка поиска: %s" % message))
                self.log("Каталог: %s" % message)

        threading.Thread(target=worker, daemon=True).start()

    def _fill_results(self, result, more):
        hits = result["hits"]
        if more:
            self.search_offset += 20
        else:
            self.search_offset = 0
        for hit in hits:
            index = len(self.results)
            self.results.append(hit)
            self.content_tree.insert("", "end", iid=str(index), values=(
                hit["title"], hit["author"] or "", "{:,}".format(hit["downloads"]).replace(",", " "),
                hit["description"][:120]))
        if not self.results:
            self.content_info.configure(
                text="Ничего не найдено. Попробуйте другой запрос или снимите галочку Create.")
        else:
            self.content_info.configure(
                text="Показано %d из %d. Двойной клик — установить."
                     % (len(self.results), max(len(self.results), result["total"])))

    def _selected_project(self):
        selection = self.content_tree.selection()
        if not selection:
            return None
        try:
            return self.results[int(selection[0])]
        except (ValueError, IndexError):
            return None

    def _content_destination(self, kind: str):
        game_dir = self.cfg.game_dir
        if kind == "mod":
            return mods.mods_dir(game_dir)
        if kind == "resourcepack":
            return os.path.join(game_dir, "resourcepacks")
        world = self.world_var.get()
        if not world or world == WORLD_GLOBAL:
            directory = os.path.join(game_dir, "datapacks")
        else:
            directory = os.path.join(game_dir, "saves", world, "datapacks")
        os.makedirs(directory, exist_ok=True)
        return directory

    def _on_install_content(self):
        hit = self._selected_project()
        if not hit:
            messagebox.showinfo("Каталог", "Выберите проект в списке", parent=self.root)
            return
        kind = {"Моды": "mod", "Датапаки": "datapack",
                "Ресурспаки": "resourcepack"}.get(self.content_type.get(), "mod")
        self._install_project(hit, kind)

    def _install_create(self):
        self._install_project({"id": "create", "slug": "create", "title": "Create"}, "mod")

    def _install_project(self, hit, kind: str):
        if self.busy or (self.process and self.process.poll() is None):
            return
        self._collect_config().save()
        destination = self._content_destination(kind)
        enable_pack = bool(self.rp_enable_var.get())
        self._set_busy(True)
        self.progress.configure(value=0)
        self.stage("Установка «%s»" % hit.get("title"))

        def worker():
            try:
                downloader = self._make_downloader()
                self.downloader = downloader
                self.log("Установка: %s (%s) → %s"
                         % (hit.get("title"), modrinth.CONTENT_LABELS.get(kind, kind), destination))
                queued = modrinth.install(
                    downloader, hit["id"], destination,
                    self.cfg.get("mc_version", "1.21.1"), "neoforge",
                    slug=hit.get("slug") or "", kind=kind, game_dir=self.cfg.game_dir,
                    allow_dependencies=(kind == "mod"), log=self.log)
                if not queued:
                    self.log("Устанавливать нечего")
                    return
                downloader.run()
                if kind == "resourcepack" and enable_pack:
                    for item in queued:
                        options.enable_resource_pack(self.cfg.game_dir, item["file_name"], True,
                                                     self.log)
                title = hit.get("title")
                self.post(lambda: self.status_var.set("Готово: %s" % title))
                self.log("Установлено файлов: %d" % len(queued))
            except DownloadCancelled:
                self.log("Загрузка отменена")
            except Exception as exc:  # noqa: BLE001
                self._fail(exc)
                self.log(traceback.format_exc())
            finally:
                self.downloader = None
                self.post(lambda: self._set_busy(False))
                self.post(self._refresh_all)

        threading.Thread(target=worker, daemon=True).start()

    def _open_page(self):
        hit = self._selected_project()
        if not hit:
            return
        try:
            import webbrowser
            webbrowser.open(hit["page"])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Ошибка", str(exc), parent=self.root)

    # ================================================================== скины
    def _skin_bytes(self):
        if self.skin_data:
            return self.skin_data
        return skins.current(self.cfg.game_dir, auth.sanitize_username(self.user_var.get()))

    def _refresh_skin(self):
        data = self._skin_bytes()
        try:
            parsed = skins.parse(data)
        except skins.SkinError as exc:
            self.skin_info.configure(text="Скин не загружен: %s" % exc)
            return
        slim = self.skin_model.get() == "slim"
        factor = 5
        width, height, figure = skins.render_player(parsed, slim, factor)
        head_width, head_height, head = skins.render_head(parsed, 5)
        try:
            self.skin_player_image = tk.PhotoImage(data=png.to_photo(width, height, figure))
            self.skin_head_image = tk.PhotoImage(data=png.to_photo(head_width, head_height, head))
        except tk.TclError as exc:
            self.log("Не удалось показать превью: %s" % exc)
            return
        self.skin_player_label.configure(image=self.skin_player_image)
        self.skin_head_label.configure(image=self.skin_head_image)
        info = skins.status(self.cfg.game_dir, auth.sanitize_username(self.user_var.get()))
        state = ("ресурспак включён" if info["enabled"] else
                 ("ресурспак есть, но выключен" if info["pack_exists"] else "скин не применён"))
        legacy = " Формат 64x32 (старый) — конечности зеркалятся, как в игре." \
            if parsed[1] < 64 else ""
        self.skin_info.configure(text="Превью %dx%d, модель %s. Статус: %s.%s"
                                      % (parsed[0], parsed[1],
                                         "тонкие руки" if slim else "широкие руки", state, legacy))

    def _set_skin(self, data: bytes, message: str):
        try:
            skins.parse(data)
        except skins.SkinError as exc:
            messagebox.showerror("Скин", str(exc), parent=self.root)
            return
        self.skin_data = data
        self.log(message)
        self._refresh_skin()

    def _skin_fetch_nick(self):
        nickname = auth.sanitize_username(self.user_var.get())
        self.stage("Скачиваю скин игрока %s" % nickname)

        def worker():
            try:
                data = skins.download_by_nickname(nickname)
                self.post(lambda: self._set_skin(data, "Скин игрока %s получен с Мойанга" % nickname))
                self.post(lambda: self.status_var.set("Скин получен"))
            except skins.SkinError as exc:
                message = str(exc)
                self.post(lambda: messagebox.showerror("Скин", message, parent=self.root))
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                self.post(lambda: messagebox.showerror("Скин", message, parent=self.root))

        threading.Thread(target=worker, daemon=True).start()

    def _skin_from_file(self):
        path = filedialog.askopenfilename(title="Выберите PNG-скин",
                                          filetypes=[("PNG", "*.png"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            self._set_skin(skins.read_file(path), "Скин загружен из %s" % os.path.basename(path))
        except skins.SkinError as exc:
            messagebox.showerror("Скин", str(exc), parent=self.root)

    def _skin_from_url(self):
        url = simpledialog.askstring("Скин по ссылке", "Ссылка на PNG-файл скина:",
                                     parent=self.root)
        if not url:
            return
        self.stage("Скачиваю скин по ссылке")

        def worker():
            try:
                data = skins.download_by_url(url)
                self.post(lambda: self._set_skin(data, "Скин скачан по ссылке"))
                self.post(lambda: self.status_var.set("Скин получен"))
            except skins.SkinError as exc:
                message = str(exc)
                self.post(lambda: messagebox.showerror("Скин", message, parent=self.root))

        threading.Thread(target=worker, daemon=True).start()

    def _skin_apply(self):
        data = self._skin_bytes()
        nickname = auth.sanitize_username(self.user_var.get())
        slim = self.skin_model.get() == "slim"
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno("Скин", "Игра запущена — скин применится при следующем "
                                               "запуске. Продолжить?", parent=self.root):
                return
        try:
            skins.apply(self.cfg.game_dir, nickname, data, slim, self.log)
            self._collect_config().save()
            self._refresh_skin()
            self.status_var.set("Скин применён")
            messagebox.showinfo("Скин", "Готово. Перезапустите игру, чтобы увидеть скин.",
                                parent=self.root)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Скин", str(exc), parent=self.root)

    def _skin_remove(self):
        nickname = auth.sanitize_username(self.user_var.get())
        skins.remove(self.cfg.game_dir, nickname, self.log)
        self.skin_data = b""
        self._refresh_skin()
        self.status_var.set("Скин убран")

    def _open_skins_dir(self):
        self._open_path(skins.skins_dir(self.cfg.game_dir))

    # ================================================================= запуск
    def _on_install(self):
        self._start_worker(launch_after=False)

    def _on_play(self):
        self._start_worker(launch_after=True)

    def _on_cancel(self):
        self.log("Отмена…")
        if self.downloader:
            self.downloader.cancel()
        if self.process and self.process.poll() is None:
            try:
                self.process.kill()
            except OSError:
                pass

    def _start_worker(self, launch_after: bool):
        if self.busy or (self.process and self.process.poll() is None):
            return
        self._collect_config().save()
        self._set_busy(True)
        self.progress.configure(value=0)
        threading.Thread(target=self._worker, args=(launch_after,), daemon=True).start()

    def _worker(self, launch_after: bool):
        try:
            cfg = self.cfg
            mc_dir = cfg.game_dir
            mc_version = cfg.get("mc_version", "1.21.1")
            mode = cfg.get("mode", "neoforge")

            self.stage("Проверка Java")
            downloader = self._make_downloader()
            self.downloader = downloader
            java = install.ensure_java(cfg, downloader, self.log)

            neo_version = ""
            if mode == "neoforge":
                self.stage("Определение версии NeoForge")
                neo_version = install.resolve_neo_version(mc_version, cfg.get("neoforge_version", ""),
                                                          self.log)
                self.post(lambda: self.neo_var.set(neo_version))

            if not install.installed(mc_dir, mc_version, mode, neo_version,
                                     bool(cfg.get("skip_sounds"))):
                install.install_all(mc_dir, mc_version, mode, neo_version, java, downloader,
                                    self.stage, self.log, bool(cfg.get("skip_sounds")))
            else:
                self.log("Все файлы уже на месте")

            self.post(self._refresh_footer)
            if not launch_after:
                self.post(lambda: self.status_var.set("Установка завершена"))
                return

            target = neoforge.profile_id(neo_version) if mode == "neoforge" else mc_version
            self.stage("Запуск Minecraft")
            process, _resolved = launch.launch(
                mc_dir, target, java, int(cfg.get("ram_mb", 4096)),
                auth.sanitize_username(cfg.get("username", "Player")),
                cfg.get("jvm_args", ""), int(cfg.get("width") or 0), int(cfg.get("height") or 0),
                log=self.log)
            self.process = process
            self.post(lambda: self.progress.configure(value=1000))
            self.post(lambda: self.status_var.set("Игра запущена"))
            self.post(lambda: self._set_busy(False))
            if cfg.get("close_launcher_on_start") and paths.WINDOWS:
                self.post(self.root.destroy)
            for line in process.stdout or []:
                self.log(line.rstrip())
            code = process.wait()
            self.log("Игра завершилась (код %s)" % code)
            self.post(lambda: self.status_var.set("Игра закрыта"))
        except DownloadCancelled:
            self.log("Загрузка отменена")
            self.post(lambda: self.status_var.set("Отменено"))
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)
            self.log(traceback.format_exc())
        finally:
            self.process = None
            self.downloader = None
            self.post(lambda: self._set_busy(False))
            self.post(lambda: self.cancel_button.configure(state="disabled"))
            self.post(self._refresh_all)

    def _fail(self, exc: Exception):
        message = str(exc) or exc.__class__.__name__
        self.log("ОШИБКА: %s" % message)
        self.post(lambda: self.status_var.set("Ошибка: %s" % message.splitlines()[0][:150]))
        self.post(lambda: messagebox.showerror("Ошибка", message, parent=self.root))

    def _on_close(self):
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno("Выход", "Игра запущена. Закрыть лаунчер?", parent=self.root):
                return
        if self.busy and self.downloader:
            self.downloader.cancel()
        try:
            self._collect_config().save()
        except (tk.TclError, ValueError):
            pass
        self.root.destroy()


def _dark_titlebar(root):
    """Просит систему сделать заголовок окна тёмным (работает в Windows 11).

    В Windows 10 атрибут принимается, но ни на что не влияет: система включает
    тёмный заголовок только для программ, у которых это объявлено в манифесте,
    а у python.exe такого объявления нет. Поэтому там заголовок остаётся системным.
    """
    if not paths.WINDOWS:
        return
    try:
        import ctypes

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        value = ctypes.c_int(1)
        for attribute in (20, 19):     # DWMWA_USE_IMMERSIVE_DARK_MODE и его старый номер
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute,
                                                          ctypes.byref(value), 4) == 0:
                break
    except Exception:
        pass


def run():
    if paths.WINDOWS:
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    root.configure(background=theme.COLORS["bg"])
    icon, logo = branding.ensure()
    if paths.WINDOWS and icon and os.path.exists(icon):
        try:
            root.iconbitmap(icon)
        except tk.TclError:
            pass
    if logo and os.path.exists(logo):
        try:
            image = tk.PhotoImage(file=logo)
            root.iconphoto(True, image)
            root._icon_image = image  # чтобы Tk не собрал мусор
        except tk.TclError:
            pass
    LauncherApp(root)
    _dark_titlebar(root)
    root.mainloop()
    return 0
