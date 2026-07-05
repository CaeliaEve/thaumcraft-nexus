import unittest

from thaum_nexus.data_model import HexCoord
from thaum_nexus.vision import DEFAULT_GRID_GEOMETRY, HexPresenceDetector
from thaum_nexus.vision.aspect_matcher import Image


@unittest.skipIf(Image is None, "Pillow is not installed")
class HexDetectorTests(unittest.TestCase):
    def test_detector_distinguishes_drawn_hex_from_blank_crop(self):
        from PIL import ImageDraw

        image = Image.new("RGBA", (342, 245), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        polygon = DEFAULT_GRID_GEOMETRY.hex_polygon_gui(HexCoord(0, 0), radius=8)
        draw.line([*polygon, polygon[0]], fill=(180, 120, 60, 255), width=2)

        detector = HexPresenceDetector(min_score=0.06)
        present_box = DEFAULT_GRID_GEOMETRY.gui_crop_box(HexCoord(0, 0), radius=9)
        blank_box = DEFAULT_GRID_GEOMETRY.gui_crop_box(HexCoord(4, 0), radius=9)

        self.assertTrue(detector.detect(image, present_box).present)
        self.assertFalse(detector.detect(image, blank_box).present)


if __name__ == "__main__":
    unittest.main()

