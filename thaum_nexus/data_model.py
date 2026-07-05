from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class CellKind(str, Enum):
    """Kinds of cells in a Thaumcraft research note board."""

    EMPTY = "empty"
    ROOT = "root"
    PLACED = "placed"
    MISSING = "missing"


@dataclass(frozen=True, order=True)
class HexCoord:
    """Axial hex coordinate used by Thaumcraft's research note grid."""

    q: int
    r: int

    def key(self) -> str:
        return f"{self.q},{self.r}"

    @classmethod
    def parse(cls, value: str | dict[str, int] | Iterable[int]) -> "HexCoord":
        if isinstance(value, str):
            q, r = value.split(",", 1)
            return cls(int(q), int(r))
        if isinstance(value, dict):
            return cls(int(value["q"]), int(value["r"]))
        q, r = value
        return cls(int(q), int(r))


HEX_DIRECTIONS: tuple[HexCoord, ...] = (
    HexCoord(1, 0),
    HexCoord(1, -1),
    HexCoord(0, -1),
    HexCoord(-1, 0),
    HexCoord(-1, 1),
    HexCoord(0, 1),
)


def hex_neighbors(coord: HexCoord) -> tuple[HexCoord, ...]:
    return tuple(HexCoord(coord.q + delta.q, coord.r + delta.r) for delta in HEX_DIRECTIONS)


@dataclass(frozen=True)
class Aspect:
    key: str
    name: str
    description: str
    icon: str
    primal: bool = False
    components: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Aspect":
        return cls(
            key=payload["key"],
            name=payload["name"],
            description=payload.get("description", ""),
            icon=payload.get("icon", ""),
            primal=bool(payload.get("primal", False)),
            components=tuple(payload.get("components") or ()),
        )


@dataclass(frozen=True)
class Cell:
    coord: HexCoord
    kind: CellKind
    aspect: str | None = None

    @property
    def is_occupied(self) -> bool:
        return self.aspect is not None and self.kind in {CellKind.ROOT, CellKind.PLACED}

    @property
    def is_root(self) -> bool:
        return self.kind is CellKind.ROOT

    @property
    def is_empty(self) -> bool:
        return self.kind is CellKind.EMPTY

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Cell":
        coord = HexCoord(int(payload["q"]), int(payload["r"]))
        kind = CellKind(payload.get("kind", CellKind.EMPTY.value))
        aspect = payload.get("aspect")
        if kind in {CellKind.ROOT, CellKind.PLACED} and not aspect:
            raise ValueError(f"{kind.value} cell at {coord.key()} must include aspect")
        if kind in {CellKind.EMPTY, CellKind.MISSING} and aspect:
            raise ValueError(f"{kind.value} cell at {coord.key()} cannot include aspect")
        return cls(coord=coord, kind=kind, aspect=aspect)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"q": self.coord.q, "r": self.coord.r, "kind": self.kind.value}
        if self.aspect is not None:
            payload["aspect"] = self.aspect
        return payload


@dataclass(frozen=True)
class BoardState:
    """Research note board state independent of screenshots."""

    cells: dict[HexCoord, Cell]
    name: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BoardState":
        cells = [Cell.from_dict(item) for item in payload.get("cells", [])]
        by_coord = {cell.coord: cell for cell in cells if cell.kind is not CellKind.MISSING}
        if len(by_coord) != len([cell for cell in cells if cell.kind is not CellKind.MISSING]):
            raise ValueError("duplicate hex coordinates in board")
        return cls(cells=by_coord, name=payload.get("name", ""))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "cells": [self.cells[coord].to_dict() for coord in sorted(self.cells)],
        }

    @property
    def roots(self) -> tuple[Cell, ...]:
        return tuple(cell for cell in self.cells.values() if cell.kind is CellKind.ROOT)

    def cell_at(self, coord: HexCoord) -> Cell | None:
        return self.cells.get(coord)

    def contains(self, coord: HexCoord) -> bool:
        return coord in self.cells

    def aspect_at(self, coord: HexCoord, placements: dict[HexCoord, str] | None = None) -> str | None:
        if placements and coord in placements:
            return placements[coord]
        cell = self.cells.get(coord)
        return cell.aspect if cell else None


@dataclass(frozen=True)
class ConnectionPath:
    """One chosen path connecting two occupied components."""

    coords: tuple[HexCoord, ...]
    aspects: dict[HexCoord, str]
    placements: dict[HexCoord, str]
    cost: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "coords": [coord.key() for coord in self.coords],
            "aspects": {coord.key(): aspect for coord, aspect in sorted(self.aspects.items())},
            "placements": {coord.key(): aspect for coord, aspect in sorted(self.placements.items())},
            "cost": self.cost,
        }


@dataclass(frozen=True)
class Solution:
    placements: dict[HexCoord, str]
    paths: tuple[ConnectionPath, ...] = ()
    cost: float = 0.0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "placements": {coord.key(): aspect for coord, aspect in sorted(self.placements.items())},
            "paths": [path.to_dict() for path in self.paths],
            "cost": self.cost,
            "warnings": list(self.warnings),
        }

