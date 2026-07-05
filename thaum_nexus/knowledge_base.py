from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .data_model import Aspect
from .paths import data_dir


class KnowledgeBase:
    """Loaded Thaumcraft aspect graph generated from this project's data files."""

    def __init__(
        self,
        aspects: dict[str, Aspect],
        neighbors: dict[str, tuple[str, ...]],
        by_output: dict[str, tuple[str, str]],
        by_pair: dict[str, str],
        primal: tuple[str, ...],
    ) -> None:
        self.aspects = aspects
        self.neighbors = neighbors
        self.by_output = by_output
        self.by_pair = by_pair
        self.primal = primal

    @classmethod
    def load(cls, project_root: Path | str | None = None) -> "KnowledgeBase":
        root_data_dir = data_dir(project_root)
        aspects_payload = _read_json(root_data_dir / "aspects.json")
        combos_payload = _read_json(root_data_dir / "combinations.json")
        adjacency_payload = _read_json(root_data_dir / "adjacency.json")

        aspects = {
            key: Aspect.from_dict(payload)
            for key, payload in aspects_payload["aspects"].items()
        }
        neighbors = {
            key: tuple(values)
            for key, values in adjacency_payload["neighbors"].items()
        }
        by_output = {
            output: tuple(components)  # type: ignore[arg-type]
            for output, components in combos_payload["byOutput"].items()
        }
        by_pair = dict(combos_payload["bySortedPair"])
        primal = tuple(combos_payload["primal"])
        kb = cls(aspects=aspects, neighbors=neighbors, by_output=by_output, by_pair=by_pair, primal=primal)
        kb.validate()
        return kb

    def validate(self) -> None:
        for key, aspect in self.aspects.items():
            if key != aspect.key:
                raise ValueError(f"aspect key mismatch: {key} != {aspect.key}")
            if key not in self.neighbors:
                raise ValueError(f"missing neighbor row for {key}")
        for output, components in self.by_output.items():
            if output not in self.aspects:
                raise ValueError(f"unknown combination output {output}")
            if len(components) != 2:
                raise ValueError(f"combination {output} must have 2 components")
            for component in components:
                if component not in self.aspects:
                    raise ValueError(f"unknown component {component} for {output}")
                if not self.can_connect(output, component):
                    raise ValueError(f"missing adjacency edge {output}<->{component}")

    def require_aspect(self, key: str) -> Aspect:
        try:
            return self.aspects[key]
        except KeyError as exc:
            raise KeyError(f"unknown aspect: {key}") from exc

    def can_connect(self, left: str, right: str) -> bool:
        if left == right:
            return False
        return right in self.neighbors.get(left, ())

    def direct_neighbors(self, key: str) -> tuple[str, ...]:
        self.require_aspect(key)
        return self.neighbors[key]

    def combination_result(self, left: str, right: str) -> str | None:
        pair = "+".join(sorted((left, right)))
        return self.by_pair.get(pair)

    @lru_cache(maxsize=None)
    def aspect_depth(self, key: str) -> int:
        aspect = self.require_aspect(key)
        if aspect.primal:
            return 0
        components = self.by_output.get(key)
        if not components:
            return 1
        return 1 + max(self.aspect_depth(component) for component in components)

    def placement_cost(self, key: str) -> float:
        # Filling fewer cells dominates. Depth is only a deterministic tie-breaker
        # favoring simpler aspects when multiple chains are equally short.
        return 1.0 + 0.05 * self.aspect_depth(key)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
