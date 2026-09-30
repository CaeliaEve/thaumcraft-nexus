import unittest

from thaum_nexus.knowledge_base import KnowledgeBase


class ResourcePreviewTests(unittest.TestCase):
    def test_rows_include_synthesis_inputs_and_do_not_call_preflight_stock_live(self):
        from thaum_nexus.resource_preview import describe_resources
        preview = describe_resources(KnowledgeBase.load(), {
            "resources": {"required": {"lux": 2}, "available": {"lux": 1, "aer": 1},
                          "synthesis": [{"output": "lux", "left": "aer", "right": "ignis"}],
                          "shortages": {"ignis": 1}},
            "apply": {"placementsSent": 2, "combinesSent": 1},
        })
        rows = {row.key: row for row in preview.rows}
        self.assertEqual(rows["lux"].required, 2)
        self.assertEqual(rows["lux"].available, 1)
        self.assertEqual(rows["lux"].synthesis, 1)
        self.assertEqual(rows["ignis"].shortage, 1)
        self.assertIn("执行前", preview.summary[0])
        self.assertIn("实际", preview.details)
        self.assertIn("库存", preview.details)

    def test_missing_inventory_is_unknown_instead_of_zero_shortage(self):
        from thaum_nexus.resource_preview import describe_resources
        preview = describe_resources(KnowledgeBase.load(), {})
        self.assertEqual(preview.rows, ())
        self.assertIn("未读取", preview.summary[0])


if __name__ == "__main__":
    unittest.main()
