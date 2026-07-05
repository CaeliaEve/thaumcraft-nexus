from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .data_model import BoardState, Cell, CellKind, HexCoord


THAUMCRAFT_HEX_TYPES: dict[int, CellKind] = {
    0: CellKind.EMPTY,
    1: CellKind.ROOT,
    2: CellKind.PLACED,
}


@dataclass(frozen=True)
class ResearchNote:
    """Structured Thaumcraft research-note data exported from client NBT.

    This is deliberately separate from the screenshot reader.  Thaumcraft
    stores the research minigame as a hex-grid NBT list, where:

    - type 0 = empty valid cell
    - type 1 = fixed/root printed aspect
    - type 2 = player-placed aspect
    """

    board: BoardState
    research_key: str = ""
    source: str = ""
    complete: bool = False
    copies: int = 0
    raw: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchNote":
        board = board_from_note_dict(payload)
        research_key = str(payload.get("researchKey") or payload.get("key") or board.name)
        return cls(
            board=board,
            research_key=research_key,
            source=str(payload.get("source") or ""),
            complete=bool(payload.get("complete", False)),
            copies=int(payload.get("copies", 0) or 0),
            raw=payload,
        )

    @classmethod
    def load(cls, path: Path | str) -> "ResearchNote":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def load_note_board(path: Path | str) -> BoardState:
    """Load either a native BoardState JSON or a Thaumcraft note JSON file."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if "hexgrid" in payload:
        return board_from_note_dict(payload)
    return BoardState.from_dict(payload)


def board_from_note_dict(payload: dict[str, Any]) -> BoardState:
    """Convert Thaumcraft note JSON/NBT export into the solver BoardState."""

    if "cells" in payload and "hexgrid" not in payload:
        return BoardState.from_dict(payload)

    entries = payload.get("hexgrid")
    if not isinstance(entries, list):
        raise ValueError("research note JSON must contain a hexgrid list")

    cells: list[Cell] = []
    seen: set[HexCoord] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"hexgrid[{index}] must be an object")
        cell = _cell_from_hexgrid_entry(entry, index=index)
        if cell.coord in seen:
            raise ValueError(f"duplicate hex coordinate in note: {cell.coord.key()}")
        seen.add(cell.coord)
        cells.append(cell)

    board_payload = {
        "name": str(payload.get("researchKey") or payload.get("key") or payload.get("name") or "research-note"),
        "cells": [cell.to_dict() for cell in cells],
    }
    return BoardState.from_dict(board_payload)


def _cell_from_hexgrid_entry(entry: dict[str, Any], *, index: int) -> Cell:
    q = _required_int(entry, "q", "hexq", index=index)
    r = _required_int(entry, "r", "hexr", index=index)
    type_value = _required_int(entry, "type", index=index)
    try:
        kind = THAUMCRAFT_HEX_TYPES[type_value]
    except KeyError as exc:
        raise ValueError(f"hexgrid[{index}] has unsupported Thaumcraft hex type {type_value}") from exc

    raw_aspect = entry.get("aspect")
    aspect = str(raw_aspect).strip() if raw_aspect is not None and str(raw_aspect).strip() else None
    if kind in {CellKind.ROOT, CellKind.PLACED} and aspect is None:
        raise ValueError(f"hexgrid[{index}] type {type_value} requires aspect")
    if kind is CellKind.EMPTY:
        aspect = None
    return Cell(coord=HexCoord(q, r), kind=kind, aspect=aspect)


def _required_int(entry: dict[str, Any], *keys: str, index: int) -> int:
    for key in keys:
        if key in entry:
            try:
                return int(entry[key])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"hexgrid[{index}].{key} must be an integer") from exc
    joined = " or ".join(keys)
    raise ValueError(f"hexgrid[{index}] missing {joined}")
