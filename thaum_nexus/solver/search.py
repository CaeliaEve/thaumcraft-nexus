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


@dataclass(frozen=True)
class _PathSearchContext:
    aspect_by_coord: dict[HexCoord, str]
    empty_coords: set[HexCoord]
    neighbors_by_coord: dict[HexCoord, tuple[HexCoord, ...]]
    connectable_by_aspect: dict[str, frozenset[str]]
    direct_candidates_by_aspect: dict[str, tuple[tuple[str, bool], ...]]
    placement_cost_by_aspect: dict[str, float]


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
        search_context = _build_path_search_context(board, kb, placements, config)
        sorted_ids = sorted(root_ids)
        for i, left_id in enumerate(sorted_ids):
            for right_id in sorted_ids[i + 1 :]:
                candidate = _find_connection_path(
                    board=board,
                    start_coords=components[left_id],
                    goal_coords=components[right_id],
                    placements=placements,
                    context=search_context,
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
    return _find_connection_path(
        board=board,
        start_coords=start_coords,
        goal_coords=goal_coords,
        placements=placements,
        context=_build_path_search_context(board, kb, placements, config),
    )


def _build_path_search_context(
    board: BoardState,
    kb: KnowledgeBase,
    placements: dict[HexCoord, str],
    config: SearchConfig,
) -> _PathSearchContext:
    cells = board.cells
    placement_aspects = placements
    aspect_by_coord: dict[HexCoord, str] = {}
    empty_coords: set[HexCoord] = set()
    for coord, cell in cells.items():
        placed = placement_aspects.get(coord)
        if placed is not None:
            aspect_by_coord[coord] = placed
        elif cell.aspect is not None:
            aspect_by_coord[coord] = cell.aspect
        if cell.kind is CellKind.EMPTY and placed is None:
            empty_coords.add(coord)

    neighbors_by_coord = {
        coord: tuple(neighbor for neighbor in hex_neighbors(coord) if neighbor in cells)
        for coord in cells
    }
    connectable_by_aspect = {
        aspect: frozenset(neighbors)
        for aspect, neighbors in kb.neighbors.items()
    }
    direct_candidates_by_aspect = {
        aspect: tuple((neighbor, True) for neighbor in neighbors)
        for aspect, neighbors in kb.neighbors.items()
    }

    return _PathSearchContext(
        aspect_by_coord=aspect_by_coord,
        empty_coords=empty_coords,
        neighbors_by_coord=neighbors_by_coord,
        connectable_by_aspect=connectable_by_aspect,
        direct_candidates_by_aspect=direct_candidates_by_aspect,
        placement_cost_by_aspect=_placement_cost_cache(kb, placements, config),
    )


def _find_connection_path(
    board: BoardState,
    start_coords: set[HexCoord],
    goal_coords: set[HexCoord],
    placements: dict[HexCoord, str],
    context: _PathSearchContext,
) -> ConnectionPath | None:
    aspect_by_coord = context.aspect_by_coord
    starts = sorted(coord for coord in start_coords if coord in aspect_by_coord)
    goals = set(goal_coords)
    if not starts or not goals:
        return None

    empty_coords = context.empty_coords
    neighbors_by_coord = context.neighbors_by_coord
    connectable_by_aspect = context.connectable_by_aspect
    direct_candidates_by_aspect = context.direct_candidates_by_aspect
    placement_cost_by_aspect = context.placement_cost_by_aspect
    sequence = count()
    heap: list[tuple[float, int, int, HexCoord, str]] = []
    dist: dict[tuple[HexCoord, str], float] = {}
    parent: dict[tuple[HexCoord, str], tuple[HexCoord, str] | None] = {}

    for coord in starts:
        aspect = aspect_by_coord[coord]
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

        for neighbor in neighbors_by_coord.get(coord, ()):
            existing = aspect_by_coord.get(neighbor)
            connectable = connectable_by_aspect[aspect]
            if existing is not None:
                if existing not in connectable:
                    continue
                candidates = ((existing, False),)
            elif neighbor in empty_coords:
                candidates = direct_candidates_by_aspect[aspect]
            else:
                continue

            for next_aspect, placing_new in candidates:
                step_cost = placement_cost_by_aspect[next_aspect] if placing_new else 0.0
                next_key = (neighbor, next_aspect)
                next_cost = cost + step_cost
                if next_cost < dist.get(next_key, float("inf")):
                    dist[next_key] = next_cost
                    parent[next_key] = key
                    heapq.heappush(heap, (next_cost, steps + 1, next(sequence), neighbor, next_aspect))

    return None


def _placement_cost_cache(
    kb: KnowledgeBase,
    placements: dict[HexCoord, str],
    config: SearchConfig,
) -> dict[str, float]:
    if config.aspect_inventory is None:
        return {aspect: kb.placement_cost(aspect) for aspect in kb.aspects}

    reserved: dict[str, int] = {}
    for placed_aspect in placements.values():
        reserved[placed_aspect] = reserved.get(placed_aspect, 0) + 1

    return {
        aspect: resource_aware_placement_cost(
            kb,
            aspect,
            config.aspect_inventory,
            reserved,
            zero_inventory_penalty=config.zero_inventory_penalty,
        )
        for aspect in kb.aspects
    }


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
