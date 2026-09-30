from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Any, Callable

from .client_bridge import (
    DEFAULT_SOLVER_MODE,
    SOLVER_MODE_OPTIMAL,
    normalize_solver_mode,
)
from .knowledge_base import KnowledgeBase
from .overlay import BoardImageRenderer
from .paths import app_root, resource_path, resource_root, runtime_root
from .diagnostics import diagnose_error
from .persistence import atomic_write_json, read_settings_json
from .version import get_build_info, get_version_label


GITHUB_URL = "https://github.com/CaeliaEve/thaumcraft-nexus"
GITHUB_ICON = Path("image") / "icons8-github-50.png"
BACKGROUND_IMAGE = Path("image") / "thaumonomicon_bg_clean.png"
DEFAULT_SHORTCUTS = {
    "read": "<F5>",
    "apply": "<F6>",
    "wheelchair": "<F7>",
    "save": "<Control-s>",
}
DEFAULT_PLACEMENT_SPEED_PRESET = "balanced"
PLACEMENT_SPEED_PRESET_ORDER = ("stable", "balanced", "fast", "turbo", "custom")
PLACEMENT_SPEED_PRESETS = {
    "stable": {"label": "稳定", "delayMs": 120, "verifyDelayMs": 800},
    "balanced": {"label": "标准", "delayMs": 80, "verifyDelayMs": 500},
    "fast": {"label": "快速", "delayMs": 50, "verifyDelayMs": 300},
    "turbo": {"label": "极速", "delayMs": 30, "verifyDelayMs": 200},
    "custom": {"label": "自定义", "delayMs": 80, "verifyDelayMs": 500},
}
ACTION_LABELS = {
    "read": "解析研究笔记",
    "apply": "推演并注入要素",
    "wheelchair": "批量研习",
    "save": "誊录研究图谱",
}
ACTION_ORDER = ("read", "apply", "wheelchair", "save")


class ThaumNexusGui:
    """Natively rendered Thaumonomicon desktop GUI for structured research note solving."""

    def __init__(self, project_root: Path | str | None = None) -> None:
        self.bridge_project_root = Path(project_root).resolve() if project_root is not None else None
        self.project_root = app_root(self.bridge_project_root)
        self.resource_root = resource_root(self.bridge_project_root)
        self.runtime_root = runtime_root(self.bridge_project_root)
        self.kb = KnowledgeBase.load(self.resource_root)
        self.board_renderer = BoardImageRenderer(self.kb, project_root=self.resource_root, hex_size=34, icon_size=24)

        self.tk = None
        self.palette: dict[str, str] = {}
        self.canvas = None
        self.logbook = None
        self.log_lines: list[str] = []
        self.settings_warnings = []
        self.details_window = None
        self.details_text = None
        self.resources_window = None
        self.resource_preview = None
        self.status = None
        self.note_name = None
        self.placement_count = None
        self.worker_label = None
        self.buttons: dict[str, Any] = {}
        self.stop_button = None
        self.shortcut_bindings: list[str] = []
        self.canvas_shortcut_tag = f"ThaumNexusShortcuts:{id(self)}"
        self.canvas_shortcut_bindings: dict[str, str] = {}
        self.shortcuts = self._load_shortcuts()
        self.placement_speed = self._load_placement_speed()
        self.solver_mode = self._load_solver_mode()
        # A JVM PID is process-lifetime state: it changes every time the game restarts.
        # Keep manual PID selection for the current GUI session only, and never
        # resurrect a stale PID from gui_settings.json.
        self.target_pid = ""

        self.rendered = None
        self.solution_payload: dict[str, Any] | None = None
        self.solution_image_path: Path | None = None
        self.batch_total = 0

        self.worker_thread: threading.Thread | None = None
        self.worker_queue: queue.Queue[tuple[str, Any]] | None = None
        self.stop_event: threading.Event | None = None
        self.busy = False
        self.cancellable_busy = False
        self.closing = False
        self._worker_poll_job = None
        self._close_job = None

    def run(self) -> int:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk.Tk()
        self.tk.title("Thaumcraft Nexus")
        from .native_window import theme_window
        theme_window(self.tk)
        self.tk.geometry("1024x681")
        self.tk.minsize(1024, 681)

        self._configure_style(ttk)
        self._build_layout(tk, ttk)
        self._set_status("准备就绪。")
        self._append_log("准备就绪。")
        if self.settings_warnings:
            self._set_status(self.settings_warnings[0].title + "，已回退默认设置；请查看详情。")
            for warning in self.settings_warnings:
                self._append_log(warning.title + "：" + warning.advice + "\n" + warning.details)
        self.tk.mainloop()
        return 0

    def _configure_style(self, ttk: Any) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Thaumonomicon theme palette: Ancient parchment & dark blood leather
        self.palette = {
            "void": "#0E0907",
            "panel": "#1B1310",
            "raised": "#2A1D18",
            "hover": "#3D2821",
            "hairline": "#4A3229",
            "text": "#D6C6B0",
            "muted": "#9E8876",
            "faint": "#695546",
            "accent": "#C93636",
            "accent_dim": "#7A1F1F",
            "accent_bright": "#F54545",
            "danger": "#B83B28",
            "danger_dim": "#5E1D13",
            "canvas": "#140D0A",
            "log_fg": "#BAA793",
            "status_fg": "#C4B29E",
        }
        pal = self.palette

        # Dropdown listboxes option database
        self.tk.option_add("*TCombobox*Listbox.background", pal["raised"])
        self.tk.option_add("*TCombobox*Listbox.foreground", pal["text"])
        self.tk.option_add("*TCombobox*Listbox.selectBackground", pal["accent_dim"])
        self.tk.option_add("*TCombobox*Listbox.selectForeground", pal["text"])
        self.tk.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))

        style.configure(".", font=("Segoe UI", 10), foreground=pal["text"])
        style.configure("TFrame", background=pal["void"])
        style.configure("Panel.TFrame", background=pal["panel"])
        style.configure("Card.TFrame", background=pal["raised"], borderwidth=1, relief="solid", bordercolor=pal["hairline"])
        style.configure("Divider.TFrame", background=pal["hairline"])

        style.configure("AppTitle.TLabel", background=pal["panel"], foreground=pal["accent"], font=("Georgia", 15, "bold"))
        style.configure("AppSubtitle.TLabel", background=pal["panel"], foreground=pal["muted"], font=("Georgia", 10))
        style.configure("SectionTitle.TLabel", background=pal["panel"], foreground=pal["text"], font=("Segoe UI", 10, "bold"))
        style.configure("Muted.TLabel", background=pal["panel"], foreground=pal["muted"])
        style.configure("Link.TLabel", background=pal["panel"], foreground=pal["accent"], font=("Georgia", 10))
        style.configure("Status.TLabel", background=pal["void"], foreground=pal["status_fg"])

        style.configure("CardTitle.TLabel", background=pal["raised"], foreground=pal["muted"], font=("Segoe UI", 9, "bold"))
        style.configure("Card.TLabel", background=pal["raised"], foreground=pal["text"], font=("Segoe UI", 10))
        style.configure("CardMuted.TLabel", background=pal["raised"], foreground=pal["muted"], font=("Segoe UI", 10))

        style.configure("TButton",
                        background=pal["raised"],
                        foreground=pal["text"],
                        bordercolor=pal["hairline"],
                        darkcolor=pal["raised"],
                        lightcolor=pal["raised"],
                        focuscolor=pal["accent_dim"],
                        borderwidth=1,
                        anchor="center",
                        padding=(10, 6),
                        font=("Segoe UI", 10))
        style.map("TButton",
                  background=[("active", pal["hover"]), ("disabled", pal["panel"])],
                  foreground=[("active", pal["accent_bright"]), ("disabled", pal["faint"])],
                  bordercolor=[("active", pal["accent_dim"]), ("disabled", pal["hairline"])])

        style.configure("Primary.TButton",
                        background=pal["accent_dim"],
                        foreground="#FFFFFF",
                        bordercolor=pal["accent"],
                        darkcolor=pal["accent_dim"],
                        lightcolor=pal["accent_dim"],
                        focuscolor=pal["accent"],
                        borderwidth=1,
                        anchor="center",
                        padding=(10, 6),
                        font=("Segoe UI", 10, "bold"))
        style.map("Primary.TButton",
                  background=[("active", pal["accent"]), ("disabled", pal["panel"])],
                  foreground=[("disabled", pal["faint"])],
                  bordercolor=[("active", pal["accent_bright"]), ("disabled", pal["hairline"])])

        style.configure("Danger.TButton",
                        background=pal["panel"],
                        foreground=pal["danger"],
                        bordercolor=pal["danger_dim"],
                        darkcolor=pal["panel"],
                        lightcolor=pal["panel"],
                        focuscolor=pal["danger_dim"],
                        borderwidth=1,
                        anchor="center",
                        padding=(10, 6),
                        font=("Segoe UI", 10))
        style.map("Danger.TButton",
                  background=[("active", pal["danger_dim"]), ("disabled", pal["panel"])],
                  foreground=[("disabled", pal["faint"])],
                  bordercolor=[("active", pal["danger"]), ("disabled", pal["hairline"])])

        style.configure("TCombobox",
                        fieldbackground=pal["raised"],
                        background=pal["panel"],
                        foreground=pal["text"],
                        bordercolor=pal["hairline"],
                        darkcolor=pal["raised"],
                        lightcolor=pal["raised"],
                        arrowcolor=pal["muted"],
                        arrowsize=12,
                        padding=5)
        style.map("TCombobox",
                  fieldbackground=[("readonly", pal["raised"]), ("active", pal["hover"])],
                  bordercolor=[("focus", pal["accent_dim"]), ("active", pal["hairline"])])

        style.configure("TEntry",
                        fieldbackground=pal["raised"],
                        foreground=pal["text"],
                        bordercolor=pal["hairline"],
                        lightcolor=pal["raised"],
                        darkcolor=pal["raised"],
                        insertcolor=pal["accent"],
                        padding=6)
        style.map("TEntry", bordercolor=[("focus", pal["accent_dim"]), ("active", pal["hairline"])])

        style.configure("TCheckbutton",
                        background=pal["panel"],
                        foreground=pal["text"],
                        focuscolor=pal["panel"],
                        font=("Segoe UI", 10))
        style.map("TCheckbutton",
                  background=[("active", pal["panel"])],
                  foreground=[("disabled", pal["faint"])])

        style.configure("Horizontal.TProgressbar",
                        troughcolor=pal["raised"],
                        bordercolor=pal["panel"],
                        background=pal["accent"],
                        lightcolor=pal["accent"],
                        darkcolor=pal["accent"],
                        thickness=4)

    def _build_layout(self, tk: Any, ttk: Any) -> None:
        from .logbook_view import LogbookView

        assert self.tk is not None
        self.tk.protocol("WM_DELETE_WINDOW", self._request_close)
        self.tk.configure(bg="#090705")
        self.note_name = tk.StringVar(master=self.tk, value="笔记：—")
        self.placement_count = tk.StringVar(master=self.tk, value="放置：—")
        self.worker_label = tk.StringVar(master=self.tk, value="状态：空闲")
        self.status = tk.StringVar(master=self.tk, value="准备就绪")
        callbacks = [self._read_current_note, self._read_and_apply_current_note,
                     self._wheelchair_apply_notes, self._save_solution]
        actions = [(key, ACTION_LABELS[key], self._shortcut_display(self.shortcuts[key]), callback)
                   for key, callback in zip(ACTION_ORDER, callbacks)]
        actions += [("settings", "研究配置", "", self._open_settings),
                    ("stop", "中止推演", "", self._stop_current_task)]
        self.logbook = LogbookView(self.tk, resource_path(BACKGROUND_IMAGE, self.resource_root),
                                   actions, self._show_details, self._open_github, self._show_resources)
        self.canvas = self.logbook.canvas
        self.buttons = {key: action for key, action in self.logbook.actions.items() if key != "stop"}
        self.stop_button = self.logbook.actions["stop"]
        self.stop_button.configure(state="disabled")
        self.buttons["save"].configure(state="disabled")
        for variable in (self.note_name, self.placement_count, self.worker_label, self.status):
            variable.trace_add("write", lambda *_: self._update_canvas_status_texts())
        self._bind_shortcuts()

    def _update_canvas_status_texts(self) -> None:
        if self.logbook is not None:
            self.logbook.update_status(
                note=self.note_name.get().removeprefix("笔记："),
                placements=self.placement_count.get().removeprefix("放置："),
                worker=self.worker_label.get().removeprefix("状态："),
                status=self.status.get(),
            )
        self._refresh_details()

    def _open_github(self) -> None:
        import webbrowser
        webbrowser.open_new_tab(GITHUB_URL)

    def _show_details(self) -> None:
        import tkinter as tk
        from tkinter import scrolledtext
        if self.details_window is not None and self.details_window.winfo_exists():
            self._refresh_details()
            self.details_window.lift()
            return
        dialog = tk.Toplevel(self.tk)
        self.details_window = dialog
        dialog.title("研究记录 · 任务详情")
        dialog.geometry("620x380")
        dialog.minsize(460, 260)
        dialog.transient(self.tk)
        from .native_window import theme_window
        theme_window(dialog)
        text = scrolledtext.ScrolledText(dialog, bg="#211710", fg="#dbc8a8", insertbackground="#dbc8a8",
                                        wrap="word", font=("Microsoft YaHei", 10), padx=18, pady=16)
        text.pack(fill="both", expand=True)
        self.details_text = text
        self._refresh_details()
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

    def _refresh_details(self) -> None:
        text = self.details_text
        if text is None or not text.winfo_exists():
            return
        top, bottom = text.yview()
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("1.0", "版本：" + get_version_label(self.resource_root) + "\n当前笔记：" + self.logbook.note + "\n\n" + self.status.get() +
                    "\n\n" + "\n".join(self.log_lines))
        text.configure(state="disabled")
        if bottom >= 1.0:
            text.see("end")
        else:
            text.yview_moveto(top)

    def _show_resources(self) -> None:
        import tkinter as tk
        from tkinter import ttk, scrolledtext
        if self.resource_preview is None:
            return
        if self.resources_window is not None and self.resources_window.winfo_exists():
            self.resources_window.destroy()
        dialog = tk.Toplevel(self.tk)
        self.resources_window = dialog
        dialog.title("资源计划 · " + self.logbook.note)
        dialog.geometry("700x480")
        dialog.minsize(560, 360)
        dialog.transient(self.tk)
        from .native_window import theme_window
        theme_window(dialog)
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="\n".join(self.resource_preview.summary)).pack(anchor="w", pady=(0, 12))
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True)
        columns = ("name", "required", "available", "synthesis", "shortage")
        table = ttk.Treeview(table_frame, columns=columns, show="headings", height=7)
        for key, label in zip(columns, ("要素", "放置需求", "读取时库存", "预计合成", "阻塞缺口")):
            table.heading(key, text=label)
            table.column(key, width=190 if key == "name" else 90, minwidth=65, anchor="w" if key == "name" else "center")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        table.pack(fill="both", expand=True)
        for row in self.resource_preview.rows:
            table.insert("", "end", values=(f"{row.name} ({row.key})", row.required, row.available, row.synthesis, row.shortage),
                         tags=("shortage",) if row.shortage else ())
        table.tag_configure("shortage", foreground="#9b241c")
        details = scrolledtext.ScrolledText(frame, height=7, wrap="word", font=("Microsoft YaHei", 10))
        details.pack(fill="both", expand=True, pady=(12, 0))
        details.insert("1.0", self.resource_preview.details)
        details.configure(state="disabled")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

    def _button_text(self, action: str) -> str:
        shortcut = self._shortcut_display(self.shortcuts.get(action, ""))
        return f"{ACTION_LABELS[action]}  {shortcut}" if shortcut else ACTION_LABELS[action]

    def _settings_path(self) -> Path:
        return self.runtime_root / "gui_settings.json"

    def _load_settings_payload(self) -> dict[str, Any]:
        payload, warning = read_settings_json(self._settings_path())
        if warning is not None and warning not in self.settings_warnings:
            self.settings_warnings.append(warning)
        return payload

    def _load_shortcuts(self) -> dict[str, str]:
        shortcuts = dict(DEFAULT_SHORTCUTS)
        payload = self._load_settings_payload()
        saved = payload.get("shortcuts") if isinstance(payload, dict) else None
        if not isinstance(saved, dict):
            return shortcuts
        for action in ACTION_ORDER:
            value = saved.get(action)
            if isinstance(value, str) and value.startswith("<") and value.endswith(">"):
                shortcuts[action] = value
        return shortcuts

    def _load_placement_speed(self) -> dict[str, int | str]:
        payload = self._load_settings_payload()
        saved = payload.get("placementSpeed") if isinstance(payload, dict) else None
        return self._normalize_placement_speed(saved)

    def _load_solver_mode(self) -> str:
        payload = self._load_settings_payload()
        return normalize_solver_mode(payload.get("solverMode"))

    def _solver_mode_summary(self) -> str:
        if self.solver_mode == SOLVER_MODE_OPTIMAL:
            return "最少要素优先（缺少时递归合成）"
        return "库存优先（优先使用数量充足的现有要素）"

    def _normalize_placement_speed(self, payload: Any) -> dict[str, int | str]:
        default = PLACEMENT_SPEED_PRESETS[DEFAULT_PLACEMENT_SPEED_PRESET]
        preset = DEFAULT_PLACEMENT_SPEED_PRESET
        delay_ms = int(default["delayMs"])
        verify_delay_ms = int(default["verifyDelayMs"])

        if isinstance(payload, dict):
            raw_preset = payload.get("preset")
            if isinstance(raw_preset, str) and raw_preset in PLACEMENT_SPEED_PRESETS:
                preset = raw_preset
            if preset == "custom":
                delay_ms = self._coerce_speed_ms(payload.get("delayMs"), delay_ms)
                verify_delay_ms = self._coerce_speed_ms(payload.get("verifyDelayMs"), verify_delay_ms)
            else:
                selected = PLACEMENT_SPEED_PRESETS[preset]
                delay_ms = int(selected["delayMs"])
                verify_delay_ms = int(selected["verifyDelayMs"])

        return {"preset": preset, "delayMs": delay_ms, "verifyDelayMs": verify_delay_ms}

    def _coerce_speed_ms(self, value: Any, fallback: int) -> int:
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            return fallback
        return max(0, min(5000, number))

    def _placement_speed_values(self) -> tuple[int, int]:
        speed = self._normalize_placement_speed(self.placement_speed)
        self.placement_speed = speed
        return int(speed["delayMs"]), int(speed["verifyDelayMs"])

    def _placement_speed_summary(self) -> str:
        speed = self._normalize_placement_speed(self.placement_speed)
        preset = str(speed["preset"])
        label = str(PLACEMENT_SPEED_PRESETS.get(preset, PLACEMENT_SPEED_PRESETS["custom"])["label"])
        return f"{label}（间隔 {int(speed['delayMs'])}ms，完成等待 {int(speed['verifyDelayMs'])}ms）"

    def _speed_preset_display(self, preset: str) -> str:
        config = PLACEMENT_SPEED_PRESETS[preset]
        if preset == "custom":
            return str(config["label"])
        return f"{config['label']}（{config['delayMs']} / {config['verifyDelayMs']} ms）"

    def _speed_preset_from_display(self, display: str) -> str:
        for preset in PLACEMENT_SPEED_PRESET_ORDER:
            if display == self._speed_preset_display(preset):
                return preset
        return "custom"

    def _load_target_pid(self) -> str:
        payload = self._load_settings_payload()
        value = payload.get("targetPid")
        return value.strip() if isinstance(value, str) else ""

    def _save_settings(self) -> None:
        path = self._settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "thaumcraft-nexus/gui-settings/v1",
            "shortcuts": {action: self.shortcuts[action] for action in ACTION_ORDER},
            "placementSpeed": self._normalize_placement_speed(self.placement_speed),
            "solverMode": normalize_solver_mode(self.solver_mode),
            "targetPid": "",
        }
        atomic_write_json(path, payload)

    def _save_shortcuts(self) -> None:
        self._save_settings()

    def _bridge_pid(self) -> str | None:
        pid = self.target_pid.strip()
        return pid or None

    def _bind_shortcuts(self) -> None:
        if self.tk is None:
            return
        for sequence, command_id in self.canvas_shortcut_bindings.items():
            self.tk.unbind_class(self.canvas_shortcut_tag, sequence)
            self.tk.deletecommand(command_id)
        self.canvas_shortcut_bindings.clear()
        if self.canvas is not None:
            tags = self.canvas.bindtags()
            if self.canvas_shortcut_tag not in tags:
                self.canvas.bindtags((self.canvas_shortcut_tag, *tags))
        for sequence in self.shortcut_bindings:
            try:
                self.tk.unbind(sequence)
            except Exception:
                pass
        self.shortcut_bindings = []
        for action in ACTION_ORDER:
            sequence = self.shortcuts.get(action)
            if not sequence:
                continue
            self.tk.bind(sequence, lambda _event, key=action: self._invoke_action(key))
            if self.canvas is not None:
                command_id = self.tk.bind_class(
                    self.canvas_shortcut_tag, sequence,
                    lambda _event, key=action: self._invoke_action(key),
                )
                self.canvas_shortcut_bindings[sequence] = command_id
            self.shortcut_bindings.append(sequence)

    def _invoke_action(self, action: str) -> str:
        editor = getattr(self, "settings_editor", None)
        if editor is not None and not editor.closed:
            return "break"
        button = self.buttons.get(action)
        if button is not None:
            button.invoke()
        return "break"

    def _refresh_shortcut_labels(self) -> None:
        for action in ACTION_ORDER:
            button = self.buttons.get(action)
            if button is not None and hasattr(button, "set_shortcut_text"):
                button.set_shortcut_text(self._shortcut_display(self.shortcuts.get(action, "")))

    def _shortcut_display(self, sequence: str) -> str:
        if not sequence:
            return ""
        text = sequence.strip("<>")
        text = text.replace("Control", "Ctrl")
        text = text.replace("-", "+")
        return text

    def _event_to_shortcut(self, event: Any) -> str | None:
        key = str(getattr(event, "keysym", "") or "")
        if not key or key in {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"}:
            return None
        modifiers: list[str] = []
        state = int(getattr(event, "state", 0) or 0)
        if state & 0x0004:
            modifiers.append("Control")
        if state & 0x0008 or state & 0x0080:
            modifiers.append("Alt")
        if state & 0x0001 and not key.startswith("F"):
            modifiers.append("Shift")
        if len(key) == 1:
            key = key.lower()
        return "<" + "-".join(modifiers + [key]) + ">"

    def _open_settings(self) -> None:
        if self.tk is None:
            return
        from .settings_dialog import SettingsDialog
        editor = getattr(self, "settings_editor", None)
        if editor is not None and not editor.closed:
            editor.view.canvas.focus_set()
            return
        self.settings_editor = SettingsDialog(self)

    def _read_current_note(self) -> None:
        if self.busy:
            self._set_status("已有任务在运行，请先等待或停止当前任务。")
            return

        def task(stop_event: threading.Event, emit: Callable[[str, Any], None]) -> dict[str, Any]:
            from .client_bridge import read_and_solve_current_note

            emit("log", "读取当前研究台笔记……")
            pid = self._bridge_pid()
            if pid:
                emit("log", f"使用目标 JVM PID：{pid}")
            solve_mode = normalize_solver_mode(self.solver_mode)
            emit("log", f"求解策略：{self._solver_mode_summary()}")
            result = read_and_solve_current_note(
                self.bridge_project_root,
                pid=pid,
                stop_event=stop_event,
                solve_mode=solve_mode,
            )
            return {"kind": "read", "result": result}

        self._start_worker("\u8bfb\u53d6\u5f53\u524d\u7b14\u8bb0", task, cancellable=True)

    def _read_and_apply_current_note(self) -> None:
        if self.busy:
            self._set_status("已有任务在运行，请先等待或停止当前任务。")
            return

        def task(stop_event: threading.Event, emit: Callable[[str, Any], None]) -> dict[str, Any]:
            from .client_bridge import read_solve_and_apply_current_note

            emit("log", "读取、求解并自动放置当前笔记……")
            pid = self._bridge_pid()
            if pid:
                emit("log", f"使用目标 JVM PID：{pid}")
            delay_ms, verify_delay_ms = self._placement_speed_values()
            solve_mode = normalize_solver_mode(self.solver_mode)
            emit("log", f"求解策略：{self._solver_mode_summary()}")
            emit("log", f"摆放速度：{self._placement_speed_summary()}")
            result = read_solve_and_apply_current_note(
                self.bridge_project_root,
                pid=pid,
                delay_ms=delay_ms,
                verify_delay_ms=verify_delay_ms,
                stop_event=stop_event,
                solve_mode=solve_mode,
            )
            return {"kind": "apply", "result": result}

        self._start_worker("\u81ea\u52a8\u653e\u7f6e\u5f53\u524d\u7b14\u8bb0", task, cancellable=True)

    def _wheelchair_apply_notes(self) -> None:
        if self.busy:
            self._set_status("已有任务在运行，请先等待或停止当前任务。")
            return

        def task(stop_event: threading.Event, emit: Callable[[str, Any], None]) -> dict[str, Any]:
            from .client_bridge import solve_all_inventory_notes

            def progress(payload: dict[str, Any]) -> None:
                emit("progress", payload)

            emit("log", "轮椅模式启动：开始扫描背包未解笔记。")
            pid = self._bridge_pid()
            if pid:
                emit("log", f"使用目标 JVM PID：{pid}")
            delay_ms, verify_delay_ms = self._placement_speed_values()
            solve_mode = normalize_solver_mode(self.solver_mode)
            emit("log", f"求解策略：{self._solver_mode_summary()}")
            emit("log", f"摆放速度：{self._placement_speed_summary()}")
            payload = solve_all_inventory_notes(
                self.bridge_project_root,
                pid=pid,
                apply=True,
                delay_ms=delay_ms,
                verify_delay_ms=verify_delay_ms,
                stop_event=stop_event,
                progress_callback=progress,
                solve_mode=solve_mode,
            )
            result_json = self._write_runtime_json("wheelchair_result.json", payload)
            return {"kind": "wheelchair", "payload": payload, "resultJson": result_json}

        self._start_worker("\u8f6e\u6905\u6a21\u5f0f\u8fd0\u884c\u4e2d", task, cancellable=True)

    def _start_worker(
        self,
        label: str,
        task: Callable[[threading.Event, Callable[[str, Any], None]], dict[str, Any]],
        *,
        cancellable: bool,
    ) -> None:
        assert self.tk is not None
        if self.busy or self.closing or (self.worker_thread is not None and self.worker_thread.is_alive()):
            return
        if self.resources_window is not None and self.resources_window.winfo_exists():
            self.resources_window.destroy()
            self.resources_window = None
        worker_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        stop_event = threading.Event()
        self.worker_queue = worker_queue
        self.batch_total = 0
        self.stop_event = stop_event
        self.busy = True
        self.cancellable_busy = cancellable
        self._set_busy_ui(label, cancellable=cancellable)
        self._set_status(f"{label}……")
        self._append_log(f"开始：{label}")

        def emit(kind: str, payload: Any) -> None:
            worker_queue.put((kind, payload))

        def runner() -> None:
            try:
                payload = task(stop_event, emit)
                emit("done", payload)
            except Exception as exc:
                emit("error", exc)

        self.worker_thread = threading.Thread(target=runner, name="ThaumNexusGuiWorker", daemon=True)
        self.worker_thread.start()
        self._worker_poll_job = self.tk.after(80, self._poll_worker_queue)

    def _poll_worker_queue(self) -> None:
        if self._worker_poll_job is not None and self.tk is not None:
            self.tk.after_cancel(self._worker_poll_job)
            self._worker_poll_job = None
        if self.worker_queue is None:
            return
        while True:
            try:
                kind, payload = self.worker_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._append_log(str(payload))
                self._set_status(str(payload))
            elif kind == "progress":
                if "unsolvedCount" in payload:
                    self.batch_total = int(payload["unsolvedCount"])
                if payload.get("event") == "inventory-final-scan" and self.worker_label is not None:
                    self.worker_label.set("状态：正在确认背包")
                elif "iteration" in payload and self.worker_label is not None:
                    index = int(payload["iteration"]) + 1
                    total = f" / {self.batch_total}" if self.batch_total else ""
                    self.worker_label.set(f"状态：第 {index}{total} 张")
                if payload.get("researchKey") and self.note_name is not None:
                    self.note_name.set(f"笔记：{payload['researchKey']}")
                message = str(payload.get("message") or payload.get("event") or "轮椅模式进度更新")
                self._append_log(message)
                self._set_status(message)
            elif kind == "done":
                try:
                    self._handle_worker_done(payload)
                except Exception as exc:
                    self._handle_worker_error(exc)
            elif kind == "error":
                self._handle_worker_error(payload)

        if self.busy and self.tk is not None:
            self._worker_poll_job = self.tk.after(120, self._poll_worker_queue)

    def _request_close(self) -> None:
        if self.closing or self.tk is None:
            return
        self.closing = True
        if self.stop_event is not None:
            self.stop_event.set()
        for button in self.buttons.values():
            button.configure(state="disabled")
        if self.stop_button is not None:
            self.stop_button.configure(state="disabled")
        self._set_status("正在停止任务，确认结束后关闭窗口……")
        self._poll_close()

    def _poll_close(self) -> None:
        self._close_job = None
        if not self.closing or self.tk is None:
            return
        if self.worker_thread is not None and self.worker_thread.is_alive():
            self._close_job = self.tk.after(80, self._poll_close)
            return
        self._poll_worker_queue()
        if not self.closing:
            return  # An unconfirmed Java mutation needs to remain visible.
        if self._worker_poll_job is not None:
            self.tk.after_cancel(self._worker_poll_job)
            self._worker_poll_job = None
        self.tk.destroy()
        self.tk = None

    def _handle_worker_done(self, payload: dict[str, Any]) -> None:
        kind = payload.get("kind")
        try:
            if kind == "read":
                result = payload["result"]
                data = result.to_dict()
                self._show_solution(
                    board=result.note.board,
                    solution=result.solution,
                    note_label=result.note.research_key or result.note.board.name,
                    payload=data,
                )
                self._set_status(f"读取完成：需要放置 {len(result.solution.placements)} 个要素。文件：{self.solution_image_path}")
                self._append_log("读取完成。")
            elif kind == "apply":
                result = payload["result"]
                data = result.to_dict()
                self._show_solution(
                    board=result.current.note.board,
                    solution=result.current.solution,
                    note_label=result.current.note.research_key or result.current.note.board.name,
                    payload=data,
                )
                sent = int(result.apply_payload.get("placementsSent", 0))
                skipped = int(result.apply_payload.get("placementsSkipped", 0))
                combines = int(result.apply_payload.get("combinesSent", 0))
                self._set_status(f"自动放置完成：合成 {combines} 次，放置 {sent} 个，跳过 {skipped} 个。")
                self._append_log("自动放置完成。")
            elif kind == "wheelchair":
                batch = payload["payload"]
                result_json = payload["resultJson"]
                status = str(batch.get("status") or "ok")
                solved = int(batch.get("solvedOrAttempted", 0) or 0)
                message = str(batch.get("message") or "轮椅模式结束")
                self._set_status(f"轮椅模式{self._status_cn(status)}：尝试处理 {solved} 张。{message} 文件：{result_json}")
                self._append_log(f"轮椅模式结束：{message}")
                if self.logbook:
                    page = "success" if status == "ok" else ("cancelled" if status == "cancelled" else "error")
                    self.logbook.preview = None
                    self.logbook.set_page(page, f"已处理 {solved} 张。{message}")
            else:
                self._set_status("任务完成。")
        finally:
            self._finish_worker_ui()

    def _handle_worker_error(self, exc: Exception) -> None:
        from .client_bridge import OperationCancelled, UnsafeAgentStateError

        if isinstance(exc, OperationCancelled):
            if self.logbook:
                self.logbook.set_page("cancelled", "已停止当前操作，可以重新读取笔记。")
            self._set_status("任务已停止。")
            self._append_log("任务已停止。")
            self._finish_worker_ui()
            return

        diagnostic = diagnose_error(exc)
        if isinstance(exc, UnsafeAgentStateError):
            self.closing = False
        if self.logbook:
            self.logbook.set_page("error", diagnostic.title + "\n" + diagnostic.advice)
        self._set_status(f"任务失败：{diagnostic.title}")
        self._append_log(f"{diagnostic.title}：{diagnostic.advice}\n{diagnostic.details}")
        try:
            error_text, error_json = self._write_error_report(exc)
            self._append_log(f"完整错误已写入：{error_text}")
            self._append_log(f"诊断 JSON：{error_json}")
        except OSError as report_error:
            self._append_log(f"诊断文件未能保存，原始错误保留在本窗口：{report_error}")
        self._finish_worker_ui()

    def _stop_current_task(self) -> None:
        if not self.busy or self.stop_event is None:
            return
        self.stop_event.set()
        self._set_status("正在停止，等待当前操作确认……")
        self._append_log("已发送立即停止请求。")
        if self.stop_button is not None:
            self.stop_button.configure(state="disabled")

    def _set_busy_ui(self, label: str, *, cancellable: bool) -> None:
        for key, button in self.buttons.items():
            button.configure(state="normal" if key == "save" and self.rendered is not None else "disabled")
        if self.stop_button is not None:
            self.stop_button.configure(state="normal" if cancellable else "disabled")
        if self.worker_label is not None:
            self.worker_label.set(f"状态：{label}")
        if self.logbook:
            self.logbook.set_page("busy", label)

    def _finish_worker_ui(self) -> None:
        self.busy = False
        self.cancellable_busy = False
        for key, button in self.buttons.items():
            button.configure(state="disabled" if self.closing or (key == "save" and self.rendered is None) else "normal")
        if self.stop_button is not None:
            self.stop_button.configure(state="disabled")
        if self.worker_label is not None:
            state = self.logbook.state if self.logbook else "idle"
            label = {"success": "完成", "error": "失败", "cancelled": "已停止"}.get(state, "空闲")
            self.worker_label.set(f"状态：{label}")

    def _show_solution(self, *, board: Any, solution: Any, note_label: str, payload: dict[str, Any]) -> None:
        from .resource_preview import describe_resources
        self.rendered = self.board_renderer.render(board, solution)
        out_dir = self.runtime_root
        out_dir.mkdir(parents=True, exist_ok=True)
        self.solution_image_path = out_dir / "current_solution.png"
        self.rendered.save(self.solution_image_path)
        solution_json = out_dir / "current_solution.json"
        atomic_write_json(solution_json, payload)
        self.solution_payload = payload
        self.resource_preview = describe_resources(self.kb, payload)
        if self.note_name is not None:
            self.note_name.set(f"笔记：{note_label}")
        if self.placement_count is not None:
            self.placement_count.set(f"放置：{len(solution.placements)}")
        if self.logbook:
            self.logbook.resource_summary = self.resource_preview.summary
            self.logbook.preview_regions = self.board_renderer.describe_cells(board, solution)
            self.logbook.set_page("success", preview=self.board_renderer.render(board, solution, paper=True))
        if self.resources_window is not None and self.resources_window.winfo_exists():
            self._show_resources()
        self.buttons["save"].configure(state="normal")

    def _save_solution(self) -> None:
        from tkinter import filedialog

        if self.rendered is None:
            self._set_status("还没有答案图。请先解析研究笔记。")
            return
        default = "current_solution.png"
        if self.solution_image_path is not None:
            default = self.solution_image_path.name
        path = filedialog.asksaveasfilename(
            title="誊录研究图谱",
            initialfile=default,
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("All files", "*.*")],
        )
        if not path:
            return
        self.rendered.save(path)
        self._set_status(f"答案图已保存：{path}")
        self._append_log(f"答案图已保存：{path}")

    def _write_runtime_json(self, name: str, payload: dict[str, Any]) -> Path:
        out_dir = self.runtime_root
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / name
        atomic_write_json(path, payload)
        return path

    def _write_error_report(self, exc: Exception) -> tuple[Path, Path]:
        diagnostic = diagnose_error(exc)
        payload = {
            "source": "thaum-nexus-gui",
            "status": "error",
            "action": "gui-worker",
            "errorType": type(exc).__name__,
            "error": str(exc),
            "code": diagnostic.code,
            "advice": diagnostic.advice,
            "details": diagnostic.details,
            "build": get_build_info(self.resource_root),
        }
        error_json = self._write_runtime_json("gui_last_error.json", payload)
        error_text = self.runtime_root / "gui_last_error.txt"
        error_text.parent.mkdir(parents=True, exist_ok=True)
        error_text.write_text(diagnostic.title + "\n" + diagnostic.advice + "\n\n" + diagnostic.details + "\n", encoding="utf-8")
        return error_text, error_json

    def _set_status(self, text: str) -> None:
        if self.status is not None:
            self.status.set(text)

    def _append_log(self, text: str) -> None:
        self.log_lines.append(text)
        self.log_lines = self.log_lines[-200:]
        self._refresh_details()

    def _status_cn(self, status: str) -> str:
        return {"ok": "完成", "cancelled": "已停止", "incomplete": "未完全完成", "error": "失败"}.get(status, "结束")

    def _short_error(self, exc: Exception) -> str:
        message = str(exc).strip().replace("\r", "\n")
        first_line = next((line.strip() for line in message.splitlines() if line.strip()), type(exc).__name__)
        if len(first_line) > 180:
            first_line = first_line[:177] + "..."
        return first_line


def main() -> int:
    return ThaumNexusGui().run()


if __name__ == "__main__":
    raise SystemExit(main())
