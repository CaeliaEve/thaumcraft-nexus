import unittest

from thaum_nexus import KnowledgeBase
from thaum_nexus.data_model import HexCoord, Solution
from thaum_nexus.overlay import StaticOverlayRenderer
from thaum_nexus.vision import CalibrationProfile, DEFAULT_GRID_GEOMETRY
from thaum_nexus.vision.aspect_matcher import Image


@unittest.skipIf(Image is None, "Pillow is not installed")
class StaticRendererTests(unittest.TestCase):
    def test_renderer_draws_solution_icon_at_expected_center(self):
        kb = KnowledgeBase.load()
        renderer = StaticOverlayRenderer(kb, icon_size=24)
        screenshot = Image.new("RGBA", (342, 245), (0, 0, 0, 0))
        solution = Solution(placements={HexCoord(1, 0): "lux"})
        calibration = CalibrationProfile(0, 0, 1)

        rendered = renderer.render(screenshot, solution, calibration)

        center = DEFAULT_GRID_GEOMETRY.axial_to_screen(HexCoord(1, 0), calibration)
        pixel = rendered.getpixel((round(center[0]), round(center[1])))
        self.assertGreater(pixel[3], 0)


if __name__ == "__main__":
    unittest.main()

