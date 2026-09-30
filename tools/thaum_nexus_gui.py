#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


if not getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

from thaum_nexus.gui_app import main


def self_test() -> int:
    import tkinter as tk
    from PIL import Image
    from thaum_nexus.client_bridge import agent_jar_path
    from thaum_nexus.knowledge_base import KnowledgeBase
    from thaum_nexus.logbook_view import LogbookView
    from thaum_nexus.paths import resource_root

    root = resource_root()
    kb = KnowledgeBase.load(root)
    if len(kb.aspects) < 1:
        raise RuntimeError("knowledge base is empty")
    icon = root / "image" / "icons8-github-50.png"
    if not icon.exists():
        raise RuntimeError(f"missing GUI icon: {icon}")
    with Image.open(icon) as image:
        image.load()
    jar = agent_jar_path(root)
    if not jar.exists():
        raise RuntimeError(f"missing Java Agent jar: {jar}")
    # Instantiate only the presentation layer: no bridge calls, workers or settings writes.
    window = tk.Tk()
    window.withdraw()
    callback_errors = []
    window.report_callback_exception = lambda *error: callback_errors.append(error)
    try:
        view = LogbookView(window, root / "image/thaumonomicon_bg_clean.png", [], lambda: None, lambda: None)
        window.update_idletasks()
        view.draw()
        window.update()
        if not any(view.canvas.type(item) == "image" for item in view.canvas.find_all()):
            raise RuntimeError("GUI self-test did not render a background image")
        if callback_errors:
            raise RuntimeError(f"GUI self-test callback failed: {callback_errors[0][1]}")
    finally:
        window.destroy()
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(main())
