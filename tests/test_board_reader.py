import unittest
from pathlib import Path

from thaum_nexus import KnowledgeBase
from thaum_nexus.data_model import CellKind, HexCoord
from thaum_nexus.solver import solve, validate_solution
from thaum_nexus.vision import (
    AutoBoardReadConfig,
    AspectMatcher,
    BoardReadConfig,
    BoardReader,
    CalibrationProfile,
    DEFAULT_GRID_GEOMETRY,
    HexPresenceDetector,
)
from thaum_nexus.vision.aspect_matcher import Image


@unittest.skipIf(Image is None, "Pillow is not installed")
class BoardReaderTests(unittest.TestCase):
    def test_reader_builds_board_state_from_synthetic_full_screenshot(self):
        kb = KnowledgeBase.load()
        matcher = AspectMatcher.load(kb)
        reader = BoardReader(kb, matcher)
        profile = CalibrationProfile(gui_left=100, gui_top=200, scale=1.0)
        screenshot = Image.new("RGBA", (500, 500), (0, 0, 0, 0))

        self._paste_icon(kb, screenshot, "aer", HexCoord(0, 0), profile, size=18)
        self._paste_icon(kb, screenshot, "ignis", HexCoord(2, 0), profile, size=18)

        config = BoardReadConfig.from_iterables(
            [HexCoord(0, 0), HexCoord(1, 0), HexCoord(2, 0)],
            root_coords=[HexCoord(0, 0), HexCoord(2, 0)],
            match_threshold=0.85,
            crop_radius=9,
        )

        result = reader.read(screenshot, profile, config, name="synthetic")

        self.assertEqual(result.board.cells[HexCoord(0, 0)].kind, CellKind.ROOT)
        self.assertEqual(result.board.cells[HexCoord(0, 0)].aspect, "aer")
        self.assertEqual(result.board.cells[HexCoord(1, 0)].kind, CellKind.EMPTY)
        self.assertEqual(result.board.cells[HexCoord(2, 0)].aspect, "ignis")
        solution = solve(result.board, kb)
        self.assertEqual(solution.placements, {HexCoord(1, 0): "lux"})
        validate_solution(result.board, kb, solution)

    def test_auto_reader_detects_present_cells_and_filters_missing_candidates(self):
        from PIL import ImageDraw

        kb = KnowledgeBase.load()
        matcher = AspectMatcher.load(kb)
        reader = BoardReader(kb, matcher)
        gui_image = Image.new("RGBA", (342, 245), (0, 0, 0, 0))
        draw = ImageDraw.Draw(gui_image)
        middle_hex = DEFAULT_GRID_GEOMETRY.hex_polygon_gui(HexCoord(1, 0), radius=8)
        draw.line([*middle_hex, middle_hex[0]], fill=(180, 120, 60, 255), width=2)
        self._paste_icon(kb, gui_image, "aer", HexCoord(0, 0), CalibrationProfile(0, 0, 1), size=18)
        self._paste_icon(kb, gui_image, "ignis", HexCoord(2, 0), CalibrationProfile(0, 0, 1), size=18)

        config = AutoBoardReadConfig.from_iterables(
            search_coords=[HexCoord(0, 0), HexCoord(1, 0), HexCoord(2, 0), HexCoord(4, 0)],
            root_coords=[HexCoord(0, 0), HexCoord(2, 0)],
            match_threshold=0.85,
            icon_crop_radius=9,
            presence_crop_radius=9,
        )

        result = reader.read_gui_image_auto(
            gui_image,
            config,
            detector=HexPresenceDetector(min_score=0.06),
        )

        self.assertEqual(set(result.board.cells), {HexCoord(0, 0), HexCoord(1, 0), HexCoord(2, 0)})
        self.assertNotIn(HexCoord(4, 0), result.board.cells)
        self.assertFalse(result.presence[HexCoord(4, 0)].present)
        self.assertEqual(result.board.cells[HexCoord(1, 0)].kind, CellKind.EMPTY)
        solution = solve(result.board, kb)
        self.assertEqual(solution.placements, {HexCoord(1, 0): "lux"})
        validate_solution(result.board, kb, solution)

    def test_reader_can_read_gui_cropped_image(self):
        kb = KnowledgeBase.load()
        matcher = AspectMatcher.load(kb)
        reader = BoardReader(kb, matcher)
        gui_image = Image.new("RGBA", (342, 245), (0, 0, 0, 0))

        self._paste_icon(kb, gui_image, "aqua", HexCoord(0, 0), CalibrationProfile(0, 0, 1))

        config = BoardReadConfig.from_iterables(
            [HexCoord(0, 0)],
            root_coords=[HexCoord(0, 0)],
            match_threshold=0.99,
            crop_radius=32,
        )

        result = reader.read_gui_image(gui_image, config)

        self.assertEqual(result.board.cells[HexCoord(0, 0)].kind, CellKind.ROOT)
        self.assertEqual(result.board.cells[HexCoord(0, 0)].aspect, "aqua")

    def _paste_icon(
        self,
        kb,
        screenshot,
        aspect_key: str,
        coord: HexCoord,
        profile: CalibrationProfile,
        *,
        size: int | None = None,
    ) -> None:
        icon = Image.open(Path(kb.aspects[aspect_key].icon)).convert("RGBA")
        if size is not None:
            icon = icon.resize((size, size), Image.Resampling.LANCZOS)
        x, y = DEFAULT_GRID_GEOMETRY.axial_to_screen(coord, profile)
        screenshot.paste(icon, (round(x - icon.width / 2), round(y - icon.height / 2)))


if __name__ == "__main__":
    unittest.main()
