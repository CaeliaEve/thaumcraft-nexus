"""Canvas presentation for the logbook. No game or worker dependencies."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable

from PIL import Image, ImageTk


WIDTH, HEIGHT = 1024, 681
INK = "#291d13"
RED = "#641b13"
MUTED = "#57432f"
GOLD = "#8b481c"


@dataclass
class MenuAction:
    view: "LogbookView"
    key: str
    label: str
    shortcut: str
    command: Callable[[], None]
    y: int
    state: str = "normal"

    def configure(self, **kwargs) -> None:
        self.state = kwargs.get("state", self.state)
        self.view.draw()

    config = configure

    def set_shortcut_text(self, text: str) -> None:
        self.shortcut = text
        self.view.draw()

    def invoke(self) -> None:
        if self.state == "normal":
            self.command()


class LogbookView:
    def __init__(self, parent: tk.Misc, background: Path,
                 actions: list[tuple[str, str, str, Callable[[], None]]],
                 on_details: Callable[[], None], on_github: Callable[[], None],
                 on_resources: Callable[[], None] | None = None):
        self.canvas = tk.Canvas(parent, width=WIDTH, height=HEIGHT, bg="#090705",
                                highlightthickness=0, takefocus=True)
        self.canvas.pack(fill="both", expand=True)
        with Image.open(background) as image:
            self.background = image.convert("RGB")
        with Image.open(background.parent / "icons8-github-50.png") as icon:
            self.github_icon = icon.convert("RGBA")
        self._github_photo = None
        self._github_key = None
        self.actions = {key: MenuAction(self, key, label, shortcut, command, 210 + i * 40)
                        for i, (key, label, shortcut, command) in enumerate(actions)}
        self.on_details, self.on_github = on_details, on_github
        self.on_resources = on_resources
        self.resource_summary: tuple[str, ...] = ()
        self.preview_regions: list[tuple[float, float, float, str]] = []
        self.preview_transform = (0.0, 0.0, 1.0)
        self._tooltip_text = ""
        self._tooltip_position = (109, 537)
        self.hover: str | None = None
        self.focus: str | None = None
        self.note = "—"
        self.placements = "—"
        self.worker = "空闲"
        self.status = "准备就绪"
        self.state = "idle"
        self.message = ""
        self.preview: Image.Image | None = None
        self.scale, self.offset_x, self.offset_y = 1.0, 0.0, 0.0
        self._background_key = None
        self._background_photo = None
        self._preview_key = None
        self._preview_photo = None
        self._tooltip_job = None
        self._fonts: dict[tuple, tkfont.Font] = {}
        families = set(tkfont.families(parent))
        self.family = next((name for name in ("SimSun", "Noto Serif CJK SC", "Microsoft YaHei")
                            if name in families), "TkDefaultFont")
        self.canvas.bind("<Configure>", lambda _event: self.draw())
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", self._leave)
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Tab>", lambda e: self._move_focus(-1 if e.state & 1 else 1))
        self.canvas.bind("<Shift-Tab>", lambda _e: self._move_focus(-1))
        try:
            self.canvas.bind("<ISO_Left_Tab>", lambda _e: self._move_focus(-1))
        except tk.TclError:
            pass  # Older Windows Tk does not define the X11 reverse-tab keysym.
        self.canvas.bind("<Up>", lambda _e: self._move_focus(-1))
        self.canvas.bind("<Down>", lambda _e: self._move_focus(1))
        self.canvas.bind("<Return>", self._activate_focus)
        self.canvas.bind("<space>", self._activate_focus)
        self.canvas.bind("<FocusOut>", lambda _e: self.draw())
        self.canvas.bind("<Destroy>", lambda _e: self._hide_tooltip())
        self.draw()

    def _font(self, size: int, *, family: str | None = None, italic=False) -> tkfont.Font:
        key = (family or self.family, max(9, round(size * self.scale)), italic)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(self.canvas, family=key[0], size=-key[1],
                                          slant="italic" if italic else "roman")
        return self._fonts[key]

    def point(self, x: float, y: float) -> tuple[float, float]:
        return self.offset_x + x * self.scale, self.offset_y + y * self.scale

    def _text(self, x, y, text, size=16, color=INK, anchor="w", width=None, **kwargs):
        font = self._font(size, family=kwargs.pop("family", None), italic=kwargs.pop("italic", False))
        return self.canvas.create_text(*self.point(x, y), text=text, font=font, fill=color,
                                       anchor=anchor, width=int(width * self.scale) if width else 0,
                                       **kwargs)

    def _fit(self, text: str, width: int, size=14) -> str:
        font = self._font(size)
        if font.measure(text) <= width * self.scale:
            return text
        while text and font.measure(text + "…") > width * self.scale:
            text = text[:-1]
        return text + "…"

    def _line(self, x1, y1, x2, y2, **kwargs):
        return self.canvas.create_line(*self.point(x1, y1), *self.point(x2, y2), **kwargs)

    def draw(self) -> None:
        if not self.canvas.winfo_exists():
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            cw, ch = WIDTH, HEIGHT
        self.scale = min(cw / WIDTH, ch / HEIGHT)
        self.offset_x = (cw - WIDTH * self.scale) / 2
        self.offset_y = (ch - HEIGHT * self.scale) / 2
        size = (max(1, round(WIDTH * self.scale)), max(1, round(HEIGHT * self.scale)))
        if size != self._background_key:
            self._background_photo = ImageTk.PhotoImage(self.background.resize(size, Image.Resampling.LANCZOS), master=self.canvas)
            self._background_key = size
            self._fonts.clear()
        self.canvas.delete("all")
        self.canvas.create_image(*self.point(0, 0), image=self._background_photo, anchor="nw")
        for action in self.actions.values():
            active = action.state == "normal"
            highlighted = active and (self.hover == action.key or self.focus == action.key)
            color = GOLD if highlighted else (RED if action.key in {"read", "stop"} else INK)
            if not active:
                color = MUTED
            self._text(110, action.y, action.label, color=color)
            title_end = 110 + self._font(16).measure(action.label) / self.scale + 10
            shortcut_start = 370 - self._font(12, family="Georgia", italic=True).measure(action.shortcut) / self.scale - 9
            if title_end < shortcut_start and action.key != "stop":
                self._line(title_end, action.y + 5, shortcut_start, action.y + 5,
                           fill="#503923", dash=(1, max(2, round(4 * self.scale))))
            if action.shortcut:
                self._text(370, action.y + 2, action.shortcut, size=12, color=color,
                           anchor="e", family="Georgia", italic=True)
            if highlighted:
                self._line(108, action.y + 16, 376, action.y + 16, fill=GOLD)

        self._text(130, 498, "现 况 ·", size=13)
        for y, label, value in [(520, "笔记", self.note), (540, "放置", self.placements), (560, "状态", self.worker)]:
            self._text(111, y, label, size=13)
            self._text(154, y, self._fit(value, 165, 13), size=13)
        self._text(111, 592, self._fit(self.status, 225, 12), size=12, color=RED)
        self._text(257, 624, "研究记录", size=12, color=GOLD if "details" in {self.hover, self.focus} else RED)
        icon_color = GOLD if "github" in {self.hover, self.focus} else INK
        icon_size = max(1, round(24 * self.scale))
        icon_key = (icon_size, icon_color)
        if icon_key != self._github_key:
            icon = Image.new("RGBA", self.github_icon.size, icon_color)
            icon.putalpha(self.github_icon.getchannel("A"))
            self._github_photo = ImageTk.PhotoImage(icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS), master=self.canvas)
            self._github_key = icon_key
        self.canvas.create_image(*self.point(352, 624), image=self._github_photo)
        if self.focus == "github":
            self._line(334, 641, 370, 641, fill=GOLD)

        if self.preview is not None and self.state == "success":
            box_w, box_h = 410 * self.scale, 385 * self.scale
            factor = min(box_w / self.preview.width, box_h / self.preview.height)
            preview_size = (max(1, round(self.preview.width * factor)), max(1, round(self.preview.height * factor)))
            key = (id(self.preview), preview_size)
            if key != self._preview_key:
                self._preview_photo = ImageTk.PhotoImage(self.preview.resize(preview_size, Image.Resampling.LANCZOS), master=self.canvas)
                self._preview_key = key
            center_x, center_y = self.point(717, 310)
            self.preview_transform = (center_x - preview_size[0] / 2, center_y - preview_size[1] / 2,
                                      preview_size[0] / self.preview.width)
            self.canvas.create_image(center_x, center_y, image=self._preview_photo)
            self._text(717, 524, self._fit(self.note, 342, 13), size=13, anchor="center", color=RED)
            for index, line in enumerate(self.resource_summary[:2]):
                self._text(717, 548 + index * 21, self._fit(line, 364, 13), size=13, anchor="center")
            if self.on_resources is not None:
                self._text(717, 592, "资源明细与合成顺序", size=13, anchor="center",
                           color=GOLD if "resources" in {self.hover, self.focus} else RED)
        else:
            headings = {"idle": "等 待 读 取 研 究 笔 记", "busy": "正 在 推 演",
                        "error": "本 次 推 演 失 败", "cancelled": "任 务 已 停 止",
                        "success": "研 究 笔 记 已 处 理"}
            self._text(717, 326, headings.get(self.state, headings["idle"]), size=18, color=RED, anchor="center")
            if self.message:
                self._text(717, 372, self._fit(self.message.replace("\n", " "), 312 * 2, 14),
                           size=14, color=INK, anchor="n", width=312, justify="center")

    def update_status(self, *, note=None, placements=None, worker=None, status=None) -> None:
        for key, value in (("note", note), ("placements", placements), ("worker", worker), ("status", status)):
            if value is not None:
                setattr(self, key, str(value))
        if self.state == "busy" and status is not None:
            self.message = str(status)
        self.draw()

    def set_page(self, state: str, message: str = "", preview: Image.Image | None = None) -> None:
        self._hide_tooltip()
        self.state, self.message = state, message
        if preview is not None:
            self.preview = preview
        self.draw()

    def _hit(self, event) -> str | None:
        x = (event.x - self.offset_x) / self.scale
        y = (event.y - self.offset_y) / self.scale
        for action in self.actions.values():
            if 102 <= x <= 382 and action.y - 18 <= y <= action.y + 18:
                return action.key if action.state == "normal" else None
        if 250 <= x <= 316 and 610 <= y <= 638:
            return "details"
        if 327 <= x <= 381 and 610 <= y <= 638:
            return "github"
        if self.state == "success" and self.preview is not None and self.on_resources is not None and 610 <= x <= 830 and 580 <= y <= 604:
            return "resources"
        return None

    def _motion(self, event) -> None:
        hit = self._hit(event)
        if hit != self.hover:
            self.hover = hit
            self.canvas.configure(cursor="hand2" if hit else "")
            self.draw()
        x = (event.x - self.offset_x) / self.scale
        y = (event.y - self.offset_y) / self.scale
        tips = {
            "github": "项目仓库 · GitHub",
            "read": "读取研究台上的笔记并推演连线，不消耗要素。",
            "apply": "解析当前笔记并自动放置，消耗游戏内的要素库存。",
            "wheelchair": "依次研习背包中的未解笔记，持续消耗要素库存。",
            "save": "将当前研究图谱保存为图片。",
            "settings": "调整研究策略、注入节律、快捷符令与世界连接。",
            "stop": "请求停止当前操作，等待正在执行的步骤安全结束。",
        }
        tooltip, position = tips.get(hit, ""), (109, 575)
        if 105 < x < 340 and 510 < y < 530 and self._fit(self.note, 165, 13) != self.note:
            tooltip = self.note
        elif self.state == "success" and self.preview is not None:
            left, top, factor = self.preview_transform
            px, py = (event.x - left) / factor, (event.y - top) / factor
            for cx, cy, radius, label in self.preview_regions:
                if (px - cx) ** 2 + (py - cy) ** 2 <= radius ** 2:
                    tooltip = label
                    position = (max(510, min(x + 12, 650)), max(115, min(y + 20, 490)))
                    break
        if tooltip != self._tooltip_text:
            self._hide_tooltip()
            self._tooltip_text = tooltip
            self._tooltip_position = position
        if tooltip:
            if self._tooltip_job is None:
                self._tooltip_job = self.canvas.after(500, self._show_tooltip)
        else:
            self._hide_tooltip()

    def _show_tooltip(self) -> None:
        if not self._tooltip_text:
            return
        self.canvas.delete("tooltip")
        item = self._text(*self._tooltip_position, self._tooltip_text, size=13, width=277, anchor="nw", tags="tooltip")
        box = self.canvas.bbox(item)
        if box:
            rect = self.canvas.create_rectangle(box[0] - 7, box[1] - 5, box[2] + 7, box[3] + 5,
                                                fill="#c6aa80", outline="#60422b", tags="tooltip")
            self.canvas.tag_raise(item, rect)

    def _hide_tooltip(self) -> None:
        self._tooltip_text = ""
        if self._tooltip_job is not None:
            self.canvas.after_cancel(self._tooltip_job)
            self._tooltip_job = None
        if self.canvas.winfo_exists():
            self.canvas.delete("tooltip")

    def _leave(self, _event) -> None:
        self.hover = None
        self._hide_tooltip()
        self.draw()

    def _click(self, event) -> None:
        key = self._hit(event)
        self.canvas.focus_set()
        if key:
            self.focus = key
            self._invoke(key)

    def _invoke(self, key: str) -> None:
        if key in self.actions:
            self.actions[key].invoke()
        elif key == "details":
            self.on_details()
        elif key == "github":
            self.on_github()
        elif key == "resources" and self.on_resources is not None:
            self.on_resources()
        self.draw()

    def _move_focus(self, step: int) -> str:
        keys = [a.key for a in self.actions.values() if a.state == "normal"] + ["details", "github"]
        if self.state == "success" and self.preview is not None and self.on_resources is not None:
            keys.append("resources")
        index = keys.index(self.focus) if self.focus in keys else (-1 if step > 0 else 0)
        self.focus = keys[(index + step) % len(keys)]
        self.draw()
        return "break"

    def _activate_focus(self, _event) -> str:
        if self.focus:
            self._invoke(self.focus)
        return "break"
