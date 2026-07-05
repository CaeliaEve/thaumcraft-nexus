import unittest

from thaum_nexus.data_model import HexCoord
from thaum_nexus.vision import CalibrationProfile, DEFAULT_GRID_GEOMETRY


class VisionGeometryTests(unittest.TestCase):
    def test_calibration_round_trip_gui_screen_coordinates(self):
        profile = CalibrationProfile(gui_left=100, gui_top=200, scale=2.0)

        screen = profile.gui_to_screen(171, 110)
        self.assertEqual(screen, (442, 420))
        self.assertEqual(profile.screen_to_gui(*screen), (171, 110))

    def test_axial_gui_round_trip(self):
        geom = DEFAULT_GRID_GEOMETRY

        for coord in [HexCoord(0, 0), HexCoord(1, 0), HexCoord(1, -1), HexCoord(-2, 3)]:
            x, y = geom.axial_to_gui(coord)
            self.assertEqual(geom.nearest_axial_from_gui(x, y), coord)

    def test_candidate_coords_include_center_and_known_neighbors(self):
        coords = set(DEFAULT_GRID_GEOMETRY.candidate_coords())

        self.assertIn(HexCoord(0, 0), coords)
        self.assertIn(HexCoord(1, 0), coords)
        self.assertIn(HexCoord(0, 1), coords)
        self.assertGreater(len(coords), 50)

    def test_screen_crop_box_scales_around_hex_center(self):
        geom = DEFAULT_GRID_GEOMETRY
        profile = CalibrationProfile(gui_left=100, gui_top=200, scale=2.0)

        self.assertEqual(
            geom.screen_crop_box(HexCoord(0, 0), profile, radius=9),
            (424, 402, 460, 438),
        )


if __name__ == "__main__":
    unittest.main()
