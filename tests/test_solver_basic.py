import json
import unittest
from pathlib import Path

from thaum_nexus import KnowledgeBase
from thaum_nexus.data_model import BoardState, HexCoord, hex_neighbors
from thaum_nexus.solver import SearchConfig, solve, validate_solution


FIXTURES = Path(__file__).parent / "fixtures" / "boards"


def load_board(name: str) -> BoardState:
    return BoardState.from_dict(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


class SolverBasicTests(unittest.TestCase):
    def test_hex_neighbors_follow_thaumcraft_axial_directions(self):
        self.assertEqual(
            set(hex_neighbors(HexCoord(0, 0))),
            {
                HexCoord(1, 0),
                HexCoord(1, -1),
                HexCoord(0, -1),
                HexCoord(-1, 0),
                HexCoord(-1, 1),
                HexCoord(0, 1),
            },
        )

    def test_solver_connects_two_roots_with_lux(self):
        kb = KnowledgeBase.load()
        board = load_board("two_roots_line.json")

        solution = solve(board, kb)

        self.assertEqual(solution.placements, {HexCoord(1, 0): "lux"})
        validate_solution(board, kb, solution)

    def test_solver_connects_three_roots_with_two_paths(self):
        kb = KnowledgeBase.load()
        board = load_board("three_roots_line.json")

        solution = solve(board, kb)

        self.assertEqual(
            solution.placements,
            {
                HexCoord(1, 0): "lux",
                HexCoord(3, 0): "potentia",
            },
        )
        validate_solution(board, kb, solution)

    def test_resource_aware_solver_prefers_abundant_common_neighbor(self):
        kb = KnowledgeBase.load()
        board = BoardState.from_dict(
            {
                "name": "resource-choice",
                "cells": [
                    {"q": 0, "r": 0, "kind": "root", "aspect": "aer"},
                    {"q": 1, "r": 0, "kind": "empty"},
                    {"q": 2, "r": 0, "kind": "root", "aspect": "praecantatio"},
                ],
            }
        )

        default_solution = solve(board, kb)
        resource_solution = solve(
            board,
            kb,
            SearchConfig(aspect_inventory={"auram": 50, "vacuos": 0}),
        )

        self.assertEqual(default_solution.placements, {HexCoord(1, 0): "vacuos"})
        self.assertEqual(resource_solution.placements, {HexCoord(1, 0): "auram"})
        validate_solution(board, kb, resource_solution)


if __name__ == "__main__":
    unittest.main()
