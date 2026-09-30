import json
import unittest
from dataclasses import replace
from pathlib import Path

from thaum_nexus import KnowledgeBase
from thaum_nexus.note_io import ResearchNote
from thaum_nexus.overlay import BoardImageRenderer
from thaum_nexus.solver import solve
from thaum_nexus.data_model import HexCoord, hex_neighbors

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]


FIXTURE = Path(__file__).parent / "fixtures" / "notes" / "two_roots_line_note.json"


@unittest.skipIf(Image is None, "Pillow is not installed")
class BoardImageRendererTests(unittest.TestCase):
    def test_renders_structured_note_solution_preview(self):
        kb = KnowledgeBase.load()
        note = ResearchNote.from_dict(json.loads(FIXTURE.read_text(encoding="utf-8")))
        solution = solve(note.board, kb)

        image = BoardImageRenderer(kb).render(note.board, solution)

        self.assertGreaterEqual(image.width, 520)
        self.assertGreaterEqual(image.height, 340)
        self.assertEqual(image.mode, "RGBA")

    def test_paper_preview_has_transparent_background_and_visible_aspects(self):
        kb = KnowledgeBase.load()
        note = ResearchNote.load(FIXTURE)
        solution = solve(note.board, kb)
        try:
            image = BoardImageRenderer(kb).render(note.board, solution, paper=True)
        except TypeError as exc:
            self.fail(f"Paper preview mode is unavailable: {exc}")
        alpha = image.getchannel("A")
        self.assertEqual(image.getpixel((0, 0))[3], 0)
        self.assertEqual(image.getpixel((image.width - 1, image.height - 1))[3], 0)
        self.assertIsNotNone(alpha.getbbox())
        self.assertGreater(alpha.histogram()[255], 100)
        # Extra transparent margins must not push the diagram out of its page.
        left, top, right, bottom = alpha.getbbox()
        self.assertLess(abs(left - (image.width - right)), 20)
        self.assertLess(abs(top - (image.height - bottom)), 20)

    def test_standalone_export_keeps_opaque_background(self):
        kb = KnowledgeBase.load()
        note = ResearchNote.load(FIXTURE)
        image = BoardImageRenderer(kb).render(note.board, solve(note.board, kb))
        self.assertEqual(image.getpixel((0, 0)), (5, 5, 5, 255))

    def test_paper_connection_paths_remain_visible_above_hexagons(self):
        kb = KnowledgeBase.load()
        note = ResearchNote.load(FIXTURE)
        solution = solve(note.board, kb)
        self.assertTrue(solution.paths)
        renderer = BoardImageRenderer(kb)
        with_paths = renderer.render(note.board, solution, paper=True)
        without_paths = renderer.render(note.board, replace(solution, paths=()), paper=True)
        self.assertTrue(with_paths.tobytes() != without_paths.tobytes(),
                        "Connection paths must change the visible preview")

    def test_adjacent_hexagons_share_an_edge_instead_of_overlapping(self):
        renderer = BoardImageRenderer(KnowledgeBase.load())
        corners = lambda coord: {(round(x, 4), round(y, 4)) for x, y in
                                 renderer._hex_points(renderer._axial_to_raw(coord))}
        origin = HexCoord(0, 0)
        for neighbor in hex_neighbors(origin):
            with self.subTest(neighbor=neighbor):
                self.assertEqual(len(corners(origin) & corners(neighbor)), 2)


if __name__ == "__main__":
    unittest.main()
