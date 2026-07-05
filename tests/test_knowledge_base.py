import unittest

from thaum_nexus import KnowledgeBase


class KnowledgeBaseTests(unittest.TestCase):
    def test_generated_knowledge_base_counts_and_edges(self):
        kb = KnowledgeBase.load()

        self.assertEqual(len(kb.aspects), 69)
        self.assertEqual(set(kb.primal), {"aer", "aqua", "ignis", "ordo", "perditio", "terra"})
        self.assertEqual(len(kb.by_output), 63)

        self.assertEqual(kb.combination_result("aer", "ignis"), "lux")
        self.assertTrue(kb.can_connect("aer", "lux"))
        self.assertTrue(kb.can_connect("lux", "ignis"))
        self.assertFalse(kb.can_connect("aer", "ignis"))

    def test_depth_prefers_primal_then_composite(self):
        kb = KnowledgeBase.load()

        self.assertEqual(kb.aspect_depth("aer"), 0)
        self.assertEqual(kb.aspect_depth("lux"), 1)
        self.assertGreater(kb.aspect_depth("alienis"), kb.aspect_depth("lux"))


if __name__ == "__main__":
    unittest.main()
