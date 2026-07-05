from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math


try:
    from PIL import Image
except Exception:  # pragma: no cover - depends on optional local GUI stack.
    Image = None  # type: ignore[assignment]

from .aspect_matcher import _foreground_mask_descriptor, _has_meaningful_transparency


@dataclass(frozen=True)
class HexPresence:
    """Presence classification for one candidate research-note hex."""

    present: bool
    score: float
    alpha_coverage: float
    edge_score: float
    crop_box: tuple[int, int, int, int]


@dataclass(frozen=True)
class HexPresenceDetector:
    """Detect whether a candidate hex cell exists in a screenshot crop.

    This is intentionally heuristic and dependency-light. It uses alpha coverage
    when tests/synthetic images have transparency, and a luminance edge score for
    opaque screenshots. Later OpenCV-specific detectors can replace this class
    behind the same output contract.
    """

    min_score: float = 0.30
    alpha_threshold: int = 12
    opaque_alpha_cutoff: int = 250
    edge_scale: float = 0.06

    def detect(self, image, crop_box: tuple[int, int, int, int]) -> HexPresence:
        if Image is None:
            raise RuntimeError("Pillow is required for HexPresenceDetector")
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        crop = image.crop(crop_box)
        if crop.width <= 0 or crop.height <= 0:
            return HexPresence(False, 0.0, 0.0, 0.0, crop_box)

        rgba = crop.tobytes()
        alpha_values = rgba[3::4]
        has_transparency = min(alpha_values, default=255) < self.opaque_alpha_cutoff
        alpha_coverage = (
            sum(1 for alpha in alpha_values if alpha > self.alpha_threshold) / len(alpha_values)
            if alpha_values
            else 0.0
        )
        edge_score = _luminance_edge_score(crop)

        if not has_transparency and not _has_meaningful_transparency(crop):
            score = max(_opaque_research_cell_score(crop), _opaque_edge_signal(edge_score))
            return HexPresence(
                present=score >= self.min_score,
                score=score,
                alpha_coverage=alpha_coverage,
                edge_score=edge_score,
                crop_box=crop_box,
            )

        edge_signal = min(1.0, edge_score / self.edge_scale) if self.edge_scale > 0 else edge_score
        # Transparent synthetic/test images should not use edge score as the
        # main signal: small fragments of a nearby icon create sharp edges and
        # otherwise look like a real cell. Real game screenshots are opaque, so
        # they still use the luminance edge signal.
        score = alpha_coverage if has_transparency else edge_signal
        return HexPresence(
            present=score >= self.min_score,
            score=score,
            alpha_coverage=alpha_coverage,
            edge_score=edge_score,
            crop_box=crop_box,
        )


def _luminance_edge_score(image) -> float:
    """Mean normalized luminance difference between adjacent pixels."""

    gray = image.convert("L")
    width, height = gray.size
    if width < 2 or height < 2:
        return 0.0
    data = gray.tobytes()
    total = 0
    count = 0

    for y in range(height):
        row = y * width
        for x in range(width - 1):
            total += abs(data[row + x] - data[row + x + 1])
            count += 1

    for y in range(height - 1):
        row = y * width
        next_row = (y + 1) * width
        for x in range(width):
            total += abs(data[row + x] - data[next_row + x])
            count += 1

    return (total / count) / 255.0 if count else 0.0


def _opaque_research_cell_score(crop) -> float:
    """Score opaque Minecraft crops by looking for a hex outline or icon body."""

    descriptor = _foreground_mask_descriptor(crop, size=64)
    mask = descriptor.mask
    ring_score = _best_hex_ring_coverage(mask, 64)
    central = _coverage(mask, _circle_indices(64, 19.0))
    inner = _coverage(mask, _circle_indices(64, 26.0))
    # Root icons often cover the middle and obscure parts of the outline.
    # Empty cells mostly score through the ring. Parchment decorations outside
    # the grid tend to be sparse or off-shape and stay below the threshold.
    return max(ring_score, central * 1.10, inner * 0.85)


def _opaque_edge_signal(edge_score: float) -> float:
    """Map subtle real hex-outline edges into a 0..1 presence signal.

    On real GTNH screenshots, actual research cells have a mean luminance-edge
    score around 0.022+ after calibration; parchment-only areas are usually
    below that. This calibrated edge term recovers empty cells whose outline is
    too close to the parchment hue for color-mask detection.
    """

    if edge_score <= 0.018:
        return 0.0
    return max(0.0, min(1.0, (edge_score - 0.018) / 0.012))


def _best_hex_ring_coverage(mask: tuple[bool, ...], size: int) -> float:
    return max(_coverage(mask, _hex_ring_indices(size, radius, width=4)) for radius in range(17, 27))


def _coverage(mask: tuple[bool, ...], indices: tuple[int, ...]) -> float:
    if not indices:
        return 0.0
    return sum(1 for index in indices if mask[index]) / len(indices)


@lru_cache(maxsize=None)
def _circle_indices(size: int, radius: float) -> tuple[int, ...]:
    center = size / 2.0
    output: list[int] = []
    for y in range(size):
        for x in range(size):
            if math.hypot(x + 0.5 - center, y + 0.5 - center) < radius:
                output.append(y * size + x)
    return tuple(output)


@lru_cache(maxsize=None)
def _hex_ring_indices(size: int, radius: int, width: int = 4) -> tuple[int, ...]:
    if Image is None:
        raise RuntimeError("Pillow is required for HexPresenceDetector")
    from PIL import ImageDraw

    image = Image.new("1", (size, size), 0)
    draw = ImageDraw.Draw(image)
    center = size / 2.0
    points = tuple(
        (
            center + radius * math.cos(math.pi / 6.0 + index * math.pi / 3.0),
            center + radius * math.sin(math.pi / 6.0 + index * math.pi / 3.0),
        )
        for index in range(6)
    )
    draw.line([*points, points[0]], fill=1, width=width)
    return tuple(index for index, value in enumerate(image.tobytes()) if value)
