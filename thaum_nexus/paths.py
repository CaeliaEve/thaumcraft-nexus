from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """Return True when running from a PyInstaller-frozen executable."""

    return bool(getattr(sys, "frozen", False))


def source_root() -> Path:
    """Repository root when running from source."""

    return Path(__file__).resolve().parents[1]


def app_root(project_root: Path | str | None = None) -> Path:
    """Writable application root.

    In source mode this is the repository root.  In a PyInstaller one-dir build
    this is the folder containing the EXE, so runtime files are written next to
    the portable application instead of inside PyInstaller's internal resource
    directory.
    """

    if project_root is not None:
        return Path(project_root).resolve()
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return source_root()


def resource_root(project_root: Path | str | None = None) -> Path:
    """Read-only bundled resource root for data, images and packaged assets."""

    if project_root is not None:
        return Path(project_root).resolve()
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)).resolve()
    return source_root()


def runtime_root(project_root: Path | str | None = None) -> Path:
    """Directory for generated JSON, preview images and GUI settings."""

    return app_root(project_root) / "runtime"


def data_dir(project_root: Path | str | None = None) -> Path:
    return resource_root(project_root) / "data"


def image_dir(project_root: Path | str | None = None) -> Path:
    return resource_root(project_root) / "image"


def resource_path(path: Path | str, project_root: Path | str | None = None) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return resource_root(project_root) / candidate
