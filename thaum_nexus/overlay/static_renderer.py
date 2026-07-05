from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from thaum_nexus.data_model import Solution
from thaum_nexus.knowledge_base import KnowledgeBase
from thaum_nexus.paths import resource_path, resource_root
from thaum_nexus.vision import CalibrationProfile, DEFAULT_GRID_GEOMETRY, HexGridGeometry
from thaum_nexus.vision.aspect_matcher import Image


@dataclass(frozen=True)
class StaticOverlayRenderer:
    """Render solver placements onto a screenshot image.

    This is the non-interactive precursor to a transparent live overlay. It is
    immediately useful for screenshot-based workflows and is deterministic
    enough to unit-test.
    """

    kb: KnowledgeBase
    project_root: Path | str | None = field(default_factory=resource_root)
    geometry: HexGridGeometry = DEFAULT_GRID_GEOMETRY
    icon_size: int = 24
    ring_color: tuple[int, int, int, int] = (40, 220, 80, 230)
    line_color: tuple[int, int, int, int] = (40, 220, 80, 160)

    def render(
        self,
        screenshot,
        solution: Solution,
        calibration: CalibrationProfile,
        *,
        show_paths: bool = True,
        show_order: bool = True,
    ):
        if Image is None:
            raise RuntimeError("Pillow is required for StaticOverlayRenderer")
        from PIL import ImageDraw, ImageFont

        image = screenshot.convert("RGBA") if screenshot.mode != "RGBA" else screenshot.copy()
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        if show_paths:
            for path in solution.paths:
                points = [self.geometry.axial_to_screen(coord, calibration) for coord in path.coords]
                if len(points) >= 2:
                    draw.line(points, fill=self.line_color, width=max(2, int(round(2 * calibration.scale))))

        font = ImageFont.load_default()
        for index, (coord, aspect_key) in enumerate(sorted(solution.placements.items()), start=1):
            center_x, center_y = self.geometry.axial_to_screen(coord, calibration)
            radius = max(10, int(round(self.icon_size * calibration.scale / 2)))
            draw.ellipse(
                (
                    int(round(center_x - radius - 2)),
                    int(round(center_y - radius - 2)),
                    int(round(center_x + radius + 2)),
                    int(round(center_y + radius + 2)),
                ),
                outline=self.ring_color,
                width=max(2, int(round(2 * calibration.scale))),
            )

            icon = self._load_icon(aspect_key, calibration)
            image.alpha_composite(icon, (int(round(center_x - icon.width / 2)), int(round(center_y - icon.height / 2))))

            if show_order:
                label = str(index)
                text_x = int(round(center_x + radius * 0.45))
                text_y = int(round(center_y - radius * 1.15))
                bbox = draw.textbbox((text_x, text_y), label, font=font)
                padding = 2
                draw.rectangle(
                    (
                        bbox[0] - padding,
                        bbox[1] - padding,
                        bbox[2] + padding,
                        bbox[3] + padding,
                    ),
                    fill=(0, 0, 0, 180),
                )
                draw.text((text_x, text_y), label, fill=(255, 255, 255, 255), font=font)

        return Image.alpha_composite(image, overlay)

    def save(
        self,
        screenshot,
        solution: Solution,
        calibration: CalibrationProfile,
        output: Path,
        *,
        show_paths: bool = True,
        show_order: bool = True,
    ) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        self.render(
            screenshot,
            solution,
            calibration,
            show_paths=show_paths,
            show_order=show_order,
        ).save(output)

    def _load_icon(self, aspect_key: str, calibration: CalibrationProfile):
        aspect = self.kb.require_aspect(aspect_key)
        icon_path = Path(aspect.icon)
        if not icon_path.is_absolute():
            icon_path = resource_path(icon_path, self.project_root)
        icon = Image.open(icon_path).convert("RGBA")
        size = max(8, int(round(self.icon_size * calibration.scale)))
        return icon.resize((size, size), Image.Resampling.LANCZOS)
