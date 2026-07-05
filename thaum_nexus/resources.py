from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .knowledge_base import KnowledgeBase


AspectCounts = Mapping[str, int]


@dataclass(frozen=True)
class SynthesisStep:
    """One Thaumcraft aspect-combination action.

    The order is intentionally depth-first: executing the list from first to
    last creates every intermediate aspect before it is consumed by a later
    step.
    """

    output: str
    left: str
    right: str

    def to_dict(self) -> dict[str, str]:
        return {"output": self.output, "left": self.left, "right": self.right}


@dataclass(frozen=True)
class ResourcePlan:
    """Resource simulation for placing a solution in the current research table."""

    required: dict[str, int]
    available: dict[str, int]
    synthesis: tuple[SynthesisStep, ...] = ()
    shortages: dict[str, int] = field(default_factory=dict)
    remaining: dict[str, int] = field(default_factory=dict)

    @property
    def is_sufficient(self) -> bool:
        return not self.shortages

    def to_dict(self) -> dict[str, object]:
        return {
            "required": dict(sorted(self.required.items())),
            "available": dict(sorted(self.available.items())),
            "synthesis": [step.to_dict() for step in self.synthesis],
            "shortages": dict(sorted(self.shortages.items())),
            "remaining": dict(sorted(self.remaining.items())),
            "sufficient": self.is_sufficient,
        }


def normalize_counts(counts: Mapping[str, int] | None) -> dict[str, int]:
    if not counts:
        return {}
    return {str(key): max(0, int(value)) for key, value in counts.items() if int(value) > 0}


def count_required_aspects(aspects: Iterable[str] | Mapping[str, int]) -> dict[str, int]:
    if isinstance(aspects, Mapping):
        counter = Counter({str(key): int(value) for key, value in aspects.items() if int(value) > 0})
    else:
        counter = Counter(str(aspect) for aspect in aspects)
    return dict(sorted(counter.items()))


def plan_resource_usage(
    kb: KnowledgeBase,
    required_aspects: Iterable[str] | Mapping[str, int],
    available_aspects: Mapping[str, int] | None,
) -> ResourcePlan:
    """Plan direct consumption plus shift-click synthesis for required aspects.

    This mirrors Thaumcraft's "combine two component aspects to produce one
    output aspect" rule.  It does not mutate the game; it is a deterministic
    local simulation used to build a Java-agent apply plan.
    """

    required = count_required_aspects(required_aspects)
    stock = Counter(normalize_counts(available_aspects))
    starting_stock = dict(sorted(stock.items()))
    steps: list[SynthesisStep] = []
    shortages: Counter[str] = Counter()

    def consume(aspect: str, stack: tuple[str, ...] = ()) -> tuple[bool, Counter[str]]:
        kb.require_aspect(aspect)
        if stock[aspect] > 0:
            stock[aspect] -= 1
            return True, Counter()

        if aspect in stack:
            return False, Counter({aspect: 1})

        components = kb.by_output.get(aspect)
        if not components:
            return False, Counter({aspect: 1})

        snapshot_stock = stock.copy()
        snapshot_steps_len = len(steps)
        left, right = components
        left_ok, left_shortages = consume(left, stack + (aspect,))
        right_ok, right_shortages = consume(right, stack + (aspect,)) if left_ok else (False, Counter())
        if left_ok and right_ok:
            steps.append(SynthesisStep(output=aspect, left=left, right=right))
            # The produced aspect is immediately consumed by the caller.
            return True, Counter()

        stock.clear()
        stock.update(snapshot_stock)
        del steps[snapshot_steps_len:]
        combined_shortages = left_shortages + right_shortages
        if not combined_shortages:
            combined_shortages[aspect] += 1
        return False, combined_shortages

    for aspect, amount in required.items():
        for _ in range(amount):
            ok, missing = consume(aspect)
            if not ok:
                shortages.update(missing)

    remaining = {key: value for key, value in sorted(stock.items()) if value > 0}
    return ResourcePlan(
        required=required,
        available=starting_stock,
        synthesis=tuple(steps),
        shortages=dict(sorted(shortages.items())),
        remaining=remaining,
    )


def resource_aware_placement_cost(
    kb: KnowledgeBase,
    aspect: str,
    available_aspects: Mapping[str, int] | None,
    reserved_aspects: Mapping[str, int] | None = None,
    *,
    zero_inventory_penalty: float = 4.0,
) -> float:
    """Return a placement cost that prefers abundant aspects but still solves.

    The base cost keeps "fewer placed cells" dominant.  Availability only acts
    as a tie-breaker unless an aspect is absent, where we strongly prefer an
    alternate route that uses an already available aspect.
    """

    base = kb.placement_cost(aspect)
    if not available_aspects:
        return base

    reserved = int((reserved_aspects or {}).get(aspect, 0))
    available = max(0, int(available_aspects.get(aspect, 0)) - reserved)
    if available > 0:
        return base + (0.20 / (available + 1))

    # Missing aspects may still be synthesizable, so do not make them
    # impossible; just push the search toward plentiful alternatives.
    return base + zero_inventory_penalty + (0.10 * kb.aspect_depth(aspect))
