"""Draft-based research preferences; only Save writes application settings."""
from __future__ import annotations

import queue
import threading
import tkinter as tk


class SettingsDialog:
    def __init__(self, app):
        self.app = app
        self.window = app.tk
        app.logbook._hide_tooltip()
        app.canvas.pack_forget()
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
        self.manual_open = bool(self.pid.get())
        self.process = tk.StringVar(self.window)
        self.shortcut_vars = {a: tk.StringVar(self.window, app._shortcut_display(v))
                              for a, v in self.shortcuts.items()}
        self.page = "研究策略"
        from .settings_book_view import SettingsBookView
        self.view = SettingsBookView(self)
        self.process_combo = self.view.process_combo
        self.traces = []
        for variable in (self.mode, self.pid, self.preset, self.hint):
            token = variable.trace_add("write", lambda *_: self.view.draw())
            self.traces.append((variable, token))
        self.show_page(self.page)
        self.view.canvas.focus_set()

    def show_page(self, title):
        self.capture_action = None
        self.page = title
        hints = {
            "研究策略": "推演受搜索预算限制，不保证全局最优。",
            "注入节律": "较慢的服务器建议使用稳定；极速可能增加校验失败。",
            "快捷符令": "Esc 取消绑定；重复键位会显示提示。",
            "世界连接": "手动选择仅本次运行有效，重启后自动检测。",
        }
        self.hint.set(hints[title])
        self.view.focus = title
        self.view.draw()

    def speed_changed(self):
        from .gui_app import PLACEMENT_SPEED_PRESETS
        if self.preset.get() != "custom":
            config = PLACEMENT_SPEED_PRESETS[self.preset.get()]
            self.delay.set(str(config["delayMs"]))
            self.verify.set(str(config["verifyDelayMs"]))
        self.view.draw()

    def toggle_manual(self):
        self.manual_open = not self.manual_open
        self.view.draw()
        if self.manual_open:
            self.view.fields["pid"].focus_set()

    def capture(self, action):
        self.capture_action = action
        self.hint.set("请按下新的快捷键；Esc 取消绑定。")
        self.view.canvas.focus_set()

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
        self.view.draw()
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
        self.view.draw()
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
        for variable, token in self.traces:
            variable.trace_remove("write", token)
        self.view.canvas.destroy()
        self.app.canvas.pack(fill="both", expand=True)
        self.app.logbook.draw()
        self.app.canvas.focus_set()
