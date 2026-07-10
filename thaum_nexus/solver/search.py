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
    minimize_placements: bool = False
    optimal_search_state_limit: int = 96


@dataclass(frozen=True)
class _StaticPathSearchContext:
    neighbors_by_coord: dict[HexCoord, tuple[HexCoord, ...]]
    connectable_by_aspect: dict[str, frozenset[str]]
    direct_candidates_by_aspect: dict[str, tuple[tuple[str, bool], ...]]


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
    if config.minimize_placements:
        return _solve_minimal_placements(board, kb, config)
    return _solve_greedy(board, kb, config)


def _solve_greedy(board: BoardState, kb: KnowledgeBase, config: SearchConfig) -> Solution:
    placements: dict[HexCoord, str] = {}
    chosen_paths: list[ConnectionPath] = []
    static_context = _build_static_path_search_context(board, kb)

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
        search_context = _build_path_search_context(
            board,
            kb,
            placements,
            config,
            static_context=static_context,
        )
        sorted_ids = sorted(root_ids)
        for i, left_id in enumerate(sorted_ids):
            targets = {
                right_id: components[right_id]
                for right_id in sorted_ids[i + 1 :]
            }
            candidates = _find_connection_paths(
                board=board,
                start_coords=components[left_id],
                goal_coords_by_id=targets,
                placements=placements,
                context=search_context,
                max_cost=best.cost if best is not None else None,
            )
            for right_id in sorted(targets):
                candidate = candidates.get(right_id)
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


def _solve_minimal_placements(
    board: BoardState,
    kb: KnowledgeBase,
    config: SearchConfig,
) -> Solution:
    """Search several global connection strategies and keep the fewest cells.

    Exact Steiner-tree search over every coordinate/aspect assignment is too
    expensive for normal research-note boards.  This bounded search improves
    on the old single-pass greedy behavior by comparing all root-component
    connection orders and several deterministic path-diversification hints.
    Inventory is only a search hint; final candidates are always ranked by
    total placement count first.
    """

    candidates = [_solve_greedy(board, kb, config)]
    for candidate_config in _minimal_candidate_configs(kb, config):
        try:
            candidates.append(_solve_greedy(board, kb, candidate_config))
        except NoSolutionError:
            continue

    best = min(candidates, key=lambda solution: _minimal_solution_key(kb, solution.placements))
    best, exhausted = _search_connection_orders(
        board,
        kb,
        config,
        initial_best=best,
    )
    warnings = list(best.warnings)
    if exhausted:
        warnings.append("minimal-placement search budget reached; returned the best candidate found")

    placements = dict(sorted(best.placements.items()))
    max_depth = max((kb.aspect_depth(aspect) for aspect in kb.aspects), default=0)
    tie_breaker = 1.0 / ((max_depth + 1) * (max(1, len(board.cells)) + 1))
    normalized_paths = tuple(
        ConnectionPath(
            coords=path.coords,
            aspects=path.aspects,
            placements=path.placements,
            cost=sum(
                1.0 + tie_breaker * kb.aspect_depth(aspect)
                for aspect in path.placements.values()
            ),
        )
        for path in best.paths
    )
    solution = Solution(
        placements=placements,
        paths=normalized_paths,
        cost=len(placements)
        + tie_breaker * sum(kb.aspect_depth(aspect) for aspect in placements.values()),
        warnings=tuple(warnings),
    )
    validate_solution(board, kb, solution)
    return solution


def _minimal_candidate_configs(
    kb: KnowledgeBase,
    config: SearchConfig,
) -> tuple[SearchConfig, ...]:
    candidates: list[SearchConfig] = []
    if config.aspect_inventory is not None:
        candidates.append(
            SearchConfig(
                max_iterations=config.max_iterations,
                aspect_inventory=config.aspect_inventory,
                zero_inventory_penalty=config.zero_inventory_penalty,
                optimal_search_state_limit=config.optimal_search_state_limit,
            )
        )

    depths = {aspect: kb.aspect_depth(aspect) for aspect in kb.aspects}
    max_depth = max(depths.values(), default=0)
    for cutoff in sorted({3, max_depth - 2}):
        if cutoff <= 0 or cutoff > max_depth:
            continue
        exploration_inventory = {
            aspect: 100 if depth >= cutoff else 0
            for aspect, depth in depths.items()
        }
        candidates.append(
            SearchConfig(
                max_iterations=config.max_iterations,
                aspect_inventory=exploration_inventory,
                zero_inventory_penalty=config.zero_inventory_penalty,
                optimal_search_state_limit=config.optimal_search_state_limit,
            )
        )
    return tuple(candidates)


def _search_connection_orders(
    board: BoardState,
    kb: KnowledgeBase,
    config: SearchConfig,
    *,
    initial_best: Solution,
) -> tuple[Solution, bool]:
    if len(board.roots) <= 2:
        return initial_best, False

    best = initial_best
    static_context = _build_static_path_search_context(board, kb)
    seen: set[tuple[tuple[HexCoord, str], ...]] = set()
    state_limit = max(1, int(config.optimal_search_state_limit))
    states_visited = 0
    exhausted = False

    def visit(
        placements: dict[HexCoord, str],
        chosen_paths: tuple[ConnectionPath, ...],
    ) -> None:
        nonlocal best, states_visited, exhausted
        if states_visited >= state_limit:
            exhausted = True
            return

        state_key = tuple(sorted(placements.items()))
        if state_key in seen:
            return
        seen.add(state_key)
        states_visited += 1

        components, coord_to_component = connected_components(board, kb, placements)
        root_ids = sorted(root_component_ids(board, coord_to_component))
        if len(root_ids) <= 1:
            candidate = Solution(
                placements=dict(sorted(placements.items())),
                paths=chosen_paths,
                cost=sum(path.cost for path in chosen_paths),
            )
            if _minimal_solution_key(kb, candidate.placements) < _minimal_solution_key(kb, best.placements):
                best = candidate
            return

        best_count = len(best.placements)
        if len(placements) >= best_count:
            return

        context = _build_path_search_context(
            board,
            kb,
            placements,
            config,
            static_context=static_context,
        )
        candidates: list[tuple[int, float, tuple[HexCoord, ...], ConnectionPath]] = []
        minimum_added_by_component = {component_id: float("inf") for component_id in root_ids}
        max_path_cost = float(best_count - len(placements) + 1)
        for index, left_id in enumerate(root_ids):
            targets = {right_id: components[right_id] for right_id in root_ids[index + 1 :]}
            found = _find_connection_paths(
                board=board,
                start_coords=components[left_id],
                goal_coords_by_id=targets,
                placements=placements,
                context=context,
                max_cost=max_path_cost,
            )
            for right_id, path in found.items():
                added = len(path.placements)
                if added <= 0:
                    continue
                minimum_added_by_component[left_id] = min(minimum_added_by_component[left_id], added)
                minimum_added_by_component[right_id] = min(minimum_added_by_component[right_id], added)
                candidates.append((added, path.cost, path.coords, path))

        if not candidates or any(value == float("inf") for value in minimum_added_by_component.values()):
            return
        lower_bound = int(max(minimum_added_by_component.values()))
        if len(placements) + lower_bound > best_count:
            return

        candidates.sort(key=lambda item: item[:3])
        for _added, _cost, _coords, path in candidates:
            merged = dict(placements)
            conflict = False
            for coord, aspect in path.placements.items():
                existing = merged.get(coord)
                if existing is not None and existing != aspect:
                    conflict = True
                    break
                merged[coord] = aspect
            if conflict or len(merged) > len(best.placements):
                continue
            visit(merged, chosen_paths + (path,))

    visit({}, ())
    return best, exhausted


def _minimal_solution_key(
    kb: KnowledgeBase,
    placements: Mapping[HexCoord, str],
) -> tuple[int, int, tuple[tuple[HexCoord, str], ...]]:
    return (
        len(placements),
        sum(kb.aspect_depth(aspect) for aspect in placements.values()),
        tuple(sorted(placements.items())),
    )


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
        context=_build_path_search_context(
            board,
            kb,
            placements,
            config,
            static_context=_build_static_path_search_context(board, kb),
        ),
    )


def _build_static_path_search_context(
    board: BoardState,
    kb: KnowledgeBase,
) -> _StaticPathSearchContext:
    cells = board.cells
    return _StaticPathSearchContext(
        neighbors_by_coord={
            coord: tuple(neighbor for neighbor in hex_neighbors(coord) if neighbor in cells)
            for coord in cells
        },
        connectable_by_aspect={
            aspect: frozenset(neighbors)
            for aspect, neighbors in kb.neighbors.items()
        },
        direct_candidates_by_aspect={
            aspect: tuple((neighbor, True) for neighbor in neighbors)
            for aspect, neighbors in kb.neighbors.items()
        },
    )


def _build_path_search_context(
    board: BoardState,
    kb: KnowledgeBase,
    placements: dict[HexCoord, str],
    config: SearchConfig,
    *,
    static_context: _StaticPathSearchContext | None = None,
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

    static_context = static_context or _build_static_path_search_context(board, kb)

    return _PathSearchContext(
        aspect_by_coord=aspect_by_coord,
        empty_coords=empty_coords,
        neighbors_by_coord=static_context.neighbors_by_coord,
        connectable_by_aspect=static_context.connectable_by_aspect,
        direct_candidates_by_aspect=static_context.direct_candidates_by_aspect,
        placement_cost_by_aspect=_placement_cost_cache(
            kb,
            placements,
            config,
            max_placements=len(empty_coords),
        ),
    )


def _find_connection_path(
    board: BoardState,
    start_coords: set[HexCoord],
    goal_coords: set[HexCoord],
    placements: dict[HexCoord, str],
    context: _PathSearchContext,
) -> ConnectionPath | None:
    return _find_connection_paths(
        board=board,
        start_coords=start_coords,
        goal_coords_by_id={0: goal_coords},
        placements=placements,
        context=context,
    ).get(0)


def _find_connection_paths(
    board: BoardState,
    start_coords: set[HexCoord],
    goal_coords_by_id: Mapping[int, set[HexCoord]],
    placements: dict[HexCoord, str],
    context: _PathSearchContext,
    max_cost: float | None = None,
) -> dict[int, ConnectionPath]:
    aspect_by_coord = context.aspect_by_coord
    starts = sorted(coord for coord in start_coords if coord in aspect_by_coord)
    goal_id_by_coord = {
        coord: goal_id
        for goal_id, coords in goal_coords_by_id.items()
        for coord in coords
    }
    if not starts or not goal_id_by_coord:
        return {}

    empty_coords = context.empty_coords
    neighbors_by_coord = context.neighbors_by_coord
    connectable_by_aspect = context.connectable_by_aspect
    direct_candidates_by_aspect = context.direct_candidates_by_aspect
    placement_cost_by_aspect = context.placement_cost_by_aspect
    sequence = count()
    heap: list[tuple[float, int, int, HexCoord, str]] = []
    dist: dict[tuple[HexCoord, str], float] = {}
    parent: dict[tuple[HexCoord, str], tuple[HexCoord, str] | None] = {}
    remaining_goals = set(goal_coords_by_id)
    found: dict[int, ConnectionPath] = {}

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
        if max_cost is not None and cost > max_cost:
            break
        goal_id = goal_id_by_coord.get(coord)
        if goal_id in remaining_goals:
            found[goal_id] = _reconstruct_path(board, key, parent, dist[key], placements)
            remaining_goals.remove(goal_id)
            if not remaining_goals:
                break

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
                if max_cost is not None and next_cost > max_cost:
                    continue
                if next_cost < dist.get(next_key, float("inf")):
                    dist[next_key] = next_cost
                    parent[next_key] = key
                    heapq.heappush(heap, (next_cost, steps + 1, next(sequence), neighbor, next_aspect))

    return found


def _placement_cost_cache(
    kb: KnowledgeBase,
    placements: dict[HexCoord, str],
    config: SearchConfig,
    *,
    max_placements: int,
) -> dict[str, float]:
    if config.minimize_placements:
        max_depth = max((kb.aspect_depth(aspect) for aspect in kb.aspects), default=0)
        tie_breaker = 1.0 / ((max_depth + 1) * (max(1, max_placements) + 1))
        return {
            aspect: 1.0 + (tie_breaker * kb.aspect_depth(aspect))
            for aspect in kb.aspects
        }

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
