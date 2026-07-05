from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json


@dataclass(frozen=True)
class CalibrationProfile:
    """Screen-space calibration for the GTNH research-table GUI.

    The base GUI coordinates are the 342x245 texture-space coordinates used by
    thaumcraft-research-tweaks. A profile maps those base coordinates into
    current screen pixels.
    """

    gui_left: float
    gui_top: float
    scale: float = 1.0
    profile_name: str = "default"
    window_title: str = "Minecraft"

    @classmethod
    def from_gui_rect(
        cls,
        left: float,
        top: float,
        right: float,
        bottom: float,
        *,
        base_width: float = 342.0,
        base_height: float = 245.0,
        profile_name: str = "default",
        window_title: str = "Minecraft",
    ) -> "CalibrationProfile":
        """Create a profile from a user-selected GUI bounding rectangle.

        Width and height can be slightly inconsistent because of manual
        selection. We average both scale estimates to reduce hand-selection
        noise.
        """

        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            raise ValueError("GUI rectangle must have positive width and height")
        scale_x = width / base_width
        scale_y = height / base_height
        return cls(
            gui_left=float(left),
            gui_top=float(top),
            scale=(scale_x + scale_y) / 2.0,
            profile_name=profile_name,
            window_title=window_title,
        )

    def gui_to_screen(self, x: float, y: float) -> tuple[float, float]:
        return self.gui_left + self.scale * x, self.gui_top + self.scale * y

    def screen_to_gui(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.gui_left) / self.scale, (y - self.gui_top) / self.scale

    def to_dict(self) -> dict[str, Any]:
        return {
            "gui_left": self.gui_left,
            "gui_top": self.gui_top,
            "scale": self.scale,
            "profile_name": self.profile_name,
            "window_title": self.window_title,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CalibrationProfile":
        return cls(
            gui_left=float(payload["gui_left"]),
            gui_top=float(payload["gui_top"]),
            scale=float(payload.get("scale", 1.0)),
            profile_name=payload.get("profile_name", "default"),
            window_title=payload.get("window_title", "Minecraft"),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "CalibrationProfile":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

