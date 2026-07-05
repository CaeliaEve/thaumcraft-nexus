from __future__ import annotations

import heapq
from dataclasses import dataclass
from itertools import count
from typing import Mapping

from thaum_nexus.data_model import BoardState, CellKind, ConnectionPath, HexCoord, Solution, hex_neighbors
from thaum_nexus.knowledge_base import KnowledgeBase
from thaum_nexus.resources import resource_aware_placement_cost
from thaum_nexus.solver.board import connected_components, root_component_ids


class NoSolutionError(RuntimeError):
    """Raised when the current board cannot be solved with the known aspect graph."""


@dataclass(frozen=True)
class SearchConfig:
    max_iterations: int = 32
    aspect_inventory: Mapping[str, int] | None = None
    zero_inventory_penalty: float = 4.0


def solve(board: BoardState, kb: KnowledgeBase, config: SearchConfig | None = None) -> Solution:
    """Connect all ROOT cells by placing aspects into empty cells."""

    config = config or SearchConfig()
    if len(board.roots) < 2:
        return Solution(placements={}, warnings=("board has fewer than two roots",))

    _validate_board_aspects(board, kb)
    placements: dict[HexCoord, str] = {}
    chosen_paths: list[ConnectionPath] = []

    for _ in range(config.max_iterations):
        components, coord_to_component = connected_components(board, kb, placements)
        root_ids = root_component_ids(board, coord_to_component)
        if len(root_ids) <= 1:
            solution = Solution(
                placements=dict(sorted(placements.items())),
                paths=tuple(chosen_paths),
                cost=sum(path.cost for path in chosen_paths),
            )
            validate_solution(board, kb, solution)
            return solution

        best: ConnectionPath | None = None
        sorted_ids = sorted(root_ids)
        for i, left_id in enumerate(sorted_ids):
            for right_id in sorted_ids[i + 1 :]:
                candidate = find_connection_path(
                    board=board,
                    kb=kb,
                    start_coords=components[left_id],
                    goal_coords=components[right_id],
                    placements=placements,
                    config=config,
                )
                if candidate is None:
                    continue
                if best is None or (candidate.cost, len(candidate.placements), candidate.coords) < (
                    best.cost,
                    len(best.placements),
                    best.coords,
                ):
                    best = candidate

        if best is None:
            raise NoSolutionError("no legal path found between remaining root components")
        if not best.placements:
            raise NoSolutionError("internal solver made no progress while roots remained disconnected")

        for coord, aspect in best.placements.items():
            existing = placements.get(coord)
            if existing is not None and existing != aspect:
                raise NoSolutionError(
                    f"conflicting placement at {coord.key()}: {existing} vs {aspect}"
                )
            placements[coord] = aspect
        chosen_paths.append(best)

    raise NoSolutionError(f"solver exceeded {config.max_iterations} iterations")


def find_connection_path(
    board: BoardState,
    kb: KnowledgeBase,
    start_coords: set[HexCoord],
    goal_coords: set[HexCoord],
    placements: dict[HexCoord, str],
    config: SearchConfig | None = None,
) -> ConnectionPath | None:
    """Dijkstra search over combined board coordinate + aspect states."""

    config = config or SearchConfig()
    starts = sorted(coord for coord in start_coords if board.aspect_at(coord, placements))
    goals = set(goal_coords)
    if not starts or not goals:
        return None

    sequence = count()
    heap: list[tuple[float, int, int, HexCoord, str]] = []
    dist: dict[tuple[HexCoord, str], float] = {}
    parent: dict[tuple[HexCoord, str], tuple[HexCoord, str] | None] = {}

    for coord in starts:
        aspect = board.aspect_at(coord, placements)
        if aspect is None:
            continue
        key = (coord, aspect)
        dist[key] = 0.0
        parent[key] = None
        heapq.heappush(heap, (0.0, 0, next(sequence), coord, aspect))

    while heap:
        cost, steps, _seq, coord, aspect = heapq.heappop(heap)
        key = (coord, aspect)
        if cost != dist.get(key):
            continue
        if coord in goals:
            return _reconstruct_path(board, key, parent, dist[key], placements)

        for neighbor in hex_neighbors(coord):
            cell = board.cell_at(neighbor)
            if cell is None or cell.kind is CellKind.MISSING:
                continue
            for next_aspect, placing_new in _candidate_aspects(board, kb, neighbor, aspect, placements):
                if not kb.can_connect(aspect, next_aspect):
                    continue
                step_cost = (
                    _placement_cost(kb, next_aspect, placements, config)
                    if placing_new
                    else 0.0
                )
                next_key = (neighbor, next_aspect)
                next_cost = cost + step_cost
                if next_cost < dist.get(next_key, float("inf")):
                    dist[next_key] = next_cost
                    parent[next_key] = key
                    heapq.heappush(heap, (next_cost, steps + 1, next(sequence), neighbor, next_aspect))

    return None


def validate_solution(board: BoardState, kb: KnowledgeBase, solution: Solution) -> None:
    for coord, aspect in solution.placements.items():
        cell = board.cell_at(coord)
        if cell is None:
            raise ValueError(f"placement outside board: {coord.key()}")
        if not cell.is_empty:
            raise ValueError(f"placement on non-empty cell: {coord.key()}")
        kb.require_aspect(aspect)

    components, coord_to_component = connected_components(board, kb, solution.placements)
    _ = components  # useful for debugger; coord_to_component is the validation input.
    root_ids = root_component_ids(board, coord_to_component)
    if len(root_ids) != 1:
        raise ValueError(f"solution does not connect all roots; root components={sorted(root_ids)}")


def _candidate_aspects(
    board: BoardState,
    kb: KnowledgeBase,
    coord: HexCoord,
    current_aspect: str,
    placements: dict[HexCoord, str],
) -> tuple[tuple[str, bool], ...]:
    existing = board.aspect_at(coord, placements)
    if existing is not None:
        return ((existing, False),)

    cell = board.cell_at(coord)
    if cell is None or not cell.is_empty:
        return ()

    return tuple((aspect, True) for aspect in kb.direct_neighbors(current_aspect))


def _placement_cost(
    kb: KnowledgeBase,
    aspect: str,
    placements: dict[HexCoord, str],
    config: SearchConfig,
) -> float:
    if config.aspect_inventory is None:
        return kb.placement_cost(aspect)
    reserved: dict[str, int] = {}
    for placed_aspect in placements.values():
        reserved[placed_aspect] = reserved.get(placed_aspect, 0) + 1
    return resource_aware_placement_cost(
        kb,
        aspect,
        config.aspect_inventory,
        reserved,
        zero_inventory_penalty=config.zero_inventory_penalty,
    )


def _reconstruct_path(
    board: BoardState,
    end_key: tuple[HexCoord, str],
    parent: dict[tuple[HexCoord, str], tuple[HexCoord, str] | None],
    cost: float,
    existing_placements: dict[HexCoord, str],
) -> ConnectionPath:
    states: list[tuple[HexCoord, str]] = []
    cursor: tuple[HexCoord, str] | None = end_key
    while cursor is not None:
        states.append(cursor)
        cursor = parent[cursor]
    states.reverse()

    aspects = {coord: aspect for coord, aspect in states}
    placements: dict[HexCoord, str] = {}
    for coord, aspect in states:
        if coord in existing_placements:
            continue
        cell = board.cell_at(coord)
        if cell is not None and cell.is_empty:
            placements[coord] = aspect

    return ConnectionPath(
        coords=tuple(coord for coord, _aspect in states),
        aspects=aspects,
        placements=placements,
        cost=cost,
    )


def _validate_board_aspects(board: BoardState, kb: KnowledgeBase) -> None:
    for cell in board.cells.values():
        if cell.aspect is not None:
            kb.require_aspect(cell.aspect)
