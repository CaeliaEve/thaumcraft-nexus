import unittest

from thaum_nexus.vision import CalibrationProfile, gui_screen_box


class CaptureGeometryTests(unittest.TestCase):
    def test_gui_screen_box_uses_calibration_scale(self):
        profile = CalibrationProfile(gui_left=10, gui_top=20, scale=2)

        self.assertEqual(gui_screen_box(profile), (10, 20, 694, 510))
        self.assertEqual(gui_screen_box(profile, padding=1), (8, 18, 696, 512))


if __name__ == "__main__":
    unittest.main()

