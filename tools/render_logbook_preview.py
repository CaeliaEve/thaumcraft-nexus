"""Export the app's canvas drawing commands to PNG for offline visual review.

This reads only a locally constructed Tk canvas, never the desktop or a JVM.
Requires Pillow. Rendering fonts match the Windows UI where available.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tkinter as tk
from tkinter import font as tkfont, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from thaum_nexus.gui_app import ThaumNexusGui
from thaum_nexus.data_model import BoardState
from thaum_nexus.solver import solve


def export_canvas(view, output: Path) -> None:
    canvas = view.canvas
    width, height = canvas.winfo_width(), canvas.winfo_height()
    if width <= 1:
        width, height = 1024, 681
    image = Image.new("RGBA", (width, height), "#090705")
    draw = ImageDraw.Draw(image)
    photos = {str(photo): photo for photo in (view._background_photo, view._preview_photo) if photo is not None}
    fonts = Path("C:/Windows/Fonts")
    for item in canvas.find_all():
        kind = canvas.type(item)
        coords = canvas.coords(item)
        if kind == "image":
            source = ImageTk.getimage(photos[canvas.itemcget(item, "image")])
            x, y = coords
            if canvas.itemcget(item, "anchor") == "center":
                x, y = x - source.width / 2, y - source.height / 2
            image.alpha_composite(source, (round(x), round(y)))
        elif kind == "line":
            color = canvas.itemcget(item, "fill")
            dash = canvas.itemcget(item, "dash")
            if dash:
                x1, y1, x2, y2 = coords
                for x in range(round(x1), round(x2), max(3, round(5 * view.scale))):
                    draw.point((x, round(y1)), fill=color)
            else:
                draw.line(coords, fill=color, width=max(1, round(float(canvas.itemcget(item, "width")))))
        elif kind == "text":
            tk_font = tkfont.nametofont(canvas.itemcget(item, "font"), root=canvas)
            config = tk_font.actual()
            filename = "georgiai.ttf" if config['slant'] == 'italic' else "georgia.ttf"
            if config['family'].lower() != 'georgia':
                filename = "simsun.ttc"
            configured_size = tk_font.cget('size')
            size = abs(configured_size) if configured_size < 0 else round(configured_size * float(canvas.tk.call('tk', 'scaling')))
            font = ImageFont.truetype(str(fonts / filename), size=size)
            text = canvas.itemcget(item, "text")
            max_width = float(canvas.itemcget(item, "width"))
            if max_width:
                lines, line = [], ""
                for char in text:
                    if char == '\n' or font.getlength(line + char) > max_width:
                        lines.append(line)
                        line = '' if char == '\n' else char
                    else:
                        line += char
                text = '\n'.join(lines + [line])
            anchor = {"w": "lm", "e": "rm", "center": "mm", "n": "mt", "nw": "lt"}[canvas.itemcget(item, "anchor")]
            draw.text(tuple(coords), text, font=font, fill=canvas.itemcget(item, "fill"),
                      anchor=anchor, align="center" if max_width else "left", spacing=4)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output)


def sample_board() -> BoardState:
    radius = 3
    roots = {(-3, 0): "aer", (3, 0): "ignis", (0, -3): "ordo", (0, 3): "terra"}
    cells = []
    for q in range(-radius, radius + 1):
        for r in range(max(-radius, -q-radius), min(radius, -q+radius) + 1):
            aspect = roots.get((q, r))
            cells.append({"q": q, "r": r, "kind": "root" if aspect else "empty",
                          **({"aspect": aspect} if aspect else {})})
    return BoardState.from_dict({"name": "基础要素研究", "cells": cells})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "logbook-previews")
    parser.add_argument("--size", default="1024x681", help="Canvas size, for example 1440x900")
    args = parser.parse_args()
    root = tk.Tk()
    root.withdraw()
    root.geometry(args.size)
    gui = ThaumNexusGui()
    gui.tk = root
    gui._configure_style(ttk)
    gui._build_layout(tk, ttk)
    # Let Tk resolve geometry for this locally constructed canvas; no screen capture.
    root.deiconify()
    root.update()
    root.withdraw()
    try:
        export_canvas(gui.logbook, args.output / "idle.png")
        board = sample_board()
        solution = solve(board, gui.kb)
        gui.note_name.set("笔记：基础要素研究")
        gui.placement_count.set(f"放置：{len(solution.placements)}")
        gui.logbook.set_page("success", preview=gui.board_renderer.render(board, solution, paper=True))
        gui.worker_label.set("状态：完成")
        gui.buttons['save'].configure(state='normal')
        gui._set_status(f"读取完成，需要放置 {len(solution.placements)} 个要素。")
        export_canvas(gui.logbook, args.output / "success.png")
        gui._set_busy_ui("第 3 / 12 张", cancellable=True)
        gui._set_status("正在合成要素，等待研究台确认。")
        export_canvas(gui.logbook, args.output / "busy.png")
        gui.logbook.set_page('error', '未找到研究台，请打开研究台后重试。')
        gui._finish_worker_ui()
        gui._set_status('读取失败，请查看详情。')
        export_canvas(gui.logbook, args.output / "error.png")
        gui.logbook.set_page('cancelled', '已停止当前操作，可以重新读取笔记。')
        gui._finish_worker_ui()
        gui._set_status('任务已停止。')
        export_canvas(gui.logbook, args.output / "cancelled.png")
        print(args.output)
    finally:
        root.destroy()


if __name__ == '__main__':
    main()
