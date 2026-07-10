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
from .paths import app_root, resource_root, runtime_root


GITHUB_URL = "https://github.com/CaeliaEve/thaumcraft-nexus"
GITHUB_ICON = Path("image") / "icons8-github-50.png"
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
    "wheelchair": "轮椅模式：解完背包笔记",
    "save": "保存答案图",
}
ACTION_ORDER = ("read", "apply", "wheelchair", "save")


class ThaumNexusGui:
    """Minimal desktop GUI for the structured client-note workflow."""
    # UI text markers: 读取当前笔记 / 读取并自动放置 / 轮椅模式 / 停止当前任务

    def __init__(self, project_root: Path | str | None = None) -> None:
        self.bridge_project_root = Path(project_root).resolve() if project_root is not None else None
        self.project_root = app_root(self.bridge_project_root)
        self.resource_root = resource_root(self.bridge_project_root)
        self.runtime_root = runtime_root(self.bridge_project_root)
        self.kb = KnowledgeBase.load(self.resource_root)
        self.board_renderer = BoardImageRenderer(self.kb, project_root=self.resource_root, hex_size=34, icon_size=24)

        self.tk = None
        self.canvas = None
        self.status = None
        self.note_name = None
        self.placement_count = None
        self.worker_label = None
        self.progress = None
        self.log_text = None
        self.buttons: dict[str, Any] = {}
        self.stop_button = None
        self.shortcut_bindings: list[str] = []
        self.shortcuts = self._load_shortcuts()
        self.placement_speed = self._load_placement_speed()
        self.solver_mode = self._load_solver_mode()
        # A JVM PID is process-lifetime state: it changes every time the game restarts.
        # Keep manual PID selection for the current GUI session only, and never
        # resurrect a stale PID from gui_settings.json.
        self.target_pid = ""

        self.photo = None
        self.github_normal_photo = None
        self.github_hover_photo = None
        self.canvas_refresh_job = None
        self.canvas_image_cache_key: tuple[int, int, int] | None = None
        self.rendered = None
        self.solution_payload: dict[str, Any] | None = None
        self.solution_image_path: Path | None = None
        self.display_scale = 1.0

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
        self.tk.geometry("1180x780")
        self.tk.minsize(980, 660)

        self._configure_style(ttk)
        self._build_layout(tk, ttk)
        self._set_status("准备就绪。")
        self._append_log("\u51c6\u5907\u5c31\u7eea\u3002")
        self.tk.mainloop()
        return 0

    def _configure_style(self, ttk) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Configure overall option database for dropdown listboxes to match our dark theme
        self.tk.option_add("*TCombobox*Listbox.background", "#1C1C1C")
        self.tk.option_add("*TCombobox*Listbox.foreground", "#F5F5F5")
        self.tk.option_add("*TCombobox*Listbox.selectBackground", "#E0E0E0")
        self.tk.option_add("*TCombobox*Listbox.selectForeground", "#080808")
        self.tk.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))

        style.configure(".", font=("Segoe UI", 10), foreground="#F5F5F5")
        style.configure("TFrame", background="#080808")
        style.configure("Panel.TFrame", background="#121212")
        style.configure("Card.TFrame", background="#1C1C1C", borderwidth=1, relief="solid", bordercolor="#2A2A2A")
        style.configure("Divider.TFrame", background="#2A2A2A")
        # Labels style configuration.
        style.configure("AppTitle.TLabel", background="#121212", foreground="#F5F5F5", font=("Monotype Corsiva", 26, "italic", "bold"))
        style.configure("AppSubtitle.TLabel", background="#121212", foreground="#7C7C7C", font=("Monotype Corsiva", 18, "italic", "bold"))
        style.configure("SectionTitle.TLabel", background="#121212", foreground="#F5F5F5", font=("Segoe UI", 11, "bold"))
        style.configure("Muted.TLabel", background="#121212", foreground="#7C7C7C")
        style.configure("Link.TLabel", background="#121212", foreground="#E0E0E0", font=("Georgia", 10, "bold"))
        style.configure("Status.TLabel", background="#080808", foreground="#CCCCCC")

        # Card Specific Labels (inside the stats container)
        style.configure("Card.TLabel", background="#1C1C1C", foreground="#F5F5F5", font=("Segoe UI", 10))
        style.configure("CardMuted.TLabel", background="#1C1C1C", foreground="#7C7C7C", font=("Segoe UI", 10))

        # Standard Button (Matte Dark Charcoal)
        style.configure("TButton",
                        background="#161616",
                        foreground="#F5F5F5",
                        bordercolor="#2A2A2A",
                        darkcolor="#161616",
                        lightcolor="#161616",
                        focuscolor="#E0E0E0",
                        borderwidth=1,
                        padding=(12, 8),
                        font=("Segoe UI", 10, "bold"))
        style.map("TButton",
                  background=[("active", "#262626"), ("disabled", "#080808")],
                  foreground=[("disabled", "#7C7C7C")],
                  bordercolor=[("active", "#404040"), ("disabled", "#2A2A2A")])

        # Primary Button (Stark White Block)
        style.configure("Primary.TButton",
                        background="#E0E0E0",
                        foreground="#080808",
                        bordercolor="#E0E0E0",
                        darkcolor="#E0E0E0",
                        lightcolor="#E0E0E0",
                        focuscolor="#FFFFFF",
                        borderwidth=1,
                        padding=(12, 8),
                        font=("Segoe UI", 10, "bold"))
        style.map("Primary.TButton",
                  background=[("active", "#FFFFFF"), ("disabled", "#1C1C1C")],
                  foreground=[("disabled", "#7C7C7C")],
                  bordercolor=[("active", "#FFFFFF"), ("disabled", "#2A2A2A")])

        # Danger Button (Slate Grey Warning)
        style.configure("Danger.TButton",
                        background="#1C1C1C",
                        foreground="#F5F5F5",
                        bordercolor="#7C7C7C",
                        darkcolor="#1C1C1C",
                        lightcolor="#1C1C1C",
                        focuscolor="#FFFFFF",
                        borderwidth=1,
                        padding=(12, 8),
                        font=("Segoe UI", 10, "bold"))
        style.map("Danger.TButton",
                  background=[("active", "#2A2A2A"), ("disabled", "#1C1C1C")],
                  foreground=[("disabled", "#7C7C7C")],
                  bordercolor=[("active", "#E0E0E0"), ("disabled", "#2A2A2A")])

        # Combobox
        style.configure("TCombobox",
                        fieldbackground="#1C1C1C",
                        background="#121212",
                        foreground="#F5F5F5",
                        bordercolor="#2A2A2A",
                        darkcolor="#1C1C1C",
                        lightcolor="#1C1C1C",
                        arrowcolor="#7C7C7C",
                        arrowsize=12,
                        padding=5)
        style.map("TCombobox",
                  fieldbackground=[("readonly", "#1C1C1C"), ("active", "#262626")],
                  bordercolor=[("focus", "#E0E0E0"), ("active", "#2A2A2A")])

        # Entry
        style.configure("TEntry",
                        fieldbackground="#1C1C1C",
                        foreground="#F5F5F5",
                        bordercolor="#2A2A2A",
                        lightcolor="#1C1C1C",
                        darkcolor="#1C1C1C",
                        padding=6)
        style.map("TEntry",
                  bordercolor=[("focus", "#E0E0E0"), ("active", "#2A2A2A")])

        style.configure(
            "TCheckbutton",
            background="#121212",
            foreground="#F5F5F5",
            focuscolor="#121212",
            font=("Segoe UI", 10),
        )
        style.map(
            "TCheckbutton",
            background=[("active", "#121212")],
            foreground=[("disabled", "#7C7C7C")],
        )

        # Progressbar (Grayscale Mana bar)
        style.configure("Horizontal.TProgressbar",
                        troughcolor="#1C1C1C",
                        bordercolor="#2A2A2A",
                        background="#E0E0E0",
                        lightcolor="#E0E0E0",
                        darkcolor="#E0E0E0",
                        thickness=6)

    def _build_layout(self, tk, ttk) -> None:
        assert self.tk is not None
        outer = ttk.Frame(self.tk, style="TFrame")
        outer.pack(fill="both", expand=True)

        side = ttk.Frame(outer, style="Panel.TFrame", width=320)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        title_frame = ttk.Frame(side, style="Panel.TFrame")
        title_frame.pack(anchor="w", padx=20, pady=(24, 18))
        ttk.Label(title_frame, text="Thaumcraft", style="AppTitle.TLabel").pack(side="left")
        ttk.Label(title_frame, text="Nexus", style="AppSubtitle.TLabel").pack(side="left", padx=(6, 0), pady=(4, 0))

        self.buttons["read"] = self._button(side, self._button_text("read"), self._read_current_note, style="Primary.TButton")
        self.buttons["read"].pack(fill="x", padx=20, pady=(0, 9))
        self.buttons["apply"] = self._button(side, self._button_text("apply"), self._read_and_apply_current_note)
        self.buttons["apply"].pack(fill="x", padx=20, pady=4)
        self.buttons["wheelchair"] = self._button(side, self._button_text("wheelchair"), self._wheelchair_apply_notes)
        self.buttons["wheelchair"].pack(fill="x", padx=20, pady=4)
        self.stop_button = self._button(side, "\u505c\u6b62\u5f53\u524d\u4efb\u52a1", self._stop_current_task, style="Danger.TButton")
        self.stop_button.pack(fill="x", padx=20, pady=(12, 4))
        self.stop_button.configure(state="disabled")
        self.buttons["save"] = self._button(side, self._button_text("save"), self._save_solution)
        self.buttons["save"].pack(fill="x", padx=20, pady=(16, 4))
        self.buttons["settings"] = self._button(side, "设置", self._open_settings)
        self.buttons["settings"].pack(fill="x", padx=20, pady=4)

        stats = ttk.Frame(side, style="Panel.TFrame")
        stats.pack(fill="x", padx=20, pady=(22, 0))
        self.note_name = tk.StringVar(value="\u7b14\u8bb0\uff1a-")
        self.placement_count = tk.StringVar(value="\u653e\u7f6e\uff1a-")
        self.worker_label = tk.StringVar(value="\u72b6\u6001\uff1a\u7a7a\u95f2")
        ttk.Label(stats, textvariable=self.note_name, style="Muted.TLabel").pack(anchor="w")
        ttk.Label(stats, textvariable=self.placement_count, style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
        ttk.Label(stats, textvariable=self.worker_label, style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        self.progress = ttk.Progressbar(side, mode="indeterminate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=20, pady=(18, 0))

        ttk.Frame(side, style="Panel.TFrame").pack(fill="both", expand=True)
        self._build_github_link(side, tk, ttk)

        main = ttk.Frame(outer, style="TFrame")
        main.pack(side="left", fill="both", expand=True)

        canvas_card = ttk.Frame(main, style="Card.TFrame")
        canvas_card.pack(fill="both", expand=True, padx=14, pady=(14, 8))
        self.canvas = tk.Canvas(canvas_card, bg="#050505", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(28, 28, text="\u7b49\u5f85\u8bfb\u53d6\u7814\u7a76\u7b14\u8bb0", fill="#7C7C7C", anchor="nw", font=("Segoe UI", 14))
        self.canvas.bind("<Configure>", lambda _event: self._schedule_canvas_refresh())

        bottom = ttk.Frame(main, style="TFrame")
        bottom.pack(fill="x", padx=14, pady=(0, 12))
        self.status = tk.StringVar()
        ttk.Label(bottom, textvariable=self.status, style="Status.TLabel", anchor="w").pack(fill="x", pady=(0, 6))
        self.log_text = tk.Text(
            bottom,
            height=6,
            bg="#050505",
            fg="#CCCCCC",
            insertbackground="#CCCCCC",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#2A2A2A",
            wrap="word",
            font=("Consolas", 10),
        )
        self.log_text.pack(fill="x")
        self.log_text.configure(state="disabled")

        self._bind_shortcuts()

    def _button(self, parent, text: str, command, style: str = "TButton"):
        from tkinter import ttk

        return ttk.Button(parent, text=text, command=command, style=style)

    def _build_github_link(self, parent, tk, ttk) -> None:
        footer = ttk.Frame(parent, style="Panel.TFrame")
        footer.pack(side="bottom", fill="x", padx=20, pady=(0, 18))

        icon_path = self.resource_root / GITHUB_ICON
        self.github_normal_photo = self._load_github_icon(icon_path, (124, 124, 124))
        self.github_hover_photo = self._load_github_icon(icon_path, (245, 245, 245))

        icon = tk.Label(footer, image=self.github_normal_photo, bg="#121212", bd=0, cursor="hand2")
        icon.pack(side="left")

        label = tk.Label(footer, text="GitHub", fg="#7C7C7C", bg="#121212", font=("Georgia", 11, "italic", "bold"), bd=0, cursor="hand2")
        label.pack(side="left", padx=(8, 0))

        def on_enter(_event) -> None:
            icon.configure(image=self.github_hover_photo)
            label.configure(fg="#F5F5F5")

        def on_leave(_event) -> None:
            icon.configure(image=self.github_normal_photo)
            label.configure(fg="#7C7C7C")

        for widget in (footer, icon, label):
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
            widget.bind("<Button-1>", lambda _event: self._open_github())

    def _open_github(self) -> None:
        import webbrowser
        webbrowser.open_new_tab(GITHUB_URL)

    def _load_github_icon(self, icon_path: Path, color: tuple[int, int, int]):
        from PIL import Image, ImageTk
        img = Image.open(icon_path).convert("RGBA")
        solid = Image.new("RGBA", img.size, color + (255,))
        tinted = Image.composite(solid, Image.new("RGBA", img.size, (0, 0, 0, 0)), img.split()[3])
        tinted = tinted.resize((20, 20), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(tinted)

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
        for sequence in self.shortcut_bindings:
            try:
                self.tk.unbind(sequence)
            except Exception:
                pass
        self.shortcut_bindings = []
        callbacks = {
            "read": self._read_current_note,
            "apply": self._read_and_apply_current_note,
            "wheelchair": self._wheelchair_apply_notes,
            "save": self._save_solution,
        }
        for action, callback in callbacks.items():
            sequence = self.shortcuts.get(action)
            if not sequence:
                continue
            self.tk.bind(sequence, lambda _event, cb=callback: cb())
            self.shortcut_bindings.append(sequence)

    def _refresh_shortcut_labels(self) -> None:
        for action in ACTION_ORDER:
            button = self.buttons.get(action)
            if button is not None:
                button.configure(text=self._button_text(action))

    def _shortcut_display(self, sequence: str) -> str:
        if not sequence:
            return ""
        text = sequence.strip("<>")
        text = text.replace("Control", "Ctrl")
        text = text.replace("-", "+")
        return text

    def _event_to_shortcut(self, event) -> str | None:
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
        dialog.configure(bg="#121212")
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

        def apply_speed_preset(_event=None) -> None:
            preset = self._speed_preset_from_display(speed_preset_var.get())
            if preset == "custom":
                return
            config = PLACEMENT_SPEED_PRESETS[preset]
            speed_delay_var.set(str(config["delayMs"]))
            speed_verify_var.set(str(config["verifyDelayMs"]))
            hint.set(f"已选择摆放速度：{config['label']}。")

        def mark_custom_speed(_event=None) -> None:
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
            text="关闭时优先使用库存中数量充足的要素；开启后优先最少放置，缺少的复合要素会自动递归合成。",
            style="Muted.TLabel",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))

        target_pid_var = tk.StringVar(value=self.target_pid)
        process_var = tk.StringVar()
        row += 1
        ttk.Label(container, text="\u76ee\u6807 JVM \u8fdb\u7a0b\uff08\u4ec5\u672c\u6b21\u8fd0\u884c\uff09", style="SectionTitle.TLabel").grid(
            row=row,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(12, 8),
        )
        row += 1
        ttk.Label(
            container,
            text="\u7559\u7a7a\u4e3a\u81ea\u52a8\u68c0\u6d4b\uff1bPID \u4f1a\u5728\u6e38\u620f\u91cd\u542f\u540e\u53d8\u5316\uff0c\u624b\u52a8\u9009\u62e9\u4ec5\u5bf9\u672c\u6b21\u8fd0\u884c\u751f\u6548\u3002",
            style="Muted.TLabel",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row += 1
        ttk.Label(container, text="PID", style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(container, textvariable=target_pid_var, width=18).grid(row=row, column=1, sticky="w", padx=(16, 12), pady=5)
        ttk.Button(container, text="\u6e05\u7a7a", command=lambda: target_pid_var.set("")).grid(row=row, column=2, sticky="e", pady=5)
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
                hint.set(f"\u5df2\u627e\u5230 {len(values)} \u4e2a JVM\uff0c\u9009\u4e2d\u540e\u70b9\u51fb\u201c\u4f7f\u7528\u9009\u4e2d\u201d\u3002")
            else:
                process_var.set("")
                hint.set("\u6ca1\u6709\u627e\u5230\u53ef\u89c1 JVM\uff1b\u8bf7\u786e\u8ba4\u6e38\u620f\u5df2\u542f\u52a8\uff0c\u6216\u624b\u52a8\u8f93\u5165 PID\u3002")

        ttk.Button(container, text="\u5237\u65b0 JVM", command=refresh_processes).grid(row=row, column=2, sticky="e", pady=5)
        row += 1
        ttk.Button(container, text="\u4f7f\u7528\u9009\u4e2d", command=apply_selected_process).grid(row=row, column=2, sticky="e", pady=5)
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
                hint.set("PID \u53ea\u80fd\u662f\u6570\u5b57\uff1b\u7559\u7a7a\u8868\u793a\u81ea\u52a8\u68c0\u6d4b\u3002")
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
        ttk.Button(buttons, text="\u4fdd\u5b58\u5e76\u5173\u95ed", command=save_and_close).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="关闭", command=dialog.destroy).pack(side="left")

        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.focus_set()

    def _capture_shortcut(self, dialog, hint, value_vars: dict[str, Any], action: str) -> None:
        hint.set(f"请按下“{ACTION_LABELS[action]}”的新快捷键……")

        def on_key(event) -> str:
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

    def _reset_shortcuts(self, value_vars: dict[str, Any], hint) -> None:
        self.shortcuts = dict(DEFAULT_SHORTCUTS)
        self._save_shortcuts()
        self._bind_shortcuts()
        self._refresh_shortcut_labels()
        for action in ACTION_ORDER:
            value_vars[action].set(self._shortcut_display(self.shortcuts[action]))
        hint.set("已恢复默认快捷键。")

    def _read_current_note(self) -> None:
        if self.busy:
            self._set_status("\u5df2\u6709\u4efb\u52a1\u5728\u8fd0\u884c\uff0c\u8bf7\u5148\u7b49\u5f85\u6216\u505c\u6b62\u5f53\u524d\u4efb\u52a1\u3002")
            return

        def task(stop_event: threading.Event, emit: Callable[[str, Any], None]) -> dict[str, Any]:
            from .client_bridge import read_and_solve_current_note

            emit("log", "\u8bfb\u53d6\u5f53\u524d\u7814\u7a76\u53f0\u7b14\u8bb0\u2026\u2026")
            pid = self._bridge_pid()
            if pid:
                emit("log", f"\u4f7f\u7528\u76ee\u6807 JVM PID\uff1a{pid}")
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
            self._set_status("\u5df2\u6709\u4efb\u52a1\u5728\u8fd0\u884c\uff0c\u8bf7\u5148\u7b49\u5f85\u6216\u505c\u6b62\u5f53\u524d\u4efb\u52a1\u3002")
            return

        def task(stop_event: threading.Event, emit: Callable[[str, Any], None]) -> dict[str, Any]:
            from .client_bridge import read_solve_and_apply_current_note

            emit("log", "\u8bfb\u53d6\u3001\u6c42\u89e3\u5e76\u81ea\u52a8\u653e\u7f6e\u5f53\u524d\u7b14\u8bb0\u2026\u2026")
            pid = self._bridge_pid()
            if pid:
                emit("log", f"\u4f7f\u7528\u76ee\u6807 JVM PID\uff1a{pid}")
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
            self._set_status("\u5df2\u6709\u4efb\u52a1\u5728\u8fd0\u884c\uff0c\u8bf7\u5148\u7b49\u5f85\u6216\u505c\u6b62\u5f53\u524d\u4efb\u52a1\u3002")
            return

        def task(stop_event: threading.Event, emit: Callable[[str, Any], None]) -> dict[str, Any]:
            from .client_bridge import solve_all_inventory_notes

            def progress(payload: dict[str, Any]) -> None:
                emit("log", str(payload.get("message") or payload.get("event") or "\u8f6e\u6905\u6a21\u5f0f\u8fdb\u5ea6\u66f4\u65b0"))

            emit("log", "\u8f6e\u6905\u6a21\u5f0f\u542f\u52a8\uff1a\u5f00\u59cb\u626b\u63cf\u80cc\u5305\u672a\u89e3\u7b14\u8bb0\u3002")
            pid = self._bridge_pid()
            if pid:
                emit("log", f"\u4f7f\u7528\u76ee\u6807 JVM PID\uff1a{pid}")
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
        self.stop_event = threading.Event()
        self.busy = True
        self.cancellable_busy = cancellable
        self._set_busy_ui(label, cancellable=cancellable)
        self._set_status(f"{label}\u2026\u2026")
        self._append_log(f"\u5f00\u59cb\uff1a{label}")

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
                self._set_status(f"\u8bfb\u53d6\u5b8c\u6210\uff1a\u9700\u8981\u653e\u7f6e {len(result.solution.placements)} \u4e2a\u8981\u7d20\u3002\u6587\u4ef6\uff1a{self.solution_image_path}")
                self._append_log("\u8bfb\u53d6\u5b8c\u6210\u3002")
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
                self._set_status(f"\u81ea\u52a8\u653e\u7f6e\u5b8c\u6210\uff1a\u5408\u6210 {combines} \u6b21\uff0c\u653e\u7f6e {sent} \u4e2a\uff0c\u8df3\u8fc7 {skipped} \u4e2a\u3002")
                self._append_log("\u81ea\u52a8\u653e\u7f6e\u5b8c\u6210\u3002")
            elif kind == "wheelchair":
                batch = payload["payload"]
                result_json = payload["resultJson"]
                status = str(batch.get("status") or "ok")
                solved = int(batch.get("solvedOrAttempted", 0) or 0)
                message = str(batch.get("message") or "\u8f6e\u6905\u6a21\u5f0f\u7ed3\u675f")
                self._set_status(f"\u8f6e\u6905\u6a21\u5f0f{self._status_cn(status)}\uff1a\u5c1d\u8bd5\u5904\u7406 {solved} \u5f20\u3002{message} \u6587\u4ef6\uff1a{result_json}")
                self._append_log(f"\u8f6e\u6905\u6a21\u5f0f\u7ed3\u675f\uff1a{message}")
            else:
                self._set_status("\u4efb\u52a1\u5b8c\u6210\u3002")
        finally:
            self._finish_worker_ui()

    def _handle_worker_error(self, exc: Exception) -> None:
        from .client_bridge import OperationCancelled

        if isinstance(exc, OperationCancelled):
            self._set_status("\u4efb\u52a1\u5df2\u505c\u6b62\u3002")
            self._append_log("\u4efb\u52a1\u5df2\u505c\u6b62\u3002")
            self._finish_worker_ui()
            return

        error_text, error_json = self._write_error_report(exc)
        self._set_status(f"\u4efb\u52a1\u5931\u8d25\uff1a{self._short_error(exc)}")
        self._append_log(f"\u5931\u8d25\uff1a{self._short_error(exc)}")
        self._append_log(f"\u5b8c\u6574\u9519\u8bef\u5df2\u5199\u5165\uff1a{error_text}")
        self._append_log(f"\u8bca\u65ad JSON\uff1a{error_json}")
        self._finish_worker_ui()

    def _stop_current_task(self) -> None:
        if not self.busy or self.stop_event is None:
            return
        self.stop_event.set()
        self._set_status("\u6b63\u5728\u7acb\u5373\u505c\u6b62\u2026\u2026")
        self._append_log("\u5df2\u53d1\u9001\u7acb\u5373\u505c\u6b62\u8bf7\u6c42\u3002")
        if self.stop_button is not None:
            self.stop_button.configure(state="disabled")

    def _set_busy_ui(self, label: str, *, cancellable: bool) -> None:
        for key, button in self.buttons.items():
            if key != "save":
                button.configure(state="disabled")
        if self.stop_button is not None:
            self.stop_button.configure(state="normal" if cancellable else "disabled")
        if self.worker_label is not None:
            self.worker_label.set(f"\u72b6\u6001\uff1a{label}")
        if self.progress is not None:
            self.progress.start(12)

    def _finish_worker_ui(self) -> None:
        self.busy = False
        self.cancellable_busy = False
        for button in self.buttons.values():
            button.configure(state="normal")
        if self.stop_button is not None:
            self.stop_button.configure(state="disabled")
        if self.worker_label is not None:
            self.worker_label.set("\u72b6\u6001\uff1a\u7a7a\u95f2")
        if self.progress is not None:
            self.progress.stop()

    def _show_solution(self, *, board, solution, note_label: str, payload: dict[str, Any]) -> None:
        self.rendered = self.board_renderer.render(board, solution)
        out_dir = self.runtime_root
        out_dir.mkdir(parents=True, exist_ok=True)
        self.solution_image_path = out_dir / "current_solution.png"
        self.rendered.save(self.solution_image_path)
        solution_json = out_dir / "current_solution.json"
        solution_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.solution_payload = payload
        if self.note_name is not None:
            self.note_name.set(f"\u7b14\u8bb0\uff1a{note_label}")
        if self.placement_count is not None:
            self.placement_count.set(f"\u653e\u7f6e\uff1a{len(solution.placements)}")
        self._refresh_canvas_image()

    def _save_solution(self) -> None:
        from tkinter import filedialog

        if self.rendered is None:
            self._set_status("\u8fd8\u6ca1\u6709\u7b54\u6848\u56fe\u3002\u8bf7\u5148\u8bfb\u53d6\u5f53\u524d\u7b14\u8bb0\u3002")
            return
        default = "current_solution.png"
        if self.solution_image_path is not None:
            default = self.solution_image_path.name
        path = filedialog.asksaveasfilename(
            title="\u4fdd\u5b58\u7b54\u6848\u56fe",
            initialfile=default,
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("All files", "*.*")],
        )
        if not path:
            return
        self.rendered.save(path)
        self._set_status(f"\u7b54\u6848\u56fe\u5df2\u4fdd\u5b58\uff1a{path}")
        self._append_log(f"\u7b54\u6848\u56fe\u5df2\u4fdd\u5b58\uff1a{path}")

    def _refresh_canvas_image(self) -> None:
        if self.canvas is None or self.rendered is None:
            return
        from PIL import Image, ImageTk

        image = self.rendered
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        if canvas_w <= 1:
            canvas_w = 820
        if canvas_h <= 1:
            canvas_h = 560

        max_w = max(1, canvas_w - 28)
        max_h = max(1, canvas_h - 28)
        self.display_scale = self._display_scale(image, max_w, max_h)
        display_w = max(1, round(image.width * self.display_scale))
        display_h = max(1, round(image.height * self.display_scale))
        cache_key = (id(image), display_w, display_h)
        if cache_key != self.canvas_image_cache_key or self.photo is None:
            display = image.resize((display_w, display_h), Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(display)
            self.canvas_image_cache_key = cache_key
        self.canvas.delete("all")
        self.canvas.create_image(canvas_w // 2, canvas_h // 2, image=self.photo, anchor="center")

    def _display_scale(self, image, max_w: int, max_h: int) -> float:
        return min(1.0, max(1, max_w) / image.width, max(1, max_h) / image.height)

    def _schedule_canvas_refresh(self) -> None:
        if self.tk is None:
            self._refresh_canvas_image()
            return
        if self.canvas_refresh_job is not None:
            try:
                self.tk.after_cancel(self.canvas_refresh_job)
            except Exception:
                pass
        self.canvas_refresh_job = self.tk.after(80, self._run_scheduled_canvas_refresh)

    def _run_scheduled_canvas_refresh(self) -> None:
        self.canvas_refresh_job = None
        self._refresh_canvas_image()

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
        if self.log_text is None:
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text.strip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _status_cn(self, status: str) -> str:
        return {"ok": "\u5b8c\u6210", "cancelled": "\u5df2\u505c\u6b62", "incomplete": "\u672a\u5b8c\u5168\u5b8c\u6210", "error": "\u5931\u8d25"}.get(status, "\u7ed3\u675f")

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
