from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import colorsys
import math
from pathlib import Path
import statistics

from thaum_nexus.knowledge_base import KnowledgeBase
from thaum_nexus.paths import resource_path, resource_root


try:  # Pillow is intentionally optional until the GUI/vision milestone.
    from PIL import Image
except Exception:  # pragma: no cover - exercised only on environments without Pillow.
    Image = None  # type: ignore[assignment]


@dataclass(frozen=True)
class AspectMatch:
    key: str
    score: float


class AspectMatcher:
    """Pillow-based aspect icon matcher.

    This is a dependency-light bridge before introducing OpenCV. It works well
    for cropped icon candidates and synthetic tests. Later screenshot code can
    replace the scoring backend with OpenCV while preserving this public API.
    """

    def __init__(self, templates: dict[str, object]) -> None:
        if Image is None:
            raise RuntimeError("Pillow is required for AspectMatcher")
        self.templates = templates
        self._shape_templates = {
            key: _ScaledTemplateShape(template)
            for key, template in templates.items()
        }

    @classmethod
    def load(
        cls,
        kb: KnowledgeBase,
        project_root: Path | str | None = None,
        *,
        size: tuple[int, int] = (64, 64),
    ) -> "AspectMatcher":
        if Image is None:
            raise RuntimeError("Pillow is required for AspectMatcher")
        root = resource_root(project_root)
        templates: dict[str, object] = {}
        for key, aspect in kb.aspects.items():
            icon_path = resource_path(aspect.icon, root)
            templates[key] = _prepare_image(icon_path, size)
        return cls(templates)

    def match(self, candidate_path: Path | str, *, threshold: float = 0.80) -> AspectMatch | None:
        candidate = _prepare_image(Path(candidate_path), self._template_size())
        return self.match_image(candidate, threshold=threshold)

    def match_image(self, candidate: object, *, threshold: float = 0.80) -> AspectMatch | None:
        ranked = self.rank_image(candidate)
        best = ranked[0] if ranked else None
        if best is None or best.score < threshold:
            return None
        return best

    def rank_image(self, candidate: object) -> list[AspectMatch]:
        """Return all aspect matches sorted by descending confidence.

        Transparent synthetic crops are scored by exact alpha-aware template
        comparison. Opaque Minecraft screenshots are scored by foreground-shape
        matching after parchment-background suppression; this avoids treating
        parchment noise as a yellow aspect icon.
        """

        if Image is None:
            raise RuntimeError("Pillow is required for AspectMatcher")
        normalized = _prepare_loaded_image(candidate, self._template_size())
        if _has_meaningful_transparency(normalized):
            scorer = lambda key, template: _alpha_weighted_similarity(template, normalized)
        else:
            descriptor = _foreground_mask_descriptor(normalized)
            scorer = lambda key, template: _foreground_shape_similarity(
                self._shape_templates[key],
                descriptor,
            )
        ranked: list[AspectMatch] = []
        for key, template in self.templates.items():
            ranked.append(AspectMatch(key=key, score=scorer(key, template)))
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked

    def _template_size(self) -> tuple[int, int]:
        first = next(iter(self.templates.values()))
        return first.size  # type: ignore[attr-defined]

    def match_crop(
        self,
        screenshot: object,
        box: tuple[int, int, int, int],
        *,
        threshold: float = 0.80,
    ) -> AspectMatch | None:
        """Crop a screenshot and match it against aspect templates."""

        if Image is None:
            raise RuntimeError("Pillow is required for AspectMatcher")
        if screenshot.mode != "RGBA":
            screenshot = screenshot.convert("RGBA")
        return self.match_image(screenshot.crop(box), threshold=threshold)


def _prepare_image(path: Path, size: tuple[int, int]):
    if Image is None:
        raise RuntimeError("Pillow is required for AspectMatcher")
    return _prepare_loaded_image(Image.open(path), size)


def _prepare_loaded_image(image, size: tuple[int, int]):
    if Image is None:
        raise RuntimeError("Pillow is required for AspectMatcher")
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    return image


def _alpha_weighted_similarity(left, right) -> float:
    """Return 0..1 similarity using the template alpha as the comparison mask.

    `left` is the canonical template. Real screenshots are usually fully
    opaque, so using candidate alpha would make the parchment/background
    dominate the score. Masking by template alpha focuses the comparison on the
    actual aspect glyph.
    """

    if left.size != right.size:
        raise ValueError(f"image size mismatch: {left.size} vs {right.size}")

    left_bytes = left.tobytes()
    right_bytes = right.tobytes()
    right_has_transparency = _has_meaningful_transparency(right)
    weighted_error = 0.0
    total_weight = 0.0
    for index in range(0, len(left_bytes), 4):
        lr, lg, lb, la_byte = left_bytes[index : index + 4]
        rr, rg, rb, ra_byte = right_bytes[index : index + 4]
        la = la_byte / 255.0
        template_brightness = max(lr, lg, lb) / 255.0
        template_saturation = _rgb_saturation(lr, lg, lb)
        # Exact/synthetic matching should still compare semi-transparent dark
        # icon pixels, but avoid letting black backing dominate real crops.
        foreground = max(0.20, min(1.0, max(template_brightness / 0.25, template_saturation * 1.5)))
        weight = la * foreground
        if weight <= 0.0001:
            continue
        rgb_error = (abs(lr - rr) + abs(lg - rg) + abs(lb - rb)) / (3.0 * 255.0)
        if right_has_transparency:
            alpha_error = abs(la_byte - ra_byte) / 255.0
            pixel_error = 0.72 * rgb_error + 0.28 * alpha_error
        else:
            # Candidate alpha is intentionally ignored for screenshots;
            # otherwise opaque parchment under a transparent template would be
            # punished before foreground-shape matching has a chance to run.
            pixel_error = rgb_error
        weighted_error += weight * pixel_error
        total_weight += weight
    if total_weight == 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - weighted_error / total_weight))


def _has_meaningful_transparency(image) -> bool:
    if image.mode != "RGBA":
        return False
    alpha = image.tobytes()[3::4]
    if not alpha:
        return False
    transparent = sum(1 for value in alpha if value < 250)
    return transparent / len(alpha) >= 0.01


def _rgb_saturation(r: int, g: int, b: int) -> float:
    high = max(r, g, b)
    low = min(r, g, b)
    return (high - low) / high if high else 0.0


def _hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)


def _hue_distance(left: float, right: float) -> float:
    delta = abs(left - right)
    return min(delta, 1.0 - delta)


@dataclass(frozen=True)
class ForegroundDescriptor:
    size: int
    mask: tuple[bool, ...]
    colors: tuple[tuple[int, int, int, float, float, float], ...]


def _foreground_mask_descriptor(image, *, size: int = 64) -> ForegroundDescriptor:
    """Suppress parchment/background and keep likely glyph/hex foreground.

    This intentionally remains heuristic and Pillow-only. It estimates a local
    parchment color from the crop border, then keeps pixels whose saturation,
    hue, brightness or RGB distance differs enough from that background.
    """

    if Image is None:
        raise RuntimeError("Pillow is required for foreground extraction")
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    if image.size != (size, size):
        image = image.resize((size, size), Image.Resampling.LANCZOS)

    bg_r, bg_g, bg_b, bg_h, _bg_s, bg_v = _estimate_background_rgba(image)
    raw_mask: list[bool] = []
    colors: list[tuple[int, int, int, float, float, float]] = []

    for r, g, b, alpha in image.getdata():
        hue, saturation, value = _hsv(r, g, b)
        rgb_distance = math.sqrt((r - bg_r) ** 2 + (g - bg_g) ** 2 + (b - bg_b) ** 2) / 441.67295593
        hue_distance = _hue_distance(hue, bg_h)

        signal = 0.0
        if alpha >= 20:
            if saturation > 0.42 and (hue_distance > 0.06 or rgb_distance > 0.12):
                signal = max(signal, min(1.0, (saturation - 0.35) * 2.0 + rgb_distance))
            if rgb_distance > 0.18:
                signal = max(signal, min(1.0, (rgb_distance - 0.12) * 3.0))
            if value < bg_v - 0.22 and rgb_distance > 0.14:
                signal = max(signal, min(1.0, (bg_v - value) * 2.5))
            if value > bg_v + 0.18 and (saturation > 0.22 or rgb_distance > 0.12):
                signal = max(signal, min(1.0, (value - bg_v) * 2.2))

        raw_mask.append(signal > 0.22)
        colors.append((r, g, b, hue, saturation, value))

    mask = raw_mask[:]
    # Remove isolated one-pixel parchment speckles. Keep clusters, because both
    # root icons and empty hex outlines are thin but connected.
    for y in range(1, size - 1):
        for x in range(1, size - 1):
            index = y * size + x
            if not raw_mask[index]:
                continue
            neighbors = 0
            for yy in (y - 1, y, y + 1):
                for xx in (x - 1, x, x + 1):
                    if raw_mask[yy * size + xx]:
                        neighbors += 1
            if neighbors < 2:
                mask[index] = False

    return ForegroundDescriptor(size=size, mask=tuple(mask), colors=tuple(colors))


def _estimate_background_rgba(image) -> tuple[int, int, int, float, float, float]:
    width, height = image.size
    pixels = list(image.getdata())
    border = max(3, min(width, height) // 5)
    samples: list[tuple[int, int, int]] = []
    for y in range(height):
        row = y * width
        for x in range(width):
            if not (x < border or x >= width - border or y < border or y >= height - border):
                continue
            r, g, b, alpha = pixels[row + x]
            if alpha < 20:
                continue
            _h, saturation, value = _hsv(r, g, b)
            if saturation < 0.55 and value > 0.25:
                samples.append((r, g, b))
    if not samples:
        samples = [(r, g, b) for r, g, b, alpha in pixels if alpha > 20]
    if not samples:
        return (0, 0, 0, *_hsv(0, 0, 0))

    rgb = tuple(int(statistics.median(sample[index] for sample in samples)) for index in range(3))
    return (*rgb, *_hsv(*rgb))


@dataclass
class _ScaledTemplateShape:
    template: object
    _entries_cache: dict[int, tuple[tuple[int, int, int, int, int, float, float, float], ...]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def entries(self, size: int) -> tuple[tuple[int, int, int, int, int, float, float, float], ...]:
        cached = self._entries_cache.get(size)
        if cached is not None:
            return cached
        if Image is None:
            raise RuntimeError("Pillow is required for template shape extraction")
        resized = self.template.resize((size, size), Image.Resampling.LANCZOS)
        entries: list[tuple[int, int, int, int, int, float, float, float]] = []
        for index, (r, g, b, alpha) in enumerate(resized.getdata()):
            high = max(r, g, b)
            saturation = _rgb_saturation(r, g, b)
            # Ignore semi-transparent black backing/shadow. It is rendered very
            # differently over parchment and otherwise confuses cyan icons such
            # as Sensus with their dark internal holes.
            if alpha > 24 and ((saturation > 0.20 and high > 25) or high > 55):
                hue, sat, value = _hsv(r, g, b)
                entries.append((index % size, index // size, r, g, b, hue, sat, value))
        cached = tuple(entries)
        self._entries_cache[size] = cached
        return cached


def _foreground_shape_similarity(template_shape: _ScaledTemplateShape, descriptor: ForegroundDescriptor) -> float:
    size = descriptor.size
    scale_sizes = tuple(
        sorted(
            {
                max(8, int(round(size * ratio)))
                for ratio in (0.66, 0.72, 0.78, 0.84, 0.91, 0.97, 1.03)
            }
        )
    )
    offsets = (-5, 0, 5) if size >= 48 else (-2, 0, 2)
    weights = _center_weights(size)
    best = 0.0
    for scaled_size in scale_sizes:
        entries = template_shape.entries(scaled_size)
        if not entries:
            continue
        for dx in offsets:
            for dy in offsets:
                x0 = (size - scaled_size) // 2 + dx
                y0 = (size - scaled_size) // 2 + dy
                template_weight = 0.0
                candidate_weight = 0.0
                overlap_weight = 0.0
                color_weight = 0.0
                color_score = 0.0
                # Penalize tiny templates that fit inside a larger unrelated
                # foreground blob (common for empty hex rings and the Ordo
                # triangle). Candidate foreground outside the template's
                # bounding square is ignored so neighboring parchment marks do
                # not dominate.
                for yy in range(max(0, y0), min(size, y0 + scaled_size)):
                    row = yy * size
                    for xx in range(max(0, x0), min(size, x0 + scaled_size)):
                        candidate_index = row + xx
                        if descriptor.mask[candidate_index]:
                            candidate_weight += weights[candidate_index]
                for x, y, _r, _g, _b, template_hue, template_sat, template_value in entries:
                    cx = x0 + x
                    cy = y0 + y
                    if cx < 0 or cx >= size or cy < 0 or cy >= size:
                        continue
                    candidate_index = cy * size + cx
                    weight = weights[candidate_index]
                    template_weight += weight
                    if not descriptor.mask[candidate_index]:
                        continue
                    overlap_weight += weight
                    _cr, _cg, _cb, candidate_hue, candidate_sat, candidate_value = descriptor.colors[candidate_index]
                    hue_delta = _hue_distance(template_hue, candidate_hue)
                    if template_sat > 0.25 and candidate_sat > 0.20:
                        pixel_color = max(0.0, 1.0 - hue_delta * 4.0)
                    else:
                        pixel_color = max(
                            0.0,
                            1.0 - (abs(template_value - candidate_value) + abs(template_sat - candidate_sat)) * 1.2,
                        )
                    color_score += weight * pixel_color
                    color_weight += weight
                if template_weight == 0:
                    continue
                recall = overlap_weight / template_weight
                precision = overlap_weight / candidate_weight if candidate_weight else 0.0
                f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
                color = color_score / color_weight if color_weight else 0.0
                score = 0.60 * f1 + 0.40 * color
                if score > best:
                    best = score
    return max(0.0, min(1.0, best))


@lru_cache(maxsize=None)
def _center_weights(size: int) -> tuple[float, ...]:
    center = size / 2.0
    weights: list[float] = []
    for y in range(size):
        for x in range(size):
            dx = (x + 0.5 - center) / center
            dy = (y + 0.5 - center) / center
            radius = math.sqrt(dx * dx + dy * dy)
            weights.append(max(0.20, 1.0 - radius * 0.75))
    return tuple(weights)
