"""Version information shared by source runs and portable releases."""
from __future__ import annotations

import json
from pathlib import Path

from .paths import resource_root

VERSION = "0.1.0.dev0"


def get_build_info(root: Path | None = None) -> dict:
    try:
        info = json.loads(((root or resource_root()) / "build-info.json").read_text(encoding="utf-8"))
        if not isinstance(info, dict) or not all(isinstance(info.get(k), str) for k in ("version", "commit")):
            raise ValueError("Invalid build metadata")
        return info
    except (OSError, ValueError):
        return {"version": VERSION, "commit": "unknown", "dirty": False}


def get_version_label(root: Path | None = None) -> str:
    info = get_build_info(root)
    suffix = "+dirty" if info.get("dirty") else ""
    return f"{info['version']} ({info['commit'][:12]}{suffix})"
