from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi, sin, sqrt
from pathlib import Path

from thaum_nexus.data_model import BoardState, CellKind, HexCoord, Solution
from thaum_nexus.knowledge_base import KnowledgeBase
from thaum_nexus.vision.aspect_matcher import Image


@dataclass(frozen=True)
class BoardImageRenderer:
    """Render a structured note/solution without relying on screenshots."""

    kb: KnowledgeBase
    project_root: Path | str = Path(__file__).resolve().parents[2]
    hex_size: int = 34
    icon_size: int = 24
    margin: int = 58

    def render(self, board: BoardState, solution: Solution | None = None):
        if Image is None:
            raise RuntimeError("Pillow is required for BoardImageRenderer")
        from PIL import ImageDraw, ImageFont

        coords = set(board.cells)
        if solution is not None:
            coords.update(solution.placements)
        if not coords:
            return Image.new("RGBA", (640, 360), (13, 17, 23, 255))

        raw_positions = {coord: self._axial_to_raw(coord) for coord in coords}
        min_x = min(x for x, _y in raw_positions.values())
        max_x = max(x for x, _y in raw_positions.values())
        min_y = min(y for _x, y in raw_positions.values())
        max_y = max(y for _x, y in raw_positions.values())

        width = int(round(max_x - min_x + self.margin * 2 + self.hex_size * 2))
        height = int(round(max_y - min_y + self.margin * 2 + self.hex_size * 2))
        image = Image.new("RGBA", (max(520, width), max(340, height)), (13, 17, 23, 255))
        draw = ImageDraw.Draw(image, "RGBA")
        font = ImageFont.load_default()

        positions = {
            coord: (
                x - min_x + self.margin + self.hex_size,
                y - min_y + self.margin + self.hex_size,
            )
            for coord, (x, y) in raw_positions.items()
        }

        if solution is not None:
            for path in solution.paths:
                points = [positions[coord] for coord in path.coords if coord in positions]
                if len(points) >= 2:
                    draw.line(points, fill=(46, 160, 67, 130), width=4)

        for coord in sorted(board.cells):
            cell = board.cells[coord]
            center = positions[coord]
            is_solution_cell = solution is not None and coord in solution.placements
            fill = (32, 36, 43, 235)
            outline = (88, 96, 105, 220)
            if cell.kind is CellKind.ROOT:
                outline = (255, 123, 114, 255)
                fill = (52, 38, 41, 245)
            elif cell.kind is CellKind.PLACED:
                outline = (121, 192, 255, 245)
                fill = (31, 48, 61, 245)
            elif is_solution_cell:
                outline = (63, 185, 80, 255)
                fill = (30, 57, 37, 245)
            draw.polygon(self._hex_points(center), fill=fill, outline=outline)
            draw.line(self._hex_points(center) + [self._hex_points(center)[0]], fill=outline, width=2)

        # Draw icons after cells so they stay crisp.
        for coord in sorted(board.cells):
            cell = board.cells[coord]
            aspect = solution.placements.get(coord) if solution is not None and coord in solution.placements else cell.aspect
            if aspect:
                self._paste_icon(image, aspect, positions[coord])

        if solution is not None:
            for index, (coord, _aspect) in enumerate(sorted(solution.placements.items()), start=1):
                if coord not in positions:
                    continue
                x, y = positions[coord]
                label = str(index)
                bbox = draw.textbbox((x + 12, y - 26), label, font=font)
                draw.rounded_rectangle(
                    (bbox[0] - 4, bbox[1] - 3, bbox[2] + 4, bbox[3] + 3),
                    radius=4,
                    fill=(0, 0, 0, 185),
                    outline=(63, 185, 80, 240),
                )
                draw.text((x + 12, y - 26), label, fill=(240, 246, 252, 255), font=font)

        title = board.name or "Thaumcraft research note"
        if solution is not None:
            title += f"  ·  placements: {len(solution.placements)}"
        draw.text((18, 16), title, fill=(201, 209, 217, 255), font=font)
        return image

    def save(self, board: BoardState, solution: Solution | None, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        self.render(board, solution).save(output)

    def _axial_to_raw(self, coord: HexCoord) -> tuple[float, float]:
        x = self.hex_size * 1.5 * coord.q
        y = self.hex_size * sqrt(3.0) * (coord.r + coord.q / 2.0)
        return x, y

    def _hex_points(self, center: tuple[float, float]) -> list[tuple[float, float]]:
        x, y = center
        return [
            (
                x + self.hex_size * cos(pi / 6.0 + i * pi / 3.0),
                y + self.hex_size * sin(pi / 6.0 + i * pi / 3.0),
            )
            for i in range(6)
        ]

    def _paste_icon(self, image, aspect_key: str, center: tuple[float, float]) -> None:
        aspect = self.kb.require_aspect(aspect_key)
        icon_path = Path(aspect.icon)
        if not icon_path.is_absolute():
            icon_path = Path(self.project_root) / icon_path
        icon = Image.open(icon_path).convert("RGBA").resize((self.icon_size, self.icon_size), Image.Resampling.LANCZOS)
        x = int(round(center[0] - icon.width / 2))
        y = int(round(center[1] - icon.height / 2))
        image.alpha_composite(icon, (x, y))
