import unittest
from pathlib import Path

from thaum_nexus import KnowledgeBase
from thaum_nexus.vision.aspect_matcher import AspectMatcher, Image


@unittest.skipIf(Image is None, "Pillow is not installed")
class AspectMatcherTests(unittest.TestCase):
    def test_exact_icon_matches_expected_aspect(self):
        kb = KnowledgeBase.load()
        matcher = AspectMatcher.load(kb)

        aer_icon = kb.aspects["aer"].icon
        result = matcher.match(aer_icon, threshold=0.99)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.key, "aer")
        self.assertGreaterEqual(result.score, 0.99)

    def test_different_primal_icon_is_not_confused_at_high_threshold(self):
        kb = KnowledgeBase.load()
        matcher = AspectMatcher.load(kb)

        ignis_icon = kb.aspects["ignis"].icon
        result = matcher.match(ignis_icon, threshold=0.99)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.key, "ignis")

    def test_match_crop_from_synthetic_screenshot(self):
        kb = KnowledgeBase.load()
        matcher = AspectMatcher.load(kb)
        icon = Image.open(Path(kb.aspects["lux"].icon)).convert("RGBA")
        screenshot = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        screenshot.paste(icon, (32, 32))

        result = matcher.match_crop(screenshot, (32, 32, 96, 96), threshold=0.99)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.key, "lux")


if __name__ == "__main__":
    unittest.main()
