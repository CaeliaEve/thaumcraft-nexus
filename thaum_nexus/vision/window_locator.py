from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    rect: tuple[int, int, int, int]
    pid: int | None = None
    process_path: str | None = None

    @property
    def width(self) -> int:
        return max(0, self.rect[2] - self.rect[0])

    @property
    def height(self) -> int:
        return max(0, self.rect[3] - self.rect[1])

    @property
    def process_name(self) -> str:
        if not self.process_path:
            return ""
        return Path(self.process_path).name.lower()


def is_windows() -> bool:
    return sys.platform.startswith("win")


def score_minecraft_window(window: WindowInfo) -> int:
    """Heuristic score for selecting the most likely Minecraft/GTNH window."""

    title = window.title.lower()
    process = window.process_name
    process_path = (window.process_path or "").lower()
    score = 0
    is_java = process in {"javaw.exe", "java.exe"}
    is_likely_browser = process in {
        "chrome.exe",
        "msedge.exe",
        "firefox.exe",
        "brave.exe",
        "opera.exe",
        "vivaldi.exe",
    }

    if is_java:
        score += 120
    if "minecraft" in title:
        score += 100
    if "gt new horizons" in title or "gt: new horizons" in title or "gtnh" in title:
        score += 120
    elif "new horizons" in title:
        score += 60
    if is_java and ("gt" in title or "minecraft" in title or "horizons" in title):
        score += 50
    if "minecraft" in process_path:
        score += 20
    if window.width >= 640 and window.height >= 480:
        score += 10
    # Browser tabs and guides often contain "GTNH" or "Minecraft" in the title;
    # they should not beat the actual Java game window.
    if is_likely_browser:
        score -= 140
    # Down-rank tiny utility windows and invisible placeholders.
    if window.width < 200 or window.height < 150:
        score -= 260
    return score


def locate_minecraft_window() -> WindowInfo | None:
    """Return the best visible Minecraft-like window on Windows."""

    candidates = list_windows()
    scored = [(score_minecraft_window(window), window) for window in candidates]
    scored = [(score, window) for score, window in scored if score > 0]
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1].width * item[1].height), reverse=True)
    return scored[0][1]


def list_windows() -> list[WindowInfo]:
    if not is_windows():
        return []
    user32 = ctypes.windll.user32

    windows: list[WindowInfo] = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not title:
            return True

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_path = _query_process_path(pid.value)
        windows.append(
            WindowInfo(
                hwnd=int(hwnd),
                title=title,
                rect=(int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
                pid=int(pid.value) if pid.value else None,
                process_path=process_path,
            )
        )
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return windows


def _query_process_path(pid: int) -> str | None:
    if not pid or not is_windows():
        return None
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return None
    finally:
        kernel32.CloseHandle(handle)
