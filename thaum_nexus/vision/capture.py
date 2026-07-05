from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .calibration import CalibrationProfile


try:
    from PIL import Image, ImageGrab
except Exception:  # pragma: no cover - depends on optional local GUI stack.
    Image = None  # type: ignore[assignment]
    ImageGrab = None  # type: ignore[assignment]


class ScreenshotUnavailableError(RuntimeError):
    """Raised when the current environment cannot capture the screen."""


class ScreenshotSource(Protocol):
    def capture(self, bbox: tuple[int, int, int, int] | None = None):
        """Capture a screenshot, optionally limited to a screen-space box."""


@dataclass(frozen=True)
class PillowScreenshotSource:
    """Screenshot source backed by Pillow's ImageGrab.

    This keeps the first implementation dependency-light. If ImageGrab is
    unreliable on a user's setup, a later MSS-backed implementation can satisfy
    the same ScreenshotSource protocol.
    """

    def capture(self, bbox: tuple[int, int, int, int] | None = None):
        if ImageGrab is None:
            raise ScreenshotUnavailableError("Pillow ImageGrab is unavailable")
        try:
            image = ImageGrab.grab(bbox=bbox)
        except Exception as exc:  # pragma: no cover - requires real desktop.
            raise ScreenshotUnavailableError(str(exc)) from exc
        return image.convert("RGBA")


def gui_screen_box(
    calibration: CalibrationProfile,
    *,
    base_width: float = 342.0,
    base_height: float = 245.0,
    padding: float = 0.0,
) -> tuple[int, int, int, int]:
    """Return the screen-space box containing the calibrated research GUI."""

    left = calibration.gui_left - padding * calibration.scale
    top = calibration.gui_top - padding * calibration.scale
    right = calibration.gui_left + (base_width + padding) * calibration.scale
    bottom = calibration.gui_top + (base_height + padding) * calibration.scale
    return int(round(left)), int(round(top)), int(round(right)), int(round(bottom))


def capture_gui(source: ScreenshotSource, calibration: CalibrationProfile, *, padding: float = 0.0):
    """Capture only the calibrated GUI rectangle."""

    return source.capture(gui_screen_box(calibration, padding=padding))

