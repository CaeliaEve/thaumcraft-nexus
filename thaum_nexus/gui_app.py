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
    "read": "读取当前笔记",
    "apply": "读取并自动放置",
    "wheelchair": "轮椅模式 · 解完背包笔记",
    "save": "保存答案图",
}
ACTION_ORDER = ("read", "apply", "wheelchair", "save")


class ThaumNexusGui:
    """Natively rendered Thaumonomicon desktop GUI for structured research note solving."""
    # UI text markers: 读取当前笔记 / 读取并自动放置 / 轮椅模式 / 停止当前任务

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
        self.details_window = None
        self.details_text = None
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

    def run(self) -> int:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk.Tk()
        self.tk.title("Thaumcraft Nexus")
        self.tk.geometry("1024x681")
        self.tk.minsize(1024, 681)

        self._configure_style(ttk)
        self._build_layout(tk, ttk)
        self._set_status("准备就绪。")
        self._append_log("准备就绪。")
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
        self.tk.configure(bg="#090705")
        self.note_name = tk.StringVar(master=self.tk, value="笔记：—")
        self.placement_count = tk.StringVar(master=self.tk, value="放置：—")
        self.worker_label = tk.StringVar(master=self.tk, value="状态：空闲")
        self.status = tk.StringVar(master=self.tk, value="准备就绪")
        callbacks = [self._read_current_note, self._read_and_apply_current_note,
                     self._wheelchair_apply_notes, self._save_solution]
        actions = [(key, ACTION_LABELS[key], self._shortcut_display(self.shortcuts[key]), callback)
                   for key, callback in zip(ACTION_ORDER, callbacks)]
        actions += [("settings", "设置", "", self._open_settings),
                    ("stop", "停止当前任务", "", self._stop_current_task)]
        self.logbook = LogbookView(self.tk, resource_path(BACKGROUND_IMAGE, self.resource_root),
                                   actions, self._show_details, self._open_github)
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
        text.insert("1.0", "当前笔记：" + self.logbook.note + "\n\n" + self.status.get() +
                    "\n\n" + "\n".join(self.log_lines))
        text.configure(state="disabled")
        if bottom >= 1.0:
            text.see("end")
        else:
            text.yview_moveto(top)

    def _button_text(self, action: str) -> str:
        shortcut = self._shortcut_display(self.shortcuts.get(action, ""))
        return f"{ACTION_LABELS[action]}  {shortcut}" if shortcut else ACTION_LABELS[action]

    def _settings_path(self) -> Path:
        return self.runtime_root / "gui_settings.json"

    def _load_settings_payload(self) -> dict[str, Any]:
        path = self._settings_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

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
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
        import tkinter as tk
        from tkinter import ttk

        dialog = tk.Toplevel(self.tk)
        dialog.title("设置")
        dialog.configure(bg=self.palette["panel"])
        dialog.resizable(False, False)
        dialog.transient(self.tk)
        dialog.grab_set()

        container = ttk.Frame(dialog, style="Panel.TFrame", padding=18)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="快捷键设置", style="SectionTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        hint = tk.StringVar(value="点击“重新绑定”，然后按下新的快捷键。")
        ttk.Label(container, textvariable=hint, style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 12))

        value_vars: dict[str, Any] = {}
        row = 2
        for action in ACTION_ORDER:
            ttk.Label(container, text=ACTION_LABELS[action], style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=5)
            value_vars[action] = tk.StringVar(value=self._shortcut_display(self.shortcuts[action]))
            ttk.Label(container, textvariable=value_vars[action], style="Muted.TLabel", width=16).grid(row=row, column=1, sticky="w", padx=(16, 12))
            ttk.Button(
                container,
                text="重新绑定",
                command=lambda a=action: self._capture_shortcut(dialog, hint, value_vars, a),
            ).grid(row=row, column=2, sticky="e", pady=5)
            row += 1

        speed_settings = self._normalize_placement_speed(self.placement_speed)
        speed_preset_values = [self._speed_preset_display(preset) for preset in PLACEMENT_SPEED_PRESET_ORDER]
        speed_preset_var = tk.StringVar(value=self._speed_preset_display(str(speed_settings["preset"])))
        speed_delay_var = tk.StringVar(value=str(speed_settings["delayMs"]))
        speed_verify_var = tk.StringVar(value=str(speed_settings["verifyDelayMs"]))
        row += 1
        ttk.Label(container, text="摆放速度", style="SectionTitle.TLabel").grid(
            row=row,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(12, 8),
        )
        row += 1
        ttk.Label(
            container,
            text="预设会同时调整每个要素之间的间隔和每张笔记完成后的等待；服务器较慢时请使用稳定预设。",
            style="Muted.TLabel",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row += 1
        ttk.Label(container, text="预设", style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=5)
        speed_combo = ttk.Combobox(container, textvariable=speed_preset_var, width=22, state="readonly", values=speed_preset_values)
        speed_combo.grid(row=row, column=1, sticky="w", padx=(16, 12), pady=5)
        row += 1
        ttk.Label(container, text="要素间隔 ms", style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=5)
        speed_delay_entry = ttk.Entry(container, textvariable=speed_delay_var, width=18)
        speed_delay_entry.grid(row=row, column=1, sticky="w", padx=(16, 12), pady=5)
        row += 1
        ttk.Label(container, text="完成等待 ms", style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=5)
        speed_verify_entry = ttk.Entry(container, textvariable=speed_verify_var, width=18)
        speed_verify_entry.grid(row=row, column=1, sticky="w", padx=(16, 12), pady=5)

        def apply_speed_preset(_event: Any = None) -> None:
            preset = self._speed_preset_from_display(speed_preset_var.get())
            if preset == "custom":
                return
            config = PLACEMENT_SPEED_PRESETS[preset]
            speed_delay_var.set(str(config["delayMs"]))
            speed_verify_var.set(str(config["verifyDelayMs"]))
            hint.set(f"已选择摆放速度：{config['label']}。")

        def mark_custom_speed(_event: Any = None) -> None:
            speed_preset_var.set(self._speed_preset_display("custom"))

        speed_combo.bind("<<ComboboxSelected>>", apply_speed_preset)
        speed_delay_entry.bind("<KeyRelease>", mark_custom_speed)
        speed_verify_entry.bind("<KeyRelease>", mark_custom_speed)

        optimal_mode_var = tk.BooleanVar(value=self.solver_mode == SOLVER_MODE_OPTIMAL)
        row += 1
        ttk.Label(container, text="求解策略", style="SectionTitle.TLabel").grid(
            row=row,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(12, 8),
        )
        row += 1
        ttk.Checkbutton(
            container,
            text="最少要素优先",
            variable=optimal_mode_var,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=5)
        row += 1
        ttk.Label(
            container,
            text="关闭时优先使用库存中数量充足的要素；开启后先保证最少放置，格数相同时会均衡基础要素库存并减少合成。",
            style="Muted.TLabel",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))

        target_pid_var = tk.StringVar(value=self.target_pid)
        process_var = tk.StringVar()
        row += 1
        ttk.Label(container, text="目标 JVM 进程（仅本次运行）", style="SectionTitle.TLabel").grid(
            row=row,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(12, 8),
        )
        row += 1
        ttk.Label(
            container,
            text="留空为自动检测；PID 会在游戏重启后变化，手动选择仅对本次运行生效。",
            style="Muted.TLabel",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row += 1
        ttk.Label(container, text="PID", style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(container, textvariable=target_pid_var, width=18).grid(row=row, column=1, sticky="w", padx=(16, 12), pady=5)
        ttk.Button(container, text="清空", command=lambda: target_pid_var.set("")).grid(row=row, column=2, sticky="e", pady=5)
        row += 1
        process_combo = ttk.Combobox(container, textvariable=process_var, width=58, state="readonly")
        process_combo.grid(row=row, column=0, columnspan=2, sticky="we", pady=5)

        def apply_selected_process() -> None:
            selected = process_var.get().strip()
            if not selected:
                return
            target_pid_var.set(selected.split(maxsplit=1)[0])

        def refresh_processes() -> None:
            from .client_bridge import list_java_processes

            processes = list_java_processes()
            values = [process.label for process in processes]
            process_combo.configure(values=values)
            if values:
                process_var.set(values[0])
                hint.set(f"已找到 {len(values)} 个 JVM，选中后点击“使用选中”。")
            else:
                process_var.set("")
                hint.set("没有找到可见 JVM；请确认游戏已启动，或手动输入 PID。")

        ttk.Button(container, text="刷新 JVM", command=refresh_processes).grid(row=row, column=2, sticky="e", pady=5)
        row += 1
        ttk.Button(container, text="使用选中", command=apply_selected_process).grid(row=row, column=2, sticky="e", pady=5)
        process_combo.bind("<<ComboboxSelected>>", lambda _event: apply_selected_process())
        row += 1

        def parse_speed_settings() -> dict[str, int | str] | None:
            preset = self._speed_preset_from_display(speed_preset_var.get())
            if preset != "custom":
                config = PLACEMENT_SPEED_PRESETS[preset]
                return {
                    "preset": preset,
                    "delayMs": int(config["delayMs"]),
                    "verifyDelayMs": int(config["verifyDelayMs"]),
                }
            try:
                delay_ms = int(speed_delay_var.get().strip())
                verify_delay_ms = int(speed_verify_var.get().strip())
            except ValueError:
                hint.set("摆放速度只能填写数字；单位为毫秒。")
                return None
            if delay_ms < 0 or verify_delay_ms < 0 or delay_ms > 5000 or verify_delay_ms > 5000:
                hint.set("摆放速度范围为 0 到 5000 毫秒。")
                return None
            return {"preset": "custom", "delayMs": delay_ms, "verifyDelayMs": verify_delay_ms}

        def save_settings() -> bool:
            speed = parse_speed_settings()
            if speed is None:
                return False
            target = target_pid_var.get().strip()
            if target and not target.isdigit():
                hint.set("PID 只能是数字；留空表示自动检测。")
                return False
            self.target_pid = target
            self.placement_speed = speed
            self.solver_mode = (
                SOLVER_MODE_OPTIMAL
                if optimal_mode_var.get()
                else DEFAULT_SOLVER_MODE
            )
            self._save_settings()
            hint.set(
                f"已保存：{self._solver_mode_summary()}；摆放速度：{self._placement_speed_summary()}；目标 JVM：{self.target_pid}"
                if self.target_pid
                else f"已保存：{self._solver_mode_summary()}；摆放速度：{self._placement_speed_summary()}；目标 JVM 使用自动检测。"
            )
            self._append_log(
                f"求解策略：{self._solver_mode_summary()}；摆放速度：{self._placement_speed_summary()}；目标 JVM PID：{self.target_pid}"
                if self.target_pid
                else f"求解策略：{self._solver_mode_summary()}；摆放速度：{self._placement_speed_summary()}；目标 JVM PID：自动检测"
            )
            return True

        def save_and_close() -> None:
            if save_settings():
                dialog.destroy()

        buttons = ttk.Frame(container, style="Panel.TFrame")
        buttons.grid(row=row, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="恢复默认", command=lambda: self._reset_shortcuts(value_vars, hint)).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="保存并关闭", command=save_and_close).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="关闭", command=dialog.destroy).pack(side="left")

        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.focus_set()

    def _capture_shortcut(self, dialog: Any, hint: Any, value_vars: dict[str, Any], action: str) -> None:
        hint.set(f"请按下“{ACTION_LABELS[action]}”的新快捷键……")

        def on_key(event: Any) -> str:
            sequence = self._event_to_shortcut(event)
            if sequence is None:
                return "break"
            conflict = next((name for name, value in self.shortcuts.items() if value == sequence and name != action), None)
            if conflict is not None:
                hint.set(f"{self._shortcut_display(sequence)} 已用于“{ACTION_LABELS[conflict]}”。")
                dialog.unbind("<KeyPress>")
                return "break"
            self.shortcuts[action] = sequence
            self._save_shortcuts()
            self._bind_shortcuts()
            self._refresh_shortcut_labels()
            value_vars[action].set(self._shortcut_display(sequence))
            hint.set(f"已设置：{ACTION_LABELS[action]} → {self._shortcut_display(sequence)}")
            dialog.unbind("<KeyPress>")
            return "break"

        dialog.bind("<KeyPress>", on_key)
        dialog.focus_force()

    def _reset_shortcuts(self, value_vars: dict[str, Any], hint: Any) -> None:
        self.shortcuts = dict(DEFAULT_SHORTCUTS)
        self._save_shortcuts()
        self._bind_shortcuts()
        self._refresh_shortcut_labels()
        for action in ACTION_ORDER:
            value_vars[action].set(self._shortcut_display(self.shortcuts[action]))
        hint.set("已恢复默认快捷键。")

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
        self.worker_queue = queue.Queue()
        self.batch_total = 0
        self.stop_event = threading.Event()
        self.busy = True
        self.cancellable_busy = cancellable
        self._set_busy_ui(label, cancellable=cancellable)
        self._set_status(f"{label}……")
        self._append_log(f"开始：{label}")

        def emit(kind: str, payload: Any) -> None:
            assert self.worker_queue is not None
            self.worker_queue.put((kind, payload))

        def runner() -> None:
            try:
                payload = task(self.stop_event or threading.Event(), emit)
                emit("done", payload)
            except Exception as exc:
                emit("error", exc)

        self.worker_thread = threading.Thread(target=runner, name="ThaumNexusGuiWorker", daemon=True)
        self.worker_thread.start()
        self.tk.after(80, self._poll_worker_queue)

    def _poll_worker_queue(self) -> None:
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
                self._handle_worker_done(payload)
            elif kind == "error":
                self._handle_worker_error(payload)

        if self.busy and self.tk is not None:
            self.tk.after(120, self._poll_worker_queue)

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
        from .client_bridge import OperationCancelled

        if isinstance(exc, OperationCancelled):
            if self.logbook:
                self.logbook.set_page("cancelled", "已停止当前操作，可以重新读取笔记。")
            self._set_status("任务已停止。")
            self._append_log("任务已停止。")
            self._finish_worker_ui()
            return

        error_text, error_json = self._write_error_report(exc)
        if self.logbook:
            self.logbook.set_page("error", self._short_error(exc))
        self._set_status(f"任务失败：{self._short_error(exc)}")
        self._append_log(f"失败：{self._short_error(exc)}")
        self._append_log(f"完整错误已写入：{error_text}")
        self._append_log(f"诊断 JSON：{error_json}")
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
            button.configure(state="disabled" if key == "save" and self.rendered is None else "normal")
        if self.stop_button is not None:
            self.stop_button.configure(state="disabled")
        if self.worker_label is not None:
            state = self.logbook.state if self.logbook else "idle"
            label = {"success": "完成", "error": "失败", "cancelled": "已停止"}.get(state, "空闲")
            self.worker_label.set(f"状态：{label}")

    def _show_solution(self, *, board: Any, solution: Any, note_label: str, payload: dict[str, Any]) -> None:
        self.rendered = self.board_renderer.render(board, solution)
        out_dir = self.runtime_root
        out_dir.mkdir(parents=True, exist_ok=True)
        self.solution_image_path = out_dir / "current_solution.png"
        self.rendered.save(self.solution_image_path)
        solution_json = out_dir / "current_solution.json"
        solution_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.solution_payload = payload
        if self.note_name is not None:
            self.note_name.set(f"笔记：{note_label}")
        if self.placement_count is not None:
            self.placement_count.set(f"放置：{len(solution.placements)}")
        if self.logbook:
            self.logbook.set_page("success", preview=self.board_renderer.render(board, solution, paper=True))
        self.buttons["save"].configure(state="normal")

    def _save_solution(self) -> None:
        from tkinter import filedialog

        if self.rendered is None:
            self._set_status("还没有答案图。请先读取当前笔记。")
            return
        default = "current_solution.png"
        if self.solution_image_path is not None:
            default = self.solution_image_path.name
        path = filedialog.asksaveasfilename(
            title="保存答案图",
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
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _write_error_report(self, exc: Exception) -> tuple[Path, Path]:
        payload = {
            "source": "thaum-nexus-gui",
            "status": "error",
            "action": "gui-worker",
            "errorType": type(exc).__name__,
            "error": str(exc),
        }
        error_json = self._write_runtime_json("gui_last_error.json", payload)
        error_text = self.runtime_root / "gui_last_error.txt"
        error_text.parent.mkdir(parents=True, exist_ok=True)
        error_text.write_text(str(exc).strip() + "\n", encoding="utf-8")
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
