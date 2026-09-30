"""Draft-based research preferences; only Save writes application settings."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk

from .native_window import theme_window

PAPER = "#d3ba8d"
INK = "#352519"
RED = "#641b13"


class SettingsDialog:
    def __init__(self, app):
        from .gui_app import ACTION_LABELS, ACTION_ORDER, PLACEMENT_SPEED_PRESETS
        self.app = app
        self.window = tk.Toplevel(app.tk)
        self.window.title("研究配置 · Thaumcraft Nexus")
        self.window.configure(bg="#211611")
        self.window.geometry("800x530")
        self.window.minsize(760, 510)
        self.window.transient(app.tk)
        self.window.grab_set()
        theme_window(self.window)
        self.shortcuts = dict(app.shortcuts)
        self.mode = tk.StringVar(self.window, app.solver_mode)
        self.pid = tk.StringVar(self.window, app.target_pid)
        speed = app._normalize_placement_speed(app.placement_speed)
        self.preset = tk.StringVar(self.window, speed["preset"])
        self.delay = tk.StringVar(self.window, str(speed["delayMs"]))
        self.verify = tk.StringVar(self.window, str(speed["verifyDelayMs"]))
        self.hint = tk.StringVar(self.window, "修改将在保存配置后生效。")
        self.pending = None
        self.closed = False
        self.capture_action = None
        self.results = queue.Queue()
        self.refreshing = False
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.bind("<Escape>", self.escape)
        self.window.bind("<KeyPress>", self.capture_key)

        footer = tk.Frame(self.window, bg="#211611", padx=18, pady=14)
        footer.pack(side="bottom", fill="x")
        ttk.Button(footer, text="恢复本页默认", command=self.reset_page).pack(side="left")
        ttk.Button(footer, text="保存配置", style="Primary.TButton", command=self.save).pack(side="right")
        ttk.Button(footer, text="取消", command=self.cancel).pack(side="right", padx=10)
        tk.Label(self.window, textvariable=self.hint, bg="#211611", fg="#e6cda5",
                 anchor="w", wraplength=730, padx=18, pady=8).pack(side="bottom", fill="x")
        body = tk.Frame(self.window, bg="#211611")
        body.pack(fill="both", expand=True, padx=14, pady=(14, 0))
        nav = tk.Frame(body, bg="#211611", width=154)
        nav.pack(side="left", fill="y", padx=(0, 12))
        tk.Label(nav, text="研究配置", bg="#211611", fg="#d9bc86",
                 font=("Microsoft YaHei", 17), pady=18).pack(fill="x")
        self.content = tk.Frame(body, bg=PAPER, padx=24, pady=20)
        self.content.pack(side="left", fill="both", expand=True)
        self.pages = {}
        self.nav = {}
        for title in ("研究策略", "注入节律", "快捷符令", "世界连接"):
            self.nav[title] = tk.Button(nav, text=title, command=lambda t=title: self.show_page(t),
                                       bg="#211611", fg="#d9bc86", activebackground=RED,
                                       activeforeground="#f3dfb8", relief="flat", bd=0,
                                       font=("Microsoft YaHei", 11), padx=22, pady=12)
            self.nav[title].pack(fill="x", pady=3)
            page = tk.Frame(self.content, bg=PAPER)
            self.pages[title] = page
            self.label(page, title, 18).pack(anchor="w", pady=(0, 16))
        from .client_bridge import DEFAULT_SOLVER_MODE, SOLVER_MODE_OPTIMAL
        page = self.pages["研究策略"]
        for value, title, description in (
            (DEFAULT_SOLVER_MODE, "库存优先", "优先使用储备充足的要素，尽量减少合成与稀缺库存消耗。"),
            (SOLVER_MODE_OPTIMAL, "精简连线", "在搜索预算内减少放置格数，再兼顾库存与合成；不保证全局最优。"),
        ):
            card = tk.Frame(page, bg="#c6aa7d", padx=14, pady=10)
            card.pack(fill="x", pady=(0, 14))
            tk.Radiobutton(card, text=title, variable=self.mode, value=value, bg="#c6aa7d",
                           fg=RED, selectcolor=PAPER, activebackground="#c6aa7d",
                           font=("Microsoft YaHei", 12)).pack(anchor="w")
            tk.Label(card, text=description, wraplength=450, justify="left", bg="#c6aa7d",
                     fg=INK, font=("Microsoft YaHei", 10)).pack(anchor="w", pady=(6, 0))
        page = self.pages["注入节律"]
        self.label(page, "较慢的服务器建议使用稳定预设；极速可能增加校验失败。", 10).pack(anchor="w")
        choices = tk.Frame(page, bg=PAPER)
        choices.pack(fill="x", pady=18)
        for key, value in PLACEMENT_SPEED_PRESETS.items():
            tk.Radiobutton(choices, text=value["label"], variable=self.preset, value=key,
                           command=self.speed_changed, bg=PAPER, fg=INK,
                           activebackground=PAPER, selectcolor=PAPER).pack(side="left")
        self.speed_summary = tk.StringVar(self.window)
        tk.Label(page, textvariable=self.speed_summary, bg=PAPER, fg=RED).pack(anchor="w", pady=10)
        self.custom = tk.Frame(page, bg=PAPER)
        for row, (label, variable) in enumerate((("要素间隔（毫秒）", self.delay), ("完成等待（毫秒）", self.verify))):
            self.label(self.custom, label, 10).grid(row=row, column=0, sticky="w", pady=8)
            ttk.Entry(self.custom, textvariable=variable, width=14).grid(row=row, column=1, padx=20)
        self.speed_changed()
        page = self.pages["快捷符令"]
        self.label(page, "选择重新绑定后按下快捷键，Esc 取消本次绑定。", 10).pack(anchor="w", pady=(0, 12))
        rows = tk.Frame(page, bg=PAPER)
        rows.pack(fill="x")
        rows.columnconfigure(0, weight=1, minsize=190)
        self.shortcut_vars = {}
        for row, action in enumerate(ACTION_ORDER):
            self.label(rows, ACTION_LABELS[action], 10).grid(row=row, column=0, sticky="w", pady=12)
            var = tk.StringVar(self.window, app._shortcut_display(self.shortcuts[action]))
            self.shortcut_vars[action] = var
            tk.Label(rows, textvariable=var, bg=PAPER, fg=RED, width=12).grid(row=row, column=1, padx=12)
            ttk.Button(rows, text="重新绑定", command=lambda a=action: self.capture(a)).grid(row=row, column=2)
        page = self.pages["世界连接"]
        self.label(page, "默认自动检测游戏；手动选择仅对本次运行生效。", 10).pack(anchor="w")
        ttk.Button(page, text="使用自动检测", command=lambda: self.pid.set("")).pack(anchor="w", pady=14)
        self.process = tk.StringVar(self.window)
        self.process_combo = ttk.Combobox(page, textvariable=self.process, state="readonly", width=48)
        self.process_combo.pack(fill="x", pady=8)
        self.process_combo.bind("<<ComboboxSelected>>", self.select_process)
        self.refresh_button = ttk.Button(page, text="刷新游戏进程", command=self.refresh_processes)
        self.refresh_button.pack(anchor="w", pady=6)
        self.manual = tk.Frame(page, bg=PAPER)
        self.label(self.manual, "PID", 10).pack(side="left", padx=(0, 12))
        ttk.Entry(self.manual, textvariable=self.pid, width=20).pack(side="left")
        ttk.Button(page, text="手动指定 PID ▾", command=self.toggle_manual).pack(anchor="w", pady=8)
        self.label(page, "当前 PID（空白表示自动检测）：", 10).pack(anchor="w", pady=(10, 0))
        tk.Label(page, textvariable=self.pid, bg=PAPER, fg=RED).pack(anchor="w")
        self.show_page("研究策略")
        self.window.focus_set()

    @staticmethod
    def label(parent, text, size):
        return tk.Label(parent, text=text, bg=PAPER, fg=INK, wraplength=470,
                        justify="left", font=("Microsoft YaHei", size))

    def show_page(self, title):
        self.capture_action = None
        self.page = title
        for name, page in self.pages.items():
            page.pack_forget()
            self.nav[name].configure(bg=RED if name == title else "#211611")
        self.pages[title].pack(fill="both", expand=True)

    def speed_changed(self):
        from .gui_app import PLACEMENT_SPEED_PRESETS
        custom = self.preset.get() == "custom"
        if custom:
            self.custom.pack(fill="x")
        else:
            config = PLACEMENT_SPEED_PRESETS[self.preset.get()]
            self.delay.set(str(config["delayMs"]))
            self.verify.set(str(config["verifyDelayMs"]))
            self.custom.pack_forget()
        self.speed_summary.set("可填写 0 到 5000 毫秒。" if custom else
                               f"要素间隔 {self.delay.get()} ms   ·   完成等待 {self.verify.get()} ms")

    def toggle_manual(self):
        if self.manual.winfo_manager():
            self.manual.pack_forget()
        else:
            self.manual.pack(anchor="w", pady=6)

    def capture(self, action):
        self.capture_action = action
        self.hint.set("请按下新的快捷键；Esc 取消绑定。")
        self.window.focus_set()

    def capture_key(self, event):
        if self.capture_action is None:
            return None
        sequence = self.app._event_to_shortcut(event)
        if sequence is None:
            return "break"
        if sequence == "<Escape>":
            self.capture_action = None
            return "break"
        if any(value == sequence and key != self.capture_action for key, value in self.shortcuts.items()):
            self.hint.set("该快捷键已被其他操作使用，请选择另一个。")
            return "break"
        action = self.capture_action
        self.shortcuts[action] = sequence
        self.shortcut_vars[action].set(self.app._shortcut_display(sequence))
        self.capture_action = None
        self.hint.set("快捷符令已修改，保存配置后生效。")
        return "break"

    def escape(self, _event=None):
        if self.capture_action:
            self.capture_action = None
            self.hint.set("已取消本次快捷键绑定。")
        else:
            self.cancel()
        return "break"

    def reset_page(self):
        from .gui_app import DEFAULT_SHORTCUTS, DEFAULT_PLACEMENT_SPEED_PRESET
        from .client_bridge import DEFAULT_SOLVER_MODE
        if self.page == "研究策略":
            self.mode.set(DEFAULT_SOLVER_MODE)
        elif self.page == "注入节律":
            self.preset.set(DEFAULT_PLACEMENT_SPEED_PRESET)
            self.speed_changed()
        elif self.page == "快捷符令":
            self.shortcuts = dict(DEFAULT_SHORTCUTS)
            for action, var in self.shortcut_vars.items():
                var.set(self.app._shortcut_display(self.shortcuts[action]))
        else:
            self.pid.set("")
            self.process.set("")
        self.hint.set("本页已恢复默认，保存配置后生效。")

    def select_process(self, _event=None):
        if self.process.get():
            self.pid.set(self.process.get().split(maxsplit=1)[0])

    def refresh_processes(self):
        if self.refreshing:
            return
        self.refreshing = True
        self.refresh_button.configure(state="disabled")
        self.hint.set("正在查找游戏进程……")
        def work():
            from .client_bridge import list_java_processes
            try:
                self.results.put(([p.label for p in list_java_processes()], None))
            except Exception as exc:
                self.results.put(([], str(exc)))
        threading.Thread(target=work, daemon=True).start()
        self.pending = self.window.after(80, self.poll_processes)

    def poll_processes(self):
        self.pending = None
        if self.closed:
            return
        try:
            values, error = self.results.get_nowait()
        except queue.Empty:
            self.pending = self.window.after(80, self.poll_processes)
            return
        self.refreshing = False
        self.refresh_button.configure(state="normal")
        self.process_combo.configure(values=values)
        self.process.set("")
        self.hint.set("进程刷新失败：" + error if error else
                      f"发现 {len(values)} 个 Java 进程，请选择游戏进程。" if values else
                      "没有找到 Java 进程，请确认游戏已启动或手动指定 PID。")

    def save(self):
        try:
            delay, verify = int(self.delay.get()), int(self.verify.get())
            if not 0 <= delay <= 5000 or not 0 <= verify <= 5000:
                raise ValueError
        except ValueError:
            self.show_page("注入节律")
            self.hint.set("注入节律只能填写 0 到 5000 毫秒的整数。")
            return
        pid = self.pid.get().strip()
        if pid and (not pid.isascii() or not pid.isdigit() or int(pid) <= 0):
            self.show_page("世界连接")
            self.hint.set("PID 必须为正整数；留空表示自动检测。")
            return
        app = self.app
        old = app.shortcuts, app.solver_mode, app.placement_speed, app.target_pid
        app.shortcuts = dict(self.shortcuts)
        app.solver_mode = self.mode.get()
        app.placement_speed = {"preset": self.preset.get(), "delayMs": delay, "verifyDelayMs": verify}
        app.target_pid = pid
        try:
            app._save_settings()
        except OSError as exc:
            app.shortcuts, app.solver_mode, app.placement_speed, app.target_pid = old
            self.hint.set("保存失败：请检查目录写入权限或磁盘空间。原配置保持不变。")
            app._append_log(f"设置保存失败：{exc}")
            return
        app._bind_shortcuts()
        app._refresh_shortcut_labels()
        app._append_log("研究配置已保存。")
        self.cancel()

    def cancel(self):
        self.closed = True
        if self.pending is not None:
            self.window.after_cancel(self.pending)
            self.pending = None
        self.window.destroy()
