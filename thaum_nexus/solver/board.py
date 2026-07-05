from __future__ import annotations

from collections import deque

from thaum_nexus.data_model import BoardState, CellKind, HexCoord, hex_neighbors
from thaum_nexus.knowledge_base import KnowledgeBase


def occupied_coords(board: BoardState, placements: dict[HexCoord, str]) -> set[HexCoord]:
    coords: set[HexCoord] = set(placements)
    for coord, cell in board.cells.items():
        if cell.kind in {CellKind.ROOT, CellKind.PLACED} and cell.aspect:
            coords.add(coord)
    return coords


def connected_components(
    board: BoardState,
    kb: KnowledgeBase,
    placements: dict[HexCoord, str] | None = None,
) -> tuple[list[set[HexCoord]], dict[HexCoord, int]]:
    """Return legal-aspect connected components among occupied cells."""

    placements = placements or {}
    occupied = occupied_coords(board, placements)
    components: list[set[HexCoord]] = []
    coord_to_component: dict[HexCoord, int] = {}

    for start in sorted(occupied):
        if start in coord_to_component:
            continue
        index = len(components)
        component: set[HexCoord] = set()
        queue: deque[HexCoord] = deque([start])
        coord_to_component[start] = index

        while queue:
            coord = queue.popleft()
            component.add(coord)
            aspect = board.aspect_at(coord, placements)
            if aspect is None:
                continue
            for neighbor in hex_neighbors(coord):
                if neighbor not in occupied or neighbor in coord_to_component:
                    continue
                other = board.aspect_at(neighbor, placements)
                if other is not None and kb.can_connect(aspect, other):
                    coord_to_component[neighbor] = index
                    queue.append(neighbor)

        components.append(component)

    return components, coord_to_component


def root_component_ids(
    board: BoardState,
    coord_to_component: dict[HexCoord, int],
) -> set[int]:
    ids: set[int] = set()
    for root in board.roots:
        if root.coord not in coord_to_component:
            raise ValueError(f"root {root.coord.key()} is not in any occupied component")
        ids.add(coord_to_component[root.coord])
    return ids

