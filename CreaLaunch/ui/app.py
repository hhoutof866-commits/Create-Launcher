"""Окно лаунчера на tkinter: сборки, моды, каталог, друзья, скины, настройки."""

from __future__ import annotations

import base64
import os
import queue
import subprocess
import threading
import time
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, simpledialog, ttk

from core import (auth, branding, config, friends as friends_mod, hero as hero_banner, install,
                  javas, lan, launch, modrinth, mods, neoforge, options, paths, png, servers_dat,
                  shortcut, skins, upnp)
from core.config import Config
from core.down import DownloadCancelled, Downloader

from . import theme

APP_TITLE = "NeoForge Launcher — Minecraft 1.21.1"
APP_VERSION = "2.4"
WORLD_GLOBAL = "‹общая папка (все миры)›"
MODELS = {"Широкие руки (Steve)": "wide", "Тонкие руки (Alex)": "slim"}
CHANGES = (
    ("Сборки", "Список сборок слева: у каждой свой режим (NeoForge или ваниль), версия, "
               "ОЗУ и папка игры. Переключение — одним кликом, «ИГРАТЬ» запускает выбранную."),
    ("Интерфейс", "Окно собрано в духе официального лаунчера: аккаунт сверху, вкладки под "
                  "названием сборки, большой баннер с кнопкой «ИГРАТЬ». Акцент — фиолетовый."),
    ("Друзья", "Поиск миров, открытых «для сети», автозаход в мир друга одной кнопкой, "
               "приглашения кодом и проброс порта через UPnP."),
    ("Мелочи", "Java 21 подхватывается из официального лаунчера, список серверов игры "
               "пишется в формате 1.21.1, карточка скина и аватар аккаунта сверху."),
)


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
        self.friends = friends_mod.Friends.load()
        self.friend_rows = {}
        self.found = {"worlds": [], "friends": []}
        self.scanning = False
        self.last_scan = 0.0
        self.world_port = 0
        self.beacon = None
        self.beacon_info = {}
        self.upnp_info = None
        self.server_icon = None
        self.join_label = ""
        self.hero_image = None
        self.avatar_image = None
        self.build_rows = {}
        self._user_job = None

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
        outer = ttk.Frame(self.root, padding=(14, 10, 14, 10))
        outer.pack(fill="both", expand=True)

        self._build_account(outer)

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True, pady=(10, 0))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        self._build_sidebar(body)

        main = ttk.Frame(body)
        main.grid(row=0, column=1, sticky="nsew", padx=(14, 0))
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        self.main_title = ttk.Label(main, text="MINECRAFT", style="Kicker.TLabel")
        self.main_title.grid(row=0, column=0, sticky="w")
        self._build_tabs(main)

    def _build_account(self, outer):
        """Строка аккаунта сверху: аватар, ник, подпись. Клик — смена ника."""
        row = tk.Frame(outer, background=theme.COLORS["bg"])
        row.pack(fill="x")

        card = tk.Frame(row, background=theme.COLORS["card"], cursor="hand2")
        card.pack(side="left")
        self.avatar_label = tk.Label(card, background=theme.COLORS["card"], borderwidth=0)
        self.avatar_label.pack(side="left", padx=(9, 9), pady=7)
        texts = tk.Frame(card, background=theme.COLORS["card"])
        texts.pack(side="left", pady=7)
        self.user_var = tk.StringVar()
        self.account_name = tk.Label(texts, text="Player", anchor="w",
                                     background=theme.COLORS["card"],
                                     foreground=theme.COLORS["text_strong"],
                                     font=(theme.FONT, 11, "bold"))
        self.account_name.pack(anchor="w")
        self.account_sub = tk.Label(texts, text="офлайн-профиль", anchor="w",
                                    background=theme.COLORS["card"],
                                    foreground=theme.COLORS["muted"], font=(theme.FONT, 9))
        self.account_sub.pack(anchor="w")
        tk.Label(card, text="▾", background=theme.COLORS["card"], foreground=theme.COLORS["muted"],
                 font=(theme.FONT, 10), padx=12).pack(side="left", pady=7)
        self._bind_click(card, self._edit_nick)
        self.user_var.trace_add("write", self._on_user_change)

    def _bind_click(self, widget, command):
        """Кликом по любому месту блока (включая подписи) вызываем команду."""
        widget.bind("<Button-1>", lambda _event: command())
        for child in widget.winfo_children():
            self._bind_click(child, command)

    def _on_user_change(self, *_args):
        """Ник правят в разных полях — обновляем подписи с небольшой задержкой."""
        if self._user_job is not None:
            try:
                self.root.after_cancel(self._user_job)
            except (tk.TclError, ValueError):
                pass
        self._user_job = self.root.after(400, self._refresh_account)

    def _edit_nick(self):
        name = simpledialog.askstring("Ник", "Ник в игре (офлайн-профиль):",
                                      initialvalue=self.user_var.get(), parent=self.root)
        if not name or not name.strip():
            return
        clean = auth.sanitize_username(name)
        self.user_var.set(clean)
        self._collect_config().save()
        self._refresh_account()
        self._refresh_skin()
        self._refresh_footer()
        self.log("Ник: %s" % clean)
        self.status_var.set("Ник сохранён: %s" % clean)

    def _refresh_account(self):
        """Аватар (голова скина) и подписи аккаунта."""
        name = auth.sanitize_username(self.user_var.get())
        build = self.cfg.get("current_build") or "—"
        self.account_name.configure(text=name)
        self.account_sub.configure(text="офлайн-профиль · сборка «%s»" % build)
        if hasattr(self, "strip_nick"):
            self.strip_nick.configure(text=name)
        try:
            width, height, face = skins.render_head(skins.parse(self._skin_bytes()), 3)
            self.avatar_image = tk.PhotoImage(data=png.to_photo(width, height, face))
            self.avatar_label.configure(image=self.avatar_image)
        except (skins.SkinError, tk.TclError) as exc:
            self.log("Аватар не построен: %s" % exc)

    # ---------------------------------------------------------- список сборок
    def _build_sidebar(self, parent):
        """Левая колонка: сборки, а внизу — служебные ссылки и версия."""
        side = tk.Frame(parent, background=theme.COLORS["card"], width=214)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.pack_propagate(False)      # дети размещаются pack — гасим и его

        head = tk.Frame(side, background=theme.COLORS["card"])
        head.pack(fill="x", padx=12, pady=(11, 7))
        tk.Label(head, text="СБОРКИ", background=theme.COLORS["card"],
                 foreground=theme.COLORS["muted"], font=(theme.FONT, 9, "bold")).pack(side="left")
        add = tk.Label(head, text="+", background=theme.COLORS["card"],
                       foreground=theme.COLORS["muted"], font=(theme.FONT, 13, "bold"),
                       cursor="hand2", padx=2)
        add.pack(side="right")
        add.bind("<Button-1>", lambda _event: self._add_build())
        add.bind("<Enter>", lambda _event: add.configure(foreground=theme.COLORS["accent_text"]))
        add.bind("<Leave>", lambda _event: add.configure(foreground=theme.COLORS["muted"]))

        bottom = tk.Frame(side, background=theme.COLORS["card"])
        bottom.pack(side="bottom", fill="x", padx=12, pady=(8, 10))
        self._sidebar_link(bottom, "Что нового", self._whats_new)
        self._sidebar_link(bottom, "Настройки", lambda: self.show_tab("Настройки"))
        tk.Label(bottom, text="NeoForge Launcher %s" % APP_VERSION,
                 background=theme.COLORS["card"], foreground=theme.COLORS["muted"],
                 font=(theme.FONT, 8)).pack(anchor="w", pady=(9, 0))

        wrap = tk.Frame(side, background=theme.COLORS["card"])
        wrap.pack(fill="both", expand=True)
        self.build_canvas = tk.Canvas(wrap, background=theme.COLORS["card"],
                                      highlightthickness=0, borderwidth=0)
        self.build_canvas.pack(side="left", fill="both", expand=True)
        self.build_bar = ttk.Scrollbar(wrap, orient="vertical", command=self.build_canvas.yview)
        self.build_canvas.configure(yscrollcommand=self.build_bar.set)
        self.builds_frame = tk.Frame(self.build_canvas, background=theme.COLORS["card"])
        self.builds_window = self.build_canvas.create_window((0, 0), window=self.builds_frame,
                                                             anchor="nw")
        self.builds_frame.bind("<Configure>", lambda _event: self.build_canvas.configure(
            scrollregion=self.build_canvas.bbox("all")))
        self.build_canvas.bind("<Configure>", lambda event: self.build_canvas.itemconfigure(
            self.builds_window, width=event.width))
        self.build_canvas.bind("<MouseWheel>", self._scroll_builds)

    def _sidebar_link(self, parent, text, command):
        label = tk.Label(parent, text=text, background=theme.COLORS["card"],
                         foreground=theme.COLORS["muted"], font=(theme.FONT, 10),
                         anchor="w", cursor="hand2")
        label.pack(fill="x", pady=1)
        label.bind("<Button-1>", lambda _event: command())
        label.bind("<Enter>", lambda _event: label.configure(foreground=theme.COLORS["text"]))
        label.bind("<Leave>", lambda _event: label.configure(foreground=theme.COLORS["muted"]))
        return label

    def _scroll_builds(self, event):
        self.build_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _refresh_builds(self):
        """Перерисовывает список сборок слева и подписи над вкладками."""
        for child in self.builds_frame.winfo_children():
            child.destroy()
        self.build_rows = {}
        items = self.cfg.build_list()
        active = self.cfg.get("current_build") or ""
        for build in items:
            name = build.get("name") or ""
            selected = name == active
            row = tk.Frame(self.builds_frame, background=theme.COLORS["card"], cursor="hand2")
            row.pack(fill="x")
            line = tk.Frame(row, width=3, background=theme.COLORS["accent"] if selected
                            else theme.COLORS["card"])
            line.pack(side="left", fill="y")
            texts = tk.Frame(row, background=theme.COLORS["card"])
            texts.pack(side="left", fill="x", expand=True, padx=(9, 8), pady=6)
            title = tk.Label(texts, text=name, anchor="w", background=theme.COLORS["card"],
                             foreground=theme.COLORS["text_strong"] if selected
                             else theme.COLORS["text"],
                             font=(theme.FONT, 10, "bold" if selected else "normal"))
            title.pack(fill="x")
            sub = tk.Label(texts, text=config.Config.build_label(build), anchor="w",
                           background=theme.COLORS["card"], foreground=theme.COLORS["muted"],
                           font=(theme.FONT, 8))
            sub.pack(fill="x")
            widgets = (row, line, texts, title, sub)
            for widget in widgets:
                widget.bind("<Button-1>", lambda _event, value=name: self._select_build(value))
                widget.bind("<Button-3>", lambda event, value=name: self._build_menu(event, value))
                widget.bind("<Enter>", lambda _event, value=name: self._paint_build(value, True))
                widget.bind("<Leave>", lambda _event, value=name: self._leave_build(value))
                widget.bind("<MouseWheel>", self._scroll_builds)
            self.build_rows[name] = {"row": row, "line": line, "texts": texts,
                                     "title": title, "sub": sub}
        if len(items) > 6:
            self.build_bar.pack(side="right", fill="y")
        else:
            self.build_bar.pack_forget()
        self.build_canvas.yview_moveto(0.0)
        if hasattr(self, "build_box"):
            self.build_box.configure(values=[item.get("name") for item in items])
            self.build_var.set(active)
        self._refresh_account()
        self._refresh_footer()

    def _paint_build(self, name, hover: bool):
        """Красит строку сборки: выбранная — с акцентной полосой, курсор — светлее."""
        info = self.build_rows.get(name)
        if not info:
            return
        active = name == (self.cfg.get("current_build") or "")
        background = theme.COLORS["card"]
        if active:
            background = theme.COLORS["accent_soft"]
        elif hover:
            background = theme.COLORS["hover"]
        for key in ("row", "texts", "title", "sub"):
            info[key].configure(background=background)
        info["line"].configure(background=theme.COLORS["accent"] if active else background)
        info["title"].configure(foreground=theme.COLORS["text_strong"] if active
                                else theme.COLORS["text"])

    def _leave_build(self, name):
        """Курсор мог перейти на соседнюю подпись — гасим подсветку с задержкой."""
        self.root.after(40, lambda: self._check_hover(name))

    def _check_hover(self, name):
        info = self.build_rows.get(name)
        if not info:
            return
        row = info["row"]
        try:
            x, y = row.winfo_pointerxy()
            inside = (row.winfo_rootx() <= x < row.winfo_rootx() + row.winfo_width()
                      and row.winfo_rooty() <= y < row.winfo_rooty() + row.winfo_height())
        except tk.TclError:
            return
        if not inside:
            self._paint_build(name, False)

    def _select_build(self, name):
        """Переключает сборку: её значения становятся текущими настройками."""
        if not name or name == (self.cfg.get("current_build") or ""):
            return
        if self.busy or (self.process and self.process.poll() is None):
            messagebox.showinfo("Сборки", "Сначала дождитесь окончания игры или установки.",
                                parent=self.root)
            return
        self._collect_config()
        build = self.cfg.select_build(name)
        self.cfg.save()
        self._apply_config()
        self._refresh_builds()
        self._refresh_all()
        self.log("Сборка «%s»: %s" % (name, config.Config.build_label(build)))
        self.status_var.set("Выбрана сборка «%s»" % name)

    def _on_build_pick(self, _event=None):
        self._select_build((self.build_var.get() or "").strip())

    def _add_build(self):
        if self.busy or (self.process and self.process.poll() is None):
            messagebox.showinfo("Сборки", "Сначала дождитесь окончания игры или установки.",
                                parent=self.root)
            return
        name = simpledialog.askstring("Новая сборка", "Название сборки:", parent=self.root)
        if not name or not name.strip():
            return
        name = name.strip()[:32]
        if self.cfg.find_build(name) is not None:
            messagebox.showinfo("Сборки", "Сборка «%s» уже есть." % name, parent=self.root)
            return
        self._collect_config()
        self.cfg.upsert_build({"name": name})          # копия текущих настроек
        self.cfg.select_build(name)
        self.cfg.save()
        self._apply_config()
        self._refresh_builds()
        self._refresh_all()
        self.log("Добавлена сборка «%s»" % name)
        self.status_var.set("Сборка «%s» добавлена — настройте её и играйте" % name)

    def _edit_active_build(self):
        name = self.cfg.active_build().get("name") or ""
        if name:
            self._edit_build(name)

    def _build_menu(self, event, name):
        menu = tk.Menu(self.root, tearoff=0, background=theme.COLORS["card_alt"],
                       foreground=theme.COLORS["text"], activebackground=theme.COLORS["accent"],
                       activeforeground="#f6f3ff", borderwidth=0, font=(theme.FONT, 10))
        menu.add_command(label="Изменить…", command=lambda: self._edit_build(name))
        menu.add_command(label="Дублировать", command=lambda: self._duplicate_build(name))
        menu.add_separator()
        menu.add_command(label="Удалить", command=lambda: self._remove_build(name),
                         state="normal" if len(self.cfg.build_list()) > 1 else "disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _duplicate_build(self, name):
        build = self.cfg.find_build(name)
        if build is None:
            return
        index = 2
        new_name = "%s (%d)" % (name, index)
        while self.cfg.find_build(new_name) is not None:
            index += 1
            new_name = "%s (%d)" % (name, index)
        data = dict(build)
        data["name"] = new_name
        self.cfg.upsert_build(data)
        self.cfg.save()
        self._refresh_builds()
        self.log("Копия сборки: %s" % new_name)
        self.status_var.set("Сборка «%s» создана" % new_name)

    def _remove_build(self, name, parent=None) -> bool:
        if len(self.cfg.build_list()) <= 1:
            messagebox.showinfo("Сборки", "Последнюю сборку удалить нельзя.", parent=parent or self.root)
            return False
        if not messagebox.askyesno("Сборки", "Удалить сборку «%s»?" % name,
                                   parent=parent or self.root):
            return False
        active = self.cfg.get("current_build") == name
        if not self.cfg.remove_build(name):
            return False
        self.cfg.save()
        if active:
            self._apply_config()
        self._refresh_builds()
        self._refresh_all()
        self.log("Сборка «%s» удалена" % name)
        self.status_var.set("Сборка «%s» удалена" % name)
        return True

    def _edit_build(self, name):
        """Окно правки сборки: название, режим, версии, ОЗУ, папка."""
        build = self.cfg.find_build(name)
        if build is None:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Сборка — %s" % name)
        dialog.configure(background=theme.COLORS["bg"])
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        name_var = tk.StringVar(value=build.get("name") or name)
        mode_var = tk.StringVar(value="Ванильная" if build.get("mode") == "vanilla" else "NeoForge")
        mc_var = tk.StringVar(value=build.get("mc_version") or "1.21.1")
        neo_var = tk.StringVar(value=(build.get("neoforge_version") or "").strip())
        ram_var = tk.StringVar(value=str(int(build.get("ram_mb") or 4096)))
        dir_var = tk.StringVar(value=build.get("game_dir") or self.cfg.game_dir)
        jvm_var = tk.StringVar(value=build.get("jvm_args") or "")

        def label(text, row, column):
            ttk.Label(frame, text=text, style="H1.TLabel").grid(row=row, column=column,
                                                                sticky="w", padx=(0, 8),
                                                                pady=(10, 2))

        label("Название:", 0, 0)
        theme.entry(frame, textvariable=name_var).grid(row=0, column=1, columnspan=3,
                                                       sticky="ew", pady=(10, 2), ipady=3)
        label("Режим:", 1, 0)
        ttk.Combobox(frame, textvariable=mode_var, state="readonly", width=16,
                     values=["NeoForge", "Ванильная"]).grid(row=1, column=1, sticky="ew",
                                                            pady=(10, 2))
        label("Minecraft:", 2, 0)
        ttk.Combobox(frame, textvariable=mc_var, state="readonly", width=16,
                     values=["1.21.1"]).grid(row=2, column=1, sticky="ew", pady=(10, 2))
        label("NeoForge:", 2, 2)
        ttk.Combobox(frame, textvariable=neo_var, width=16,
                     values=list(reversed(self.neo_versions))).grid(row=2, column=3, sticky="ew",
                                                                    pady=(10, 2))
        label("Оперативная память, МБ:", 3, 0)
        theme.entry(frame, textvariable=ram_var).grid(row=3, column=1, sticky="ew",
                                                      pady=(10, 2), ipady=3)
        label("Папка игры:", 4, 0)
        theme.entry(frame, textvariable=dir_var).grid(row=4, column=1, columnspan=2, sticky="ew",
                                                      pady=(10, 2), ipady=3)
        ttk.Button(frame, text="Обзор…", style="Small.TButton",
                   command=lambda: self._pick_dir(dir_var, dialog)).grid(row=4, column=3,
                                                                         sticky="e",
                                                                         pady=(10, 2))
        label("Доп. аргументы JVM:", 5, 0)
        theme.entry(frame, textvariable=jvm_var).grid(row=5, column=1, columnspan=3, sticky="ew",
                                                      pady=(10, 2), ipady=3)

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(16, 0))

        def save():
            new_name = name_var.get().strip()[:32]
            if not new_name:
                messagebox.showinfo("Сборка", "У сборки должно быть название.", parent=dialog)
                return
            if new_name != name and self.cfg.find_build(new_name) is not None:
                messagebox.showinfo("Сборка", "Сборка «%s» уже есть." % new_name, parent=dialog)
                return
            try:
                ram = max(1024, min(65536, int(float(ram_var.get()))))
            except ValueError:
                ram = int(self.cfg.get("ram_mb") or 4096)
            data = {
                "name": new_name,
                "mode": "vanilla" if mode_var.get() == "Ванильная" else "neoforge",
                "mc_version": (mc_var.get() or "1.21.1").strip(),
                "neoforge_version": neo_var.get().strip(),
                "ram_mb": ram,
                "game_dir": dir_var.get().strip(),
                "jvm_args": jvm_var.get().strip(),
            }
            if new_name != name:
                self.cfg.rename_build(name, new_name)
            self.cfg.upsert_build(data)
            if self.cfg.get("current_build") == new_name:
                self.cfg.select_build(new_name)      # правки текущей сборки — сразу в работу
            self.cfg.save()
            self._apply_config()
            self._refresh_builds()
            self._refresh_all()
            dialog.destroy()
            self.log("Сборка «%s» сохранена: %s" % (new_name, config.Config.build_label(data)))
            self.status_var.set("Сборка «%s» сохранена" % new_name)

        def delete():
            if self._remove_build(name, parent=dialog):
                dialog.destroy()

        ttk.Button(buttons, text="Сохранить", command=save).pack(side="left")
        ttk.Button(buttons, text="Отмена", command=dialog.destroy).pack(side="left", padx=6)
        ttk.Button(buttons, text="Удалить сборку", style="Small.TButton",
                   command=delete).pack(side="right")

        dialog.update_idletasks()
        dialog.geometry("+%d+%d" % (self.root.winfo_rootx() + 120, self.root.winfo_rooty() + 120))

    def _pick_dir(self, variable, parent):
        initial = variable.get() if os.path.isdir(variable.get()) else os.path.expanduser("~")
        chosen = filedialog.askdirectory(title="Выберите папку игры", initialdir=initial,
                                         parent=parent)
        if chosen:
            variable.set(os.path.normpath(chosen))

    def _whats_new(self):
        """Небольшое окно «что нового» (ссылка внизу слева)."""
        window = tk.Toplevel(self.root)
        window.title("Что нового")
        window.configure(background=theme.COLORS["bg"])
        window.transient(self.root)
        window.resizable(False, False)
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="NeoForge Launcher %s" % APP_VERSION,
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Что изменилось", style="Muted.TLabel").pack(anchor="w",
                                                                          pady=(0, 10))
        for title, text in CHANGES:
            block = ttk.Frame(frame)
            block.pack(fill="x", pady=(0, 8))
            ttk.Label(block, text=title, style="H1.TLabel").pack(anchor="w")
            ttk.Label(block, text=text, style="Muted.TLabel", wraplength=430,
                      justify="left").pack(anchor="w")
        ttk.Button(frame, text="Закрыть", command=window.destroy).pack(anchor="e", pady=(6, 0))

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
        if name == "Друзья" and self.state_ready():
            self._refresh_addresses()
            if self.last_scan and time.time() - self.last_scan < 45:
                return
            if not (self.process and self.process.poll() is None):
                self._on_scan()

    def state_ready(self) -> bool:
        """Всё ли построено (вкладки создаются по очереди, до конца — рано)."""
        return hasattr(self, "friends_tree")

    def _build_tabs(self, main):
        """Полоса вкладок под названием сборки: плоские подписи, у активной — черта."""
        holder = ttk.Frame(main)
        holder.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        holder.rowconfigure(2, weight=1)
        holder.columnconfigure(0, weight=1)
        self.tab_bar = tk.Frame(holder, background=theme.COLORS["bg"])
        self.tab_bar.grid(row=0, column=0, sticky="ew")
        separator = tk.Frame(holder, height=1, background=theme.COLORS["border"])
        separator.grid(row=1, column=0, sticky="ew")
        self.tab_body = ttk.Frame(holder)
        self.tab_body.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        self.tab_body.rowconfigure(0, weight=1)
        self.tab_body.columnconfigure(0, weight=1)

        self.tabs = {}          # имя -> (рамка, подпись, черта)
        self.tab_order = []
        self._build_play_tab(self.tab_body)
        self._build_mods_tab(self.tab_body)
        self._build_content_tab(self.tab_body)
        self._build_friends_tab(self.tab_body)
        self._build_skins_tab(self.tab_body)
        self._build_console_tab(self.tab_body)
        self._build_settings_tab(self.tab_body)
        self.show_tab(self.tab_order[0])

    def _build_play_tab(self, parent):
        """Главная вкладка: баннер сборки, большая кнопка «ИГРАТЬ» и строка состояния."""
        frame = ttk.Frame(parent, padding=(0, 12, 0, 0))
        self._add_tab("Играть", frame)
        frame.columnconfigure(0, weight=1)

        hero = tk.Canvas(frame, background=theme.COLORS["card"], height=228,
                         highlightthickness=0, borderwidth=0)
        hero.grid(row=0, column=0, sticky="ew")
        self.hero_canvas = hero
        self.hero_images = {}
        self.hero_photo = hero.create_image(0, 0, anchor="center")
        self.hero_shadow = hero.create_text(0, 0, text="", fill="#1b1426",
                                            font=(theme.FONT, 20, "bold"))
        self.hero_title = hero.create_text(0, 0, text="", fill="#f4f0ff",
                                           font=(theme.FONT, 20, "bold"))
        self.play_button = ttk.Button(hero, text="ИГРАТЬ", style="Play.TButton",
                                      command=self._on_play)
        self.hero_button = hero.create_window(0, 0, window=self.play_button)
        hero.bind("<Configure>", self._layout_hero)
        self._load_hero(hero_banner.FACTOR)

        strip = ttk.Frame(frame)
        strip.grid(row=1, column=0, sticky="ew", pady=(9, 0))
        strip.columnconfigure(1, weight=1)
        self.footer = ttk.Label(strip, style="Muted.TLabel", anchor="w")
        self.footer.grid(row=0, column=0, sticky="w")
        self.strip_nick = ttk.Label(strip, style="H1.TLabel", anchor="e")
        self.strip_nick.grid(row=0, column=2, sticky="e")

        actions = ttk.Frame(frame)
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.install_button = ttk.Button(actions, text="Установить / проверить",
                                         command=self._on_install)
        self.install_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="Отменить", command=self._on_cancel,
                                        state="disabled")
        self.cancel_button.pack(side="left", padx=6)
        ttk.Button(actions, text="Изменить сборку…", style="Small.TButton",
                   command=self._edit_active_build).pack(side="left", padx=(12, 0))
        ttk.Button(actions, text="Открыть папку игры", style="Small.TButton",
                   command=self._open_game_dir).pack(side="right")

        status = ttk.Frame(frame)
        status.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        status.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Готово к запуску")
        ttk.Label(status, textvariable=self.status_var, style="Stage.TLabel").grid(
            row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=1000)
        self.progress.grid(row=4, column=0, sticky="ew", pady=(5, 0))

        card = tk.Frame(frame, background=theme.COLORS["card"])
        card.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        card.columnconfigure(0, weight=1)
        tk.Label(card, text="НОВОЕ В ЛАУНЧЕРЕ", background=theme.COLORS["card"],
                 foreground=theme.COLORS["accent_text"],
                 font=(theme.FONT, 8, "bold")).grid(row=0, column=0, columnspan=2, sticky="w",
                                                    padx=12, pady=(10, 2))
        tk.Label(card, text="Сборки и игра с друзьями", background=theme.COLORS["card"],
                 foreground=theme.COLORS["text_strong"],
                 font=(theme.FONT, 12, "bold")).grid(row=1, column=0, columnspan=2, sticky="w",
                                                     padx=12)
        text = tk.Label(card, justify="left", wraplength=460, background=theme.COLORS["card"],
                        foreground=theme.COLORS["muted"], font=(theme.FONT, 10),
                        text="Слева — список сборок: у каждой свой режим, версия, ОЗУ и папка "
                             "игры. Переключение — один клик, «ИГРАТЬ» запускает выбранную.\n"
                             "Друг открывает мир «для сети» — вы заходите к нему одной кнопкой "
                             "на вкладке «Друзья».")
        text.grid(row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(4, 4))
        card.bind("<Configure>", lambda event, widget=text: widget.configure(
            wraplength=max(220, event.width - 40)))
        ttk.Button(card, text="Открыть «Друзья»", style="Small.TButton",
                   command=lambda: self.show_tab("Друзья")).grid(row=3, column=1, sticky="e",
                                                                 padx=12, pady=(0, 10))

    def _load_hero(self, factor: int):
        """Подгружает картинку баннера нужного размера (в памяти держим все размеры)."""
        if factor in self.hero_images:
            return
        try:
            self.hero_images[factor] = tk.PhotoImage(file=hero_banner.image_path(factor))
        except (tk.TclError, OSError) as exc:
            self.log("Баннер не построен: %s" % exc)
            self.hero_images[factor] = None
        if self.hero_images[factor] is not None:
            self.hero_canvas.itemconfigure(self.hero_photo, image=self.hero_images[factor])

    def _layout_hero(self, _event=None):
        """Баннер по центру (при узком окне — мельче), подпись сверху, кнопка внизу."""
        canvas = self.hero_canvas
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width <= 1 or height <= 1:
            return
        factor = hero_banner.pick_factor(width)
        self._load_hero(factor)
        canvas.coords(self.hero_photo, width // 2, height // 2)
        canvas.coords(self.hero_shadow, width // 2 + 1, int(height * 0.2) + 1)
        canvas.coords(self.hero_title, width // 2, int(height * 0.2))
        canvas.coords(self.hero_button, width // 2, int(height * 0.79))

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
                               selectforeground="#f2eeff", font=("Consolas", 9),
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

        ttk.Label(frame, text="Галочка = мод загрузится. Снятая — файл уезжает в .disabled.",
                  style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 6))
        self.mods_tree = ttk.Treeview(frame, columns=("name", "state", "size"),
                                      show="headings", selectmode="browse")
        self.mods_tree.heading("name", text="Мод")
        self.mods_tree.heading("state", text="Состояние")
        self.mods_tree.heading("size", text="Размер")
        self.mods_tree.column("name", width=340, anchor="w")
        self.mods_tree.column("state", width=120, anchor="center")
        self.mods_tree.column("size", width=90, anchor="e")
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
        frame.rowconfigure(4, weight=1)

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
        row2.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.create_only_var = tk.BooleanVar(value=True)
        theme.check(row2, "Только контент для Create", self.create_only_var,
                    command=lambda: self._on_search(False)).grid(row=0, column=0, sticky="w")
        self.rp_enable_var = tk.BooleanVar(value=True)
        theme.check(row2, "Включать ресурспак сразу", self.rp_enable_var).grid(
            row=0, column=1, sticky="w", padx=(12, 0))

        row3 = ttk.Frame(frame)
        row3.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(row3, text="Мир для датапаков:", style="Muted.TLabel").pack(side="left")
        self.world_var = tk.StringVar()
        self.world_box = ttk.Combobox(row3, textvariable=self.world_var, state="readonly",
                                      width=24)
        self.world_box.pack(side="left", padx=(6, 0))

        self.content_info = ttk.Label(frame, text="Введите запрос и нажмите «Найти».",
                                      style="Muted.TLabel")
        self.content_info.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 4))

        self.content_tree = ttk.Treeview(frame, columns=("title", "author", "downloads", "desc"),
                                         show="headings", selectmode="browse")
        for key, title, width, anchor in (("title", "Название", 200, "w"),
                                          ("author", "Автор", 100, "w"),
                                          ("downloads", "Загрузок", 80, "e"),
                                          ("desc", "Описание", 200, "w")):
            self.content_tree.heading(key, text=title)
            self.content_tree.column(key, width=width, anchor=anchor)
        self.content_tree.grid(row=4, column=0, sticky="nsew")
        self.content_tree.bind("<Double-1>", lambda _e: self._on_install_content())
        scroll = ttk.Scrollbar(frame, command=self.content_tree.yview)
        scroll.grid(row=4, column=1, sticky="ns")
        self.content_tree.configure(yscrollcommand=scroll.set)

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
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

    # --------------------------------------------------------------- друзья
    def _build_friends_tab(self, parent):
        frame = ttk.Frame(parent, padding=(0, 12, 0, 0))
        self._add_tab("Друзья", frame)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        top = ttk.Frame(frame)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        self.friends_info = ttk.Label(top, style="Muted.TLabel",
                                      text="Нажмите «Обновить поиск»: друзья и миры, открытые "
                                           "для сети, появятся в списке.")
        self.friends_info.grid(row=0, column=0, sticky="w")
        self.scan_button = ttk.Button(top, text="Обновить поиск", style="Small.TButton",
                                      command=self._on_scan)
        self.scan_button.grid(row=0, column=1, sticky="e")

        table = ttk.Frame(frame)
        table.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.friends_tree = ttk.Treeview(table, columns=("name", "address", "world", "source"),
                                         show="headings", selectmode="browse", height=6)
        for key, title, width, anchor in (("name", "Друг / мир", 170, "w"),
                                          ("address", "Адрес", 160, "w"),
                                          ("world", "Мир", 250, "w"),
                                          ("source", "Откуда", 120, "w")):
            self.friends_tree.heading(key, text=title)
            self.friends_tree.column(key, width=width, anchor=anchor)
        self.friends_tree.grid(row=0, column=0, sticky="nsew")
        self.friends_tree.bind("<Double-1>", lambda _event: self._on_connect())
        scroll = ttk.Scrollbar(table, command=self.friends_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.friends_tree.configure(yscrollcommand=scroll.set)

        actions = ttk.Frame(frame)
        actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="Подключиться к другу (автозаход)",
                   command=self._on_connect).pack(side="left")
        ttk.Button(actions, text="Добавить друга…", style="Small.TButton",
                   command=self._on_add_friend).pack(side="left", padx=6)
        ttk.Button(actions, text="Удалить", style="Small.TButton",
                   command=self._on_remove_friend).pack(side="left")
        ttk.Button(actions, text="Копировать адрес", style="Small.TButton",
                   command=self._on_copy_address).pack(side="right")

        card = ttk.Labelframe(frame, text=" Мой мир ", style="Card.TLabelframe", padding=10)
        card.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        card.columnconfigure(0, weight=1)
        self.world_status = ttk.Label(card, style="Card.TLabel",
                                      text="Мир ещё не открыт для сети.")
        self.world_status.grid(row=0, column=0, sticky="w")
        self.my_addresses = ttk.Label(card, text="", style="CardMuted.TLabel", wraplength=660,
                                      justify="left")
        self.my_addresses.grid(row=1, column=0, sticky="w", pady=(4, 0))

        row = ttk.Frame(card, style="Card.TFrame")
        row.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.share_var = tk.BooleanVar(value=True)
        theme.check(row, "Объявлять мой мир в сети", self.share_var,
                    command=self._on_share_toggle).pack(side="left")
        self.upnp_button = ttk.Button(row, text="Открыть порт (UPnP)", style="Small.TButton",
                                      command=self._on_upnp)
        self.upnp_button.pack(side="right")
        self.upnp_close_button = ttk.Button(row, text="Закрыть порт", style="Small.TButton",
                                            command=self._on_upnp_close, state="disabled")
        self.upnp_close_button.pack(side="right", padx=6)
        ttk.Button(row, text="Копировать приглашение", style="Small.TButton",
                   command=self._on_copy_invite).pack(side="right", padx=6)

        self.share_info = ttk.Label(card, text="", style="CardMuted.TLabel", wraplength=660,
                                    justify="left")
        self.share_info.grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Label(card, style="CardMuted.TLabel", wraplength=660, justify="left",
                  text="Как играть вдвоём: поставьте Radmin VPN (или играйте в одной сети), друг "
                       "в игре открывает мир «для сети», вы жмёте «Обновить поиск», выбираете друга "
                       "и «Подключиться» — игра запустится и зайдёт в мир сама.").grid(
            row=4, column=0, sticky="w", pady=(8, 0))

    # ------------------------------------------------------------ настройки
    def _scroll_page(self, parent):
        """Страница с вертикальной прокруткой: содержимое может быть выше окна."""
        holder = ttk.Frame(parent, padding=(0, 12, 0, 0))
        canvas = tk.Canvas(holder, background=theme.COLORS["bg"], highlightthickness=0,
                           borderwidth=0)
        canvas.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        bar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=bar.set)
        box = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=box, anchor="nw")
        box.bind("<Configure>", lambda _event: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window,
                                                                     width=event.width))
        canvas.bind("<MouseWheel>", lambda event: canvas.yview_scroll(
            -1 if event.delta > 0 else 1, "units"))
        return holder, box

    def _build_settings_tab(self, parent):
        holder, frame = self._scroll_page(parent)
        self._add_tab("Настройки", holder)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)
        self._settings_frame = frame

        # --- сборка и аккаунт (как в официальном лаунчере — в настройках)
        ttk.Label(frame, text="Сборка:", style="H1.TLabel").grid(row=0, column=0, sticky="w",
                                                                 padx=(0, 6))
        self.build_var = tk.StringVar()
        self.build_box = ttk.Combobox(frame, textvariable=self.build_var, state="readonly")
        self.build_box.grid(row=0, column=1, sticky="ew")
        self.build_box.bind("<<ComboboxSelected>>", self._on_build_pick)
        ttk.Button(frame, text="Изменить сборку…", style="Small.TButton",
                   command=self._edit_active_build).grid(row=0, column=2, columnspan=2,
                                                         sticky="w", padx=(8, 0))

        ttk.Label(frame, text="Никнейм:", style="H1.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(10, 0))
        theme.entry(frame, textvariable=self.user_var, width=16).grid(
            row=1, column=1, sticky="ew", pady=(10, 0), ipady=3)
        ttk.Label(frame, text="Режим:", style="H1.TLabel").grid(
            row=1, column=2, sticky="w", padx=(14, 6), pady=(10, 0))
        self.mode_var = tk.StringVar()
        mode_box = ttk.Combobox(frame, textvariable=self.mode_var, state="readonly", width=18,
                                values=["NeoForge (моды)", "Ванильный (без модов)"])
        mode_box.grid(row=1, column=3, sticky="ew", pady=(10, 0))
        mode_box.bind("<<ComboboxSelected>>", lambda _e: self._on_mode_change())

        ttk.Label(frame, text="Minecraft:", style="H1.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(10, 0))
        self.mc_var = tk.StringVar(value="1.21.1")
        ttk.Label(frame, textvariable=self.mc_var, style="Muted.TLabel").grid(
            row=2, column=1, sticky="w", pady=(10, 0))
        ttk.Label(frame, text="NeoForge:", style="H1.TLabel").grid(
            row=2, column=2, sticky="w", padx=(14, 6), pady=(10, 0))
        self.neo_var = tk.StringVar()
        self.neo_box = ttk.Combobox(frame, textvariable=self.neo_var, width=16)
        self.neo_box.grid(row=2, column=3, sticky="ew", pady=(10, 0))

        ttk.Label(frame, text="Оперативная память:", style="H1.TLabel").grid(
            row=3, column=0, sticky="w", padx=(0, 6), pady=(10, 0))
        ram_frame = ttk.Frame(frame)
        ram_frame.grid(row=3, column=1, columnspan=3, sticky="ew", pady=(10, 0))
        ram_frame.columnconfigure(0, weight=1)
        self.ram_var = tk.IntVar(value=4096)
        self.ram_scale = ttk.Scale(ram_frame, from_=1024, to=16384, orient="horizontal",
                                   command=self._on_ram_change)
        self.ram_scale.grid(row=0, column=0, sticky="ew")
        self.ram_label = ttk.Label(ram_frame, text="4096 МБ", style="Muted.TLabel")
        self.ram_label.grid(row=0, column=1, sticky="w", padx=(10, 0))

        ttk.Label(frame, text="Папка игры:", style="H1.TLabel").grid(
            row=4, column=0, sticky="w", padx=(0, 6), pady=(10, 0))
        self.dir_var = tk.StringVar()
        theme.entry(frame, textvariable=self.dir_var, readonly=True).grid(
            row=4, column=1, columnspan=2, sticky="ew", pady=(10, 0), ipady=3)
        ttk.Button(frame, text="Изменить…", style="Small.TButton",
                   command=self._choose_dir).grid(row=4, column=3, sticky="e", padx=(8, 0),
                                                  pady=(10, 0))

        ttk.Label(frame, text="Java:", style="H1.TLabel").grid(
            row=5, column=0, sticky="w", padx=(0, 6), pady=(10, 0))
        self.java_var = tk.StringVar()
        self.java_box = ttk.Combobox(frame, textvariable=self.java_var, values=[])
        self.java_box.grid(row=5, column=1, columnspan=3, sticky="ew", pady=(10, 0))
        java_buttons = ttk.Frame(frame)
        java_buttons.grid(row=6, column=2, columnspan=2, sticky="e", pady=(6, 0))
        ttk.Button(java_buttons, text="Указать вручную…", style="Small.TButton",
                   command=self._choose_java).pack(side="left")
        ttk.Button(java_buttons, text="Скачать Java 21", style="Small.TButton",
                   command=self._download_java).pack(side="left", padx=4)

        ttk.Label(frame, text="Доп. аргументы JVM:", style="H1.TLabel").grid(
            row=7, column=0, sticky="w", padx=(0, 6), pady=(10, 0))
        self.jvm_var = tk.StringVar()
        theme.entry(frame, textvariable=self.jvm_var).grid(
            row=7, column=1, columnspan=3, sticky="ew", pady=(10, 0), ipady=3)

        self.skip_sounds_var = tk.BooleanVar()
        theme.check(frame, "Не скачивать звуки (~700 МБ меньше, игра будет без звука)",
                    self.skip_sounds_var).grid(row=8, column=0, columnspan=4,
                                               sticky="w", pady=(12, 2))
        self.close_on_start_var = tk.BooleanVar()
        theme.check(frame, "Закрывать лаунчер после запуска игры",
                    self.close_on_start_var).grid(row=9, column=0, columnspan=4,
                                                  sticky="w", pady=2)
        ttk.Button(frame, text="Сохранить настройки", command=self._save_settings).grid(
            row=10, column=0, sticky="w", pady=(12, 0))

        tools = ttk.Labelframe(frame, text=" Сервис ", style="Card.TLabelframe", padding=10)
        tools.grid(row=11, column=0, columnspan=4, sticky="ew", pady=(16, 0))
        ttk.Button(tools, text="Создать ярлык на рабочем столе", style="Small.TButton",
                   command=self._create_shortcut).pack(side="left")
        ttk.Button(tools, text="Ярлык в папке лаунчера", style="Small.TButton",
                   command=lambda: self._create_shortcut(False)).pack(side="left", padx=6)
        ttk.Button(tools, text="Открыть папку игры", style="Small.TButton",
                   command=self._open_game_dir).pack(side="left")

        ttk.Label(frame, justify="left", wraplength=660, style="Muted.TLabel",
                  text="Вход выполняется в офлайн-режиме по нику (без аккаунта Microsoft). "
                       "Для игры на серверах с проверкой лицензии нужен лицензионный аккаунт — "
                       "эта версия лаунчера его не поддерживает.\n"
                       "Моды должны быть для NeoForge 1.21.1: старые моды для Forge не подойдут. "
                       "Моды лежат в папке игры и общие для всех сборок — сборка задаёт режим, "
                       "версию, ОЗУ и папку.").grid(row=12, column=0, columnspan=4, sticky="w",
                                                   pady=(16, 0))

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
        self.post(self._refresh_addresses)
        self.post(lambda: self.root.after(6000, self._auto_scan))
        self.log("Готово. Ник: %s" % self.cfg.get("username", "Player"))

    def _refresh_all(self):
        self._refresh_mods()
        self._refresh_worlds()
        self._refresh_skin()
        self._refresh_footer()
        self._refresh_friends()

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
        target = ("NeoForge " + neo) if neo else ("ванильная" if not neoforge_mode else "без модов")
        self.footer.configure(text="Minecraft %s  •  %s  •  %s  •  %s" % (
            mc_version, target, state, java_text))
        name = self.cfg.get("current_build") or "сборка"
        self.main_title.configure(text="MINECRAFT: %s" % name.upper())
        self.hero_canvas.itemconfigure(self.hero_title, text=name.upper())
        self.hero_canvas.itemconfigure(self.hero_shadow, text=name.upper())
        self.strip_nick.configure(text=auth.sanitize_username(self.user_var.get()))

    # ================================================================ настройки
    def _apply_config(self):
        self.cfg.active_build()          # список сборок не бывает пустым
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
        self.share_var.set(bool(self.cfg.get("share_world", True)))
        self.skin_model.set(self.cfg.get("skin_model", "wide"))
        self.content_type.set({"mod": "Моды", "datapack": "Датапаки",
                               "resourcepack": "Ресурспаки"}.get(
            self.cfg.get("content_type", "mod"), "Моды"))
        total = paths.system_memory_mb()
        upper = max(2048, min(total - 1024, 16384)) if total else 16384
        self.ram_scale.configure(to=upper)
        self.ram_scale.set(min(max(1024, int(self.cfg.get("ram_mb", 4096))), upper))
        self._on_ram_change()
        self._refresh_builds()

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
        self.cfg["share_world"] = bool(self.share_var.get())
        java_value = (self.java_var.get() or "").split(" — ")[0].strip()
        if java_value.lower().endswith((".exe", "java")):
            self.cfg["java_path"] = java_value
        self.cfg.sync_active_build()      # текущие настройки — это и есть выбранная сборка
        return self.cfg

    def _save_settings(self):
        self._collect_config().save()
        self.log("Настройки сохранены")
        self._refresh_builds()
        self.status_var.set("Настройки сохранены — сборка «%s»"
                            % (self.cfg.get("current_build") or ""))

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
            desc = hit["description"] or ""
            if len(desc) > 80:                 # колонка узкая — длинное описание не влезет
                desc = desc[:78].rstrip() + "…"
            self.content_tree.insert("", "end", iid=str(index), values=(
                hit["title"], hit["author"] or "", "{:,}".format(hit["downloads"]).replace(",", " "),
                desc))
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

    # ================================================================ друзья
    def _refresh_friends(self):
        """Перерисовывает список: мои друзья + все, кто нашёлся в сети."""
        self.friends_tree.delete(*self.friends_tree.get_children())
        self.friend_rows = {}
        live = {}
        for item in self.found.get("friends", []):
            live[item["nick"].lower()] = item
        for item in self.friends.list():
            found = live.pop(item["name"].lower(), None)
            if found:
                self._add_friend_row(item["name"], found["host"], found["port"],
                                     found.get("world") or item.get("world") or "открыт для сети",
                                     "рядом (сеть)")
            else:
                self._add_friend_row(item["name"], item.get("address", ""), item.get("port") or 0,
                                     item.get("world") or "—", "мой список")
        for found in sorted(live.values(), key=lambda item: item["nick"].lower()):
            self._add_friend_row(found["nick"], found["host"], found["port"],
                                 found.get("world") or "открыт для сети", "рядом (сеть)")
        for world in self.found.get("worlds", []):
            self._add_friend_row(world["motd"], world["host"], world["port"], "открыт для сети",
                                 "мир в сети")
        self._select_best_row()

    def _add_friend_row(self, name, host, port, world, source):
        port = int(port or 0)
        address = lan.format_address(host, port) if host else ("порт %d" % port if port else "—")
        item = self.friends_tree.insert("", "end", values=(name, address, world, source))
        self.friend_rows[item] = {"name": name, "host": host, "port": port, "world": world,
                                  "source": source}

    def _select_best_row(self):
        """По умолчанию выделяет того, к кому сейчас реально можно зайти."""
        items = self.friends_tree.get_children()
        if not items:
            return
        current = self.friends_tree.selection()
        if current and current[0] in self.friend_rows:
            return
        for item in items:
            if self.friend_rows[item]["source"].startswith("рядом"):
                self.friends_tree.selection_set(item)
                return
        self.friends_tree.selection_set(items[0])

    def _selected_friend(self):
        selection = self.friends_tree.selection()
        if not selection:
            return None
        return self.friend_rows.get(selection[0])

    def _best_share_host(self, items=None) -> str:
        """Адрес, который называем другу: сначала виртуальная сеть (Radmin VPN и similar)."""
        return lan.best_share_address(items)

    def _refresh_addresses(self):
        """Показывает мои адреса: именно их называют друзьям."""
        items = lan.local_addresses()
        best = self._best_share_host(items)
        parts = []
        for item in items:
            label = item["ip"] + ((" (%s)" % item["name"]) if item["name"] else "")
            if item["ip"] == best and len(items) > 1:
                label += " — для друзей"
            parts.append(label)
        self.my_addresses.configure(
            text=("Мой адрес: " + "  ·  ".join(parts)) if parts else
            "Сетевые адреса не найдены — проверьте подключение к сети.")
        self._refresh_world_status()

    def _refresh_world_status(self):
        if self.world_port:
            share = "  ·  объявляю друзьям" if self._beacon_running() else ""
            self.world_status.configure(text="Мир открыт для сети — порт %d%s"
                                             % (self.world_port, share))
        else:
            self.world_status.configure(text="Мир ещё не открыт для сети: в игре Esc → «Открыть "
                                             "для сети» — порт лаунчер увидит сам.")

    def _on_scan(self):
        if self.scanning:
            return
        self.scanning = True
        self.scan_button.configure(state="disabled")
        self.status_var.set("Ищу друзей и миры в сети…")
        self.log("Поиск в локальной сети (мультикаст игры + объявления лаунчеров)…")

        def worker():
            try:
                result = lan.scan(2.6, log=self.log, my_id=self.friends.me_id())
            except Exception as exc:          # noqa: BLE001
                result = {"worlds": [], "friends": [], "errors": [str(exc)]}
            self.found = result
            self.last_scan = time.time()
            for message in result.get("errors", []):
                self.log(message)
            self.post(self._refresh_friends)
            self.post(lambda: self.friends_info.configure(
                text="Найдено в сети: друзей — %d, миров — %d. Пусто? Значит никто не открыл мир "
                     "«для сети»." % (len(result["friends"]), len(result["worlds"]))))
            self.post(lambda: self.status_var.set("Поиск завершён"))

            def done():
                self.scanning = False
                self.scan_button.configure(state="normal")
            self.post(done)

        threading.Thread(target=worker, daemon=True).start()

    def _auto_scan(self):
        """Тихий поиск при заходе на вкладку (только если игра не запущена)."""
        if self.scanning or (self.process and self.process.poll() is None):
            return
        self._on_scan()

    def _on_connect(self):
        row = self._selected_friend()
        if row is None:
            messagebox.showinfo("Друзья", "Выберите друга или мир в списке.", parent=self.root)
            return
        if not row["host"] or not row["port"]:
            messagebox.showinfo("Друзья",
                                "У этого друга пока нет адреса.\n\n"
                                "Попросите приглашение («Добавить друга…» понимает код CL1.…) или "
                                "нажмите «Обновить поиск», если он рядом в сети.", parent=self.root)
            return
        self._start_worker(launch_after=True, join=row)

    def _on_add_friend(self):
        text = simpledialog.askstring(
            "Добавить друга",
            "Вставьте приглашение друга (сообщение или код CL1.…)\n"
            "либо введите «Имя 26.0.0.5:51234»:", parent=self.root)
        if not text or not text.strip():
            return
        parsed = friends_mod.parse_invite(text)
        if parsed is None:
            messagebox.showinfo("Друзья", "В тексте не вижу адреса.\n\nПодойдёт приглашение из "
                                          "лаунчера, код CL1.… или строка вида «Вася 26.0.0.5:51234».",
                                parent=self.root)
            return
        name = (parsed.get("name") or "").strip()
        if not name or name == "Друг":
            name = simpledialog.askstring("Добавить друга", "Как зовут друга?", initialvalue=name,
                                          parent=self.root) or name
        name = (name or "Друг").strip()[:24]
        self.friends.add(name, parsed.get("address", ""), int(parsed.get("port") or 0))
        friend = self.friends.find(name)
        if friend and parsed.get("world"):
            friend["world"] = parsed["world"]
            self.friends.save()
        address = lan.format_address(parsed["address"], parsed["port"]) if parsed.get("address") \
            else "без адреса"
        self.log("Друг добавлен: %s (%s)" % (name, address))
        self.status_var.set("Друг добавлен: %s" % name)
        self._refresh_friends()

    def _on_remove_friend(self):
        row = self._selected_friend()
        if row is None:
            messagebox.showinfo("Друзья", "Сначала выберите друга в списке.", parent=self.root)
            return
        if not messagebox.askyesno("Друзья", "Удалить «%s» из списка друзей?" % row["name"],
                                   parent=self.root):
            return
        removed = self.friends.remove(row["name"])
        servers_dat.remove(self.cfg.game_dir, row["name"])
        self.log(("Удалён друг %s" % row["name"]) if removed else
                 ("Убрано из списка: %s" % row["name"]))
        self._refresh_friends()
        self.status_var.set("Список друзей обновлён")

    def _copy(self, text, what):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()
        self.status_var.set("%s скопирован в буфер обмена" % what)
        first = text.splitlines()[0] if text else ""
        self.log("%s: %s" % (what, first))

    def _on_copy_address(self):
        row = self._selected_friend()
        if row is None or not row["host"]:
            messagebox.showinfo("Друзья", "У выбранной строки нет адреса.", parent=self.root)
            return
        self._copy(lan.format_address(row["host"], row["port"]), "Адрес")

    def _on_copy_invite(self):
        if not self.world_port:
            messagebox.showinfo("Друзья", "Сначала откройте мир в игре («Открыть для сети») — "
                                          "без порта приглашение не имеет смысла.", parent=self.root)
            return
        host = self._best_share_host()
        nick = auth.sanitize_username(self.user_var.get())
        world = (self.cfg.get("last_world") or "").strip() or "Мир %s" % nick
        self._copy(friends_mod.invite_text(nick, host, self.world_port, world), "Приглашение")

    def _on_share_toggle(self):
        if self.share_var.get() and not self.world_port:
            self.share_info.configure(text="Объявление включится само, как только вы откроете мир "
                                           "«для сети».")
        self._update_beacon()

    def _update_beacon(self):
        """Объявляет мой мир в сети, пока он открыт (иначе — молчит)."""
        want = bool(self.share_var.get()) and self.world_port > 0
        if want and not self._beacon_running():
            nick = auth.sanitize_username(self.user_var.get())
            world = (self.cfg.get("last_world") or "").strip() or "Мир %s" % nick
            self.beacon_info = {"nick": nick, "port": self.world_port, "world": world,
                                "players": 0, "state": "открыт для сети"}
            self.beacon = lan.Beacon(self._beacon_provider)
            self.beacon.start()
            self.log("Объявляю мир в сети: порт %d, ник %s" % (self.world_port, nick))
        elif not want and self._beacon_running():
            self.beacon.stop()
            self.beacon = None
            self.log("Объявление мира остановлено")
        self._refresh_world_status()

    def _beacon_running(self) -> bool:
        return bool(self.beacon is not None and self.beacon.is_alive())

    def _beacon_provider(self):
        """Данные для объявления (читает фоновый поток — только простые значения)."""
        info = self.beacon_info
        return (info.get("nick", ""), int(info.get("port") or 0), info.get("world", ""),
                int(info.get("players") or 0), info.get("state", ""), self.friends.me_id())

    def _on_upnp(self):
        if not self.world_port:
            messagebox.showinfo("Друзья", "Сначала откройте мир в игре «для сети» — роутеру нужно "
                                          "знать порт мира.", parent=self.root)
            return
        internal = lan.primary_address()
        world_port = self.world_port
        external = int(self.cfg.get("upnp_port") or upnp.DEFAULT_EXTERNAL_PORT)
        self.stage("Открываю порт на роутере (UPnP)…")
        self.share_info.configure(text="Ищу роутер с UPnP…")
        self.log("UPnP: пробрасываю порт %d → %s:%d" % (external, internal, world_port))

        def worker():
            try:
                info = upnp.open_world_port(internal, world_port, external)
            except upnp.UpnpError as exc:
                text = "UPnP: %s" % exc
                self.log(text)
                self.post(lambda: self.share_info.configure(text=text))
                self.post(lambda: self.status_var.set("UPnP не сработал"))
                return
            self.upnp_info = info
            address = lan.format_address(info["address"], info["port"])
            self.post(lambda: self.share_info.configure(
                text="Порт открыт на роутере: %s — этот адрес можно отправить другу, Radmin VPN "
                     "не нужен." % address))
            self.post(lambda: self.upnp_close_button.configure(state="normal"))
            self.post(lambda: self._copy(address, "Адрес"))
            self.log("UPnP: %s → %s (%s)" % (address, info["internal"], ", ".join(info["mapped"])))

        threading.Thread(target=worker, daemon=True).start()

    def _on_upnp_close(self):
        info = self.upnp_info or {}
        external = int(info.get("port") or self.cfg.get("upnp_port") or upnp.DEFAULT_EXTERNAL_PORT)
        self.stage("Закрываю порт на роутере")
        self.upnp_close_button.configure(state="disabled")

        def worker():
            removed = upnp.close_world_port(external)
            self.upnp_info = None
            self.log("Проброс порта %d: %s" % (external, "закрыт" if removed else "не найден"))
            self.post(lambda: self.share_info.configure(
                text="Проброс порта закрыт." if removed else
                "Не удалось закрыть проброс — роутер не ответил."))

        threading.Thread(target=worker, daemon=True).start()

    def _world_opened(self):
        """Игра сообщила в логе порт мира, открытого «для сети»."""
        self.log("Мир открыт для сети — порт %d" % self.world_port)
        self._refresh_world_status()
        self._update_beacon()
        self.friends_info.configure(
            text="Ваш мир виден друзьям на этой вкладке: порт %d." % self.world_port)

    def _world_closed(self):
        self.world_port = 0
        self._refresh_world_status()
        self._update_beacon()
        info = self.upnp_info
        if not info:
            return
        self.upnp_info = None
        self.upnp_close_button.configure(state="disabled")

        def worker():
            removed = upnp.close_world_port(int(info["port"]))
            self.log("Мир закрыт — проброс порта %d %s"
                     % (info["port"], "снят" if removed else "уже неактуален"))
            self.post(lambda: self.share_info.configure(text="Мир закрыт, проброс порта снят."))

        threading.Thread(target=worker, daemon=True).start()

    def _friend_icon(self) -> str:
        """Иконка друга в списке серверов игры (64x64 PNG крипера, чистый base64)."""
        if self.server_icon is None:
            try:
                size, _height, rgba = branding.creeper_rgba(64)
                self.server_icon = base64.b64encode(png.encode(size, size, rgba)).decode("ascii")
            except Exception:                 # noqa: BLE001
                self.log("Иконку для списка серверов сделать не удалось — не страшно")
                self.server_icon = ""
        return self.server_icon

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

    def _start_worker(self, launch_after: bool, join=None):
        if self.busy or (self.process and self.process.poll() is None):
            return
        self._collect_config().save()
        self._set_busy(True)
        self.progress.configure(value=0)
        threading.Thread(target=self._worker, args=(launch_after, join), daemon=True).start()

    def _prepare_join(self, join: dict, mc_dir: str) -> str:
        """Проверяет мир друга и готовит автозаход: servers.dat + адрес для quick play."""
        host, port = join["host"], int(join["port"])
        address = lan.format_address(host, port)
        self.stage("Проверяю мир друга (%s)" % address)
        self.log("Подключаюсь к «%s» (%s)…" % (join["name"], address))
        if not lan.probe(host, port, 2.5):
            raise RuntimeError(
                "Мир не отвечает: %s\n\n"
                "Проверьте, что друг открыл мир в игре («Открыть для сети»), что вы оба в одной "
                "сети (Radmin VPN или Wi-Fi) и что адрес ещё актуален — кнопка «Обновить поиск»."
                % address)
        self.join_label = join["name"]
        try:
            self.friends.touch(join["name"], host, port, join.get("world", ""))
            self.post(self._refresh_friends)
        except Exception as exc:              # noqa: BLE001
            self.log("Список друзей обновить не удалось: %s" % exc)
        try:
            servers_dat.upsert(mc_dir, join["name"], address, icon=self._friend_icon())
            self.log("«%s» появится и в сетевой игре — в списке серверов" % join["name"])
        except Exception as exc:              # noqa: BLE001
            self.log("servers.dat обновить не удалось: %s" % exc)
        return address

    def _worker(self, launch_after: bool, join=None):
        try:
            cfg = self.cfg
            mc_dir = cfg.game_dir
            mc_version = cfg.get("mc_version", "1.21.1")
            mode = cfg.get("mode", "neoforge")
            quick_play = self._prepare_join(join, mc_dir) if join else ""

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
            self.stage("Запуск Minecraft" if not quick_play else
                       "Запускаю игру и захожу в мир друга")
            process, _resolved = launch.launch(
                mc_dir, target, java, int(cfg.get("ram_mb", 4096)),
                auth.sanitize_username(cfg.get("username", "Player")),
                cfg.get("jvm_args", ""), int(cfg.get("width") or 0), int(cfg.get("height") or 0),
                log=self.log, quick_play=quick_play)
            self.process = process
            self.post(lambda: self.progress.configure(value=1000))
            self.post(lambda: self.status_var.set(
                "Захожу в мир «%s»" % self.join_label if quick_play else "Игра запущена"))
            self.post(lambda: self._set_busy(False))
            if cfg.get("close_launcher_on_start") and paths.WINDOWS:
                self.post(self.root.destroy)
            for line in process.stdout or []:
                text = line.rstrip()
                self.log(text)
                port = lan.started_serving_port(text)
                if port and port != self.world_port:
                    self.world_port = port
                    self.post(self._world_opened)
            code = process.wait()
            self.log("Игра завершилась (код %s)" % code)
            if self.world_port:
                self.world_port = 0
                self.post(self._world_closed)
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
        if self.beacon is not None:
            self.beacon.stop()
            self.beacon = None
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
