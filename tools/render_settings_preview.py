"""Export actual settings canvas commands; native fields are approximated, not captured."""
import argparse
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from thaum_nexus.gui_app import ThaumNexusGui
from thaum_nexus.settings_book_view import PAGES
from render_logbook_preview import export_canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', default='1024x681')
    parser.add_argument('--output', type=Path, default=ROOT/'build/settings-book-preview')
    args = parser.parse_args()
    root = tk.Tk()
    root.maxsize(4096, 4096)
    root.geometry(args.size)
    app = ThaumNexusGui()
    app.tk = root
    app._configure_style(ttk)
    app._build_layout(tk, ttk)
    app._open_settings()
    editor = app.settings_editor
    try:
        for i, page in enumerate(PAGES):
            editor.show_page(page)
            root.update()
            export_canvas(editor.view, args.output/f'chapter-{i+1}.png')
        editor.show_page('注入节律')
        editor.view.set_preset('custom')
        root.update()
        export_canvas(editor.view, args.output/'custom.png')
    finally:
        editor.cancel()
        root.destroy()


if __name__ == '__main__':
    main()
