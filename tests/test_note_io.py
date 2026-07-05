import json
import unittest
from pathlib import Path

from thaum_nexus import KnowledgeBase
from thaum_nexus.data_model import CellKind, HexCoord
from thaum_nexus.note_io import ResearchNote, board_from_note_dict, load_note_board
from thaum_nexus.solver import solve, validate_solution


FIXTURES = Path(__file__).parent / "fixtures" / "notes"


class NoteIoTests(unittest.TestCase):
    def test_converts_thaumcraft_hexgrid_types_to_board_cells(self):
        payload = json.loads((FIXTURES / "two_roots_line_note.json").read_text(encoding="utf-8"))

        note = ResearchNote.from_dict(payload)

        self.assertEqual(note.research_key, "TEST_NOTE")
        self.assertEqual(note.board.name, "TEST_NOTE")
        self.assertEqual(note.board.cell_at(HexCoord(0, 0)).kind, CellKind.ROOT)
        self.assertEqual(note.board.cell_at(HexCoord(0, 0)).aspect, "aer")
        self.assertEqual(note.board.cell_at(HexCoord(1, 0)).kind, CellKind.EMPTY)
        self.assertEqual(note.board.cell_at(HexCoord(2, 0)).kind, CellKind.ROOT)
        self.assertEqual(note.board.cell_at(HexCoord(2, 0)).aspect, "ignis")

    def test_accepts_short_q_r_keys_and_player_placed_aspects(self):
        board = board_from_note_dict(
            {
                "key": "PLACED",
                "hexgrid": [
                    {"q": 0, "r": 0, "type": 1, "aspect": "aer"},
                    {"q": 1, "r": 0, "type": 2, "aspect": "lux"},
                    {"q": 2, "r": 0, "type": 1, "aspect": "ignis"},
                ],
            }
        )

        self.assertEqual(board.cell_at(HexCoord(1, 0)).kind, CellKind.PLACED)
        self.assertEqual(board.cell_at(HexCoord(1, 0)).aspect, "lux")

    def test_note_board_can_be_solved_from_structured_data(self):
        kb = KnowledgeBase.load()
        board = load_note_board(FIXTURES / "two_roots_line_note.json")

        solution = solve(board, kb)

        self.assertEqual(solution.placements, {HexCoord(1, 0): "lux"})
        validate_solution(board, kb, solution)

    def test_rejects_root_without_aspect(self):
        with self.assertRaisesRegex(ValueError, "requires aspect"):
            board_from_note_dict({"hexgrid": [{"q": 0, "r": 0, "type": 1}]})


if __name__ == "__main__":
    unittest.main()
