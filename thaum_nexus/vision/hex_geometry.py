from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from thaum_nexus.data_model import HexCoord
from .calibration import CalibrationProfile


@dataclass(frozen=True)
class HexGridGeometry:
    """Thaumcraft research-note hex grid geometry in base GUI coordinates."""

    gui_width: float = 342.0
    gui_height: float = 245.0
    center_x: float = 171.0
    center_y: float = 110.0
    hex_size: float = 9.0
    parchment_half_width: float = 75.0
    parchment_half_height: float = 75.0

    def axial_to_gui(self, coord: HexCoord) -> tuple[float, float]:
        """Map axial hex coordinate to GUI-space center point."""

        x = self.center_x + 1.5 * coord.q * self.hex_size
        y = self.center_y + sqrt(3.0) * (coord.r + coord.q / 2.0) * self.hex_size
        return x, y

    def axial_to_screen(self, coord: HexCoord, calibration: CalibrationProfile) -> tuple[float, float]:
        return calibration.gui_to_screen(*self.axial_to_gui(coord))

    def gui_crop_box(self, coord: HexCoord, radius: float | None = None) -> tuple[int, int, int, int]:
        """Return a GUI-space square crop box around a hex center.

        The default radius intentionally covers the icon/hex center but stays
        smaller than the distance to neighboring hex centers.
        """

        radius = self.hex_size if radius is None else radius
        x, y = self.axial_to_gui(coord)
        return (
            int(round(x - radius)),
            int(round(y - radius)),
            int(round(x + radius)),
            int(round(y + radius)),
        )

    def screen_crop_box(
        self,
        coord: HexCoord,
        calibration: CalibrationProfile,
        radius: float | None = None,
    ) -> tuple[int, int, int, int]:
        """Return a screen-space square crop box around a hex center."""

        radius = self.hex_size if radius is None else radius
        x, y = self.axial_to_screen(coord, calibration)
        scaled_radius = radius * calibration.scale
        return (
            int(round(x - scaled_radius)),
            int(round(y - scaled_radius)),
            int(round(x + scaled_radius)),
            int(round(y + scaled_radius)),
        )

    def hex_polygon_gui(self, coord: HexCoord, radius: float | None = None) -> tuple[tuple[float, float], ...]:
        """Return pointy-top hex polygon vertices around a coord in GUI space."""

        radius = self.hex_size if radius is None else radius
        center_x, center_y = self.axial_to_gui(coord)
        # Pointy-top orientation. The exact art may differ, but this is useful
        # for tests, overlays, and visual debugging.
        from math import cos, pi, sin

        return tuple(
            (
                center_x + radius * cos(pi / 6.0 + index * pi / 3.0),
                center_y + radius * sin(pi / 6.0 + index * pi / 3.0),
            )
            for index in range(6)
        )

    def hex_polygon_screen(
        self,
        coord: HexCoord,
        calibration: CalibrationProfile,
        radius: float | None = None,
    ) -> tuple[tuple[float, float], ...]:
        return tuple(calibration.gui_to_screen(x, y) for x, y in self.hex_polygon_gui(coord, radius=radius))

    def gui_to_axial_float(self, x: float, y: float) -> tuple[float, float]:
        """Inverse of axial_to_gui before hex rounding."""

        px = (x - self.center_x) / self.hex_size
        py = (y - self.center_y) / self.hex_size
        q = (2.0 / 3.0) * px
        r = (py / sqrt(3.0)) - (q / 2.0)
        return q, r

    def nearest_axial_from_gui(self, x: float, y: float) -> HexCoord:
        q, r = self.gui_to_axial_float(x, y)
        return _hex_round(q, r)

    def nearest_axial_from_screen(self, x: float, y: float, calibration: CalibrationProfile) -> HexCoord:
        gui_x, gui_y = calibration.screen_to_gui(x, y)
        return self.nearest_axial_from_gui(gui_x, gui_y)

    def is_inside_research_area(self, coord: HexCoord, margin: float = 0.0) -> bool:
        x, y = self.axial_to_gui(coord)
        return (
            self.center_x - self.parchment_half_width + margin <= x <= self.center_x + self.parchment_half_width - margin
            and self.center_y - self.parchment_half_height + margin <= y <= self.center_y + self.parchment_half_height - margin
        )

    def candidate_coords(self, margin: float = 0.0) -> tuple[HexCoord, ...]:
        """Enumerate candidate hex centers inside the parchment square.

        Actual research notes use a subset of these cells. Vision still needs to
        classify each candidate as present/absent/empty/root/placed.
        """

        max_q = int(self.parchment_half_width / (1.5 * self.hex_size)) + 2
        max_r = int(self.parchment_half_height / (sqrt(3.0) * self.hex_size)) + max_q + 2
        coords: list[HexCoord] = []
        for q in range(-max_q, max_q + 1):
            for r in range(-max_r, max_r + 1):
                coord = HexCoord(q, r)
                if self.is_inside_research_area(coord, margin=margin):
                    coords.append(coord)
        return tuple(sorted(coords))


DEFAULT_GRID_GEOMETRY = HexGridGeometry()


def _hex_round(q: float, r: float) -> HexCoord:
    """Round fractional axial coordinates to the nearest hex."""

    x = q
    z = r
    y = -x - z

    rx = round(x)
    ry = round(y)
    rz = round(z)

    x_diff = abs(rx - x)
    y_diff = abs(ry - y)
    z_diff = abs(rz - z)

    if x_diff > y_diff and x_diff > z_diff:
        rx = -ry - rz
    elif y_diff > z_diff:
        ry = -rx - rz
    else:
        rz = -rx - ry

    return HexCoord(int(rx), int(rz))
