import json
import unittest
from pathlib import Path

from thaum_nexus import KnowledgeBase
from thaum_nexus.note_io import ResearchNote
from thaum_nexus.overlay import BoardImageRenderer
from thaum_nexus.solver import solve
from thaum_nexus.vision.aspect_matcher import Image


FIXTURE = Path(__file__).parent / "fixtures" / "notes" / "two_roots_line_note.json"


@unittest.skipIf(Image is None, "Pillow is not installed")
class BoardImageRendererTests(unittest.TestCase):
    def test_renders_structured_note_solution_without_screenshot(self):
        kb = KnowledgeBase.load()
        note = ResearchNote.from_dict(json.loads(FIXTURE.read_text(encoding="utf-8")))
        solution = solve(note.board, kb)

        image = BoardImageRenderer(kb).render(note.board, solution)

        self.assertGreaterEqual(image.width, 520)
        self.assertGreaterEqual(image.height, 340)
        self.assertEqual(image.mode, "RGBA")


if __name__ == "__main__":
    unittest.main()
