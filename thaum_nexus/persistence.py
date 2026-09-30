"""Settings persistence that leaves existing files intact on failure."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .diagnostics import Diagnostic


def atomic_write_json(path: Path | str, payload: Any) -> None:
    path = Path(path)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # Preserve the original write/replace exception if cleanup is denied.
                pass


def read_settings_json(path: Path | str) -> tuple[dict[str, Any], Diagnostic | None]:
    """Return saved values, or caller defaults ({}) and an optional warning.

    Invalid/unreadable files are never changed. A missing file is normal on first run.
    """
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("settings JSON must contain an object")
        return payload, None
    except FileNotFoundError:
        return {}, None
    except (ValueError, UnicodeError) as exc:
        details = f"{path}\n{type(exc).__name__}: {exc}"
        code, title = "settings_invalid", "设置文件格式损坏"
        advice = "已使用默认设置，原文件已保留。请备份并检查原文件后再保存设置。"
    except PermissionError as exc:
        details = f"{path}\n{type(exc).__name__}: {exc}"
        code, title = "settings_permission", "没有权限读取设置"
        advice = "已使用默认设置。检查设置文件权限或占用情况，原文件未修改。"
    except OSError as exc:
        details = f"{path}\n{type(exc).__name__}: {exc}"
        code, title = "settings_read_error", "设置文件读取失败"
        advice = "已使用默认设置。检查磁盘与设置路径，原文件未修改。"
    return {}, Diagnostic(code, title, advice, details)
