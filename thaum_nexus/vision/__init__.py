"""Vision helpers for external screenshot-based solving."""

from .aspect_matcher import AspectMatch, AspectMatcher
from .board_reader import AutoBoardReadConfig, BoardReadConfig, BoardReadError, BoardReadResult, BoardReader
from .calibration import CalibrationProfile
from .capture import PillowScreenshotSource, ScreenshotUnavailableError, gui_screen_box
from .hex_detector import HexPresence, HexPresenceDetector
from .hex_geometry import DEFAULT_GRID_GEOMETRY, HexGridGeometry
from .window_locator import WindowInfo, locate_minecraft_window, score_minecraft_window

__all__ = [
    "AspectMatch",
    "AspectMatcher",
    "AutoBoardReadConfig",
    "BoardReadConfig",
    "BoardReadError",
    "BoardReadResult",
    "BoardReader",
    "CalibrationProfile",
    "DEFAULT_GRID_GEOMETRY",
    "HexGridGeometry",
    "HexPresence",
    "HexPresenceDetector",
    "WindowInfo",
    "PillowScreenshotSource",
    "ScreenshotUnavailableError",
    "gui_screen_box",
    "locate_minecraft_window",
    "score_minecraft_window",
]
