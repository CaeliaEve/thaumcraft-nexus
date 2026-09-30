import json
import unittest
from pathlib import Path

from thaum_nexus import KnowledgeBase
from thaum_nexus.data_model import BoardState, HexCoord, hex_neighbors
from thaum_nexus.solver import SearchConfig, solve, validate_solution


FIXTURES = Path(__file__).parent / "fixtures" / "boards"


def load_board(name: str) -> BoardState:
    return BoardState.from_dict(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def radius_board(radius: int = 4) -> BoardState:
    cells = []
    for q in range(-radius, radius + 1):
        r_min = max(-radius, -q - radius)
        r_max = min(radius, -q + radius)
        for r in range(r_min, r_max + 1):
            cells.append({"q": q, "r": r, "kind": "empty"})
    roots = {
        (-radius, 0): "aer",
        (radius, 0): "ignis",
        (0, -radius): "ordo",
        (0, radius): "terra",
    }
    for cell in cells:
        aspect = roots.get((cell["q"], cell["r"]))
        if aspect:
            cell["kind"] = "root"
            cell["aspect"] = aspect
    return BoardState.from_dict({"name": "radius-board", "cells": cells})


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

    def test_minimal_placement_mode_uses_inventory_only_for_equal_length_paths(self):
        kb = KnowledgeBase.load()
        board = BoardState.from_dict(
            {
                "name": "minimal-resource-choice",
                "cells": [
                    {"q": 0, "r": 0, "kind": "root", "aspect": "aer"},
                    {"q": 1, "r": 0, "kind": "empty"},
                    {"q": 2, "r": 0, "kind": "root", "aspect": "praecantatio"},
                ],
            }
        )

        solution = solve(
            board,
            kb,
            SearchConfig(
                aspect_inventory={"auram": 50, "vacuos": 0},
                minimize_placements=True,
            ),
        )

        self.assertEqual(solution.placements, {HexCoord(1, 0): "auram"})
        validate_solution(board, kb, solution)

    def test_minimal_placement_mode_balances_primal_aspects_by_remaining_stock(self):
        kb = KnowledgeBase.load()
        board = BoardState.from_dict(
            {
                "name": "balanced-primal-choice",
                "cells": [
                    {"q": 0, "r": 0, "kind": "root", "aspect": "lux"},
                    {"q": 1, "r": 0, "kind": "empty"},
                    {"q": 2, "r": 0, "kind": "root", "aspect": "lux"},
                ],
            }
        )

        ignis_solution = solve(
            board,
            kb,
            SearchConfig(
                aspect_inventory={"aer": 2, "ignis": 20},
                minimize_placements=True,
            ),
        )
        aer_solution = solve(
            board,
            kb,
            SearchConfig(
                aspect_inventory={"aer": 20, "ignis": 2},
                minimize_placements=True,
            ),
        )
        equal_solution = solve(
            board,
            kb,
            SearchConfig(
                aspect_inventory={"aer": 10, "ignis": 10},
                minimize_placements=True,
            ),
        )

        self.assertEqual(ignis_solution.placements, {HexCoord(1, 0): "ignis"})
        self.assertEqual(aer_solution.placements, {HexCoord(1, 0): "aer"})
        self.assertEqual(equal_solution.placements, {HexCoord(1, 0): "ignis"})
        validate_solution(board, kb, ignis_solution)
        validate_solution(board, kb, aer_solution)
        validate_solution(board, kb, equal_solution)

    def test_minimal_placement_mode_can_select_every_abundant_primal_aspect(self):
        kb = KnowledgeBase.load()
        cases = {
            "aer": ("lux", "ignis"),
            "aqua": ("victus", "terra"),
            "ignis": ("lux", "aer"),
            "ordo": ("potentia", "ignis"),
            "perditio": ("vacuos", "aer"),
            "terra": ("victus", "aqua"),
        }

        for preferred, (root_aspect, alternate) in cases.items():
            with self.subTest(preferred=preferred):
                board = BoardState.from_dict(
                    {
                        "name": f"abundant-{preferred}",
                        "cells": [
                            {"q": 0, "r": 0, "kind": "root", "aspect": root_aspect},
                            {"q": 1, "r": 0, "kind": "empty"},
                            {"q": 2, "r": 0, "kind": "root", "aspect": root_aspect},
                        ],
                    }
                )
                inventory = {aspect: 5 for aspect in kb.primal}
                inventory[preferred] = 20
                inventory[alternate] = 2

                solution = solve(
                    board,
                    kb,
                    SearchConfig(
                        aspect_inventory=inventory,
                        minimize_placements=True,
                    ),
                )

                self.assertEqual(solution.placements, {HexCoord(1, 0): preferred})
                validate_solution(board, kb, solution)

    def test_minimal_placement_mode_compares_root_connection_orders(self):
        kb = KnowledgeBase.load()
        radius = 2
        roots = {
            (-2, 1): "volatus",
            (-1, -1): "superbia",
            (-1, 2): "strontio",
        }
        cells = []
        for q in range(-radius, radius + 1):
            r_min = max(-radius, -q - radius)
            r_max = min(radius, -q + radius)
            for r in range(r_min, r_max + 1):
                aspect = roots.get((q, r))
                cells.append(
                    {"q": q, "r": r, "kind": "root", "aspect": aspect}
                    if aspect is not None
                    else {"q": q, "r": r, "kind": "empty"}
                )
        board = BoardState.from_dict({"name": "connection-order-choice", "cells": cells})

        solution = solve(board, kb, SearchConfig(minimize_placements=True))

        self.assertEqual(len(solution.placements), 3)
        validate_solution(board, kb, solution)

    def test_minimal_placement_mode_uses_inventory_only_as_search_hint(self):
        kb = KnowledgeBase.load()
        radius = 2
        roots = {
            (0, -1): "terra",
            (0, 1): "infernus",
            (1, -2): "machina",
        }
        cells = []
        for q in range(-radius, radius + 1):
            r_min = max(-radius, -q - radius)
            r_max = min(radius, -q + radius)
            for r in range(r_min, r_max + 1):
                aspect = roots.get((q, r))
                cells.append(
                    {"q": q, "r": r, "kind": "root", "aspect": aspect}
                    if aspect is not None
                    else {"q": q, "r": r, "kind": "empty"}
                )
        board = BoardState.from_dict({"name": "inventory-search-hint", "cells": cells})
        inventory = {
            "tutamen": 50,
            "ignis": 50,
            "instrumentum": 50,
            "telum": 50,
        }

        solution = solve(
            board,
            kb,
            SearchConfig(aspect_inventory=inventory, minimize_placements=True),
        )

        self.assertEqual(len(solution.placements), 4)
        validate_solution(board, kb, solution)

    def test_minimal_placement_mode_finds_shared_two_cell_global_solution(self):
        kb = KnowledgeBase.load()
        radius = 2
        roots = {
            (-1, -1): "instrumentum",
            (-1, 1): "sano",
            (0, 2): "terra",
            (1, 0): "bestia",
        }
        cells = []
        for q in range(-radius, radius + 1):
            r_min = max(-radius, -q - radius)
            r_max = min(radius, -q + radius)
            for r in range(r_min, r_max + 1):
                aspect = roots.get((q, r))
                cells.append(
                    {"q": q, "r": r, "kind": "root", "aspect": aspect}
                    if aspect is not None
                    else {"q": q, "r": r, "kind": "empty"}
                )
        board = BoardState.from_dict({"name": "shared-global-solution", "cells": cells})

        solution = solve(board, kb, SearchConfig(minimize_placements=True))

        self.assertEqual(
            solution.placements,
            {
                HexCoord(-1, 0): "ordo",
                HexCoord(0, 1): "victus",
            },
        )
        validate_solution(board, kb, solution)

    def test_large_board_solution_regression(self):
        kb = KnowledgeBase.load()
        board = radius_board(4)

        default_solution = solve(board, kb)
        resource_solution = solve(
            board,
            kb,
            SearchConfig(aspect_inventory={aspect: 10 for aspect in kb.aspects}),
        )

        self.assertEqual(
            {coord.key(): aspect for coord, aspect in sorted(default_solution.placements.items())},
            {
                "-3,-1": "lux",
                "-2,-2": "aer",
                "-2,-1": "aer",
                "-1,-3": "motus",
                "-1,-1": "lux",
                "0,-1": "aer",
                "1,-1": "lux",
                "1,3": "vitreus",
                "2,-1": "aer",
                "2,2": "ordo",
                "3,-1": "lux",
                "3,0": "ignis",
                "3,1": "potentia",
            },
        )
        self.assertEqual(
            {coord.key(): aspect for coord, aspect in sorted(resource_solution.placements.items())},
            {
                "-3,-1": "lux",
                "-2,-2": "aer",
                "-2,-1": "ignis",
                "-1,-3": "motus",
                "-1,-1": "gelum",
                "0,-1": "ignis",
                "1,-1": "gelum",
                "1,3": "vitreus",
                "2,-1": "ignis",
                "2,2": "ordo",
                "3,-1": "gelum",
                "3,0": "ignis",
                "3,1": "potentia",
            },
        )
        validate_solution(board, kb, default_solution)
        validate_solution(board, kb, resource_solution)

class SolverCancellationTests(unittest.TestCase):
    def test_cancel_during_real_search_stops_both_modes(self):
        # Removing checks inside the heap loop makes this return a solution.
        for minimal in (False, True):
            with self.subTest(minimal=minimal):
                checks = 0
                def cancelled():
                    nonlocal checks
                    checks += 1
                    return checks >= 20
                try:
                    solve(radius_board(4), KnowledgeBase.load(), SearchConfig(
                        minimize_placements=minimal, cancel_check=cancelled))
                except RuntimeError as exc:
                    self.assertEqual(type(exc).__name__, 'SolverCancelled')
                else:
                    self.fail('search ignored cancellation')
                self.assertEqual(checks, 20)

    def test_bridge_maps_search_cancellation_to_operation_cancelled(self):
        from unittest.mock import patch
        from thaum_nexus import client_bridge
        checks = 0
        class StopEvent:
            def is_set(self):
                nonlocal checks
                checks += 1
                return checks >= 20
        payload = radius_board(4).to_dict()
        with patch.object(client_bridge, 'export_current_note',
                          return_value=(payload, Path('unused.json'), '', '')):
            with self.assertRaises(client_bridge.OperationCancelled):
                client_bridge.read_and_solve_current_note(Path('.'), stop_event=StopEvent())

class SolverSeedRecoveryTests(unittest.TestCase):
    def test_minimal_search_recovers_when_first_greedy_strategy_gets_stuck(self):
        # Aborting on the first seed discards a valid five-placement alternative.
        roots = {(-2, 2): 'tempus', (-1, 2): 'perfodio',
                 (0, 2): 'telum', (2, -2): 'permutatio'}
        cells = [dict(q=q, r=r, kind='root', aspect=roots[q, r])
                 if (q, r) in roots else dict(q=q, r=r, kind='empty')
                 for q in range(-2, 3) for r in range(-2, 3) if abs(q+r) <= 2]
        board = BoardState.from_dict({'name': 'seed-recovery', 'cells': cells})
        kb = KnowledgeBase.load()
        solution = solve(board, kb, SearchConfig(minimize_placements=True))
        validate_solution(board, kb, solution)
        self.assertLessEqual(len(solution.placements), 5)


if __name__ == "__main__":
    unittest.main()
