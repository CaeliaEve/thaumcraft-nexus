import unittest

from thaum_nexus import KnowledgeBase
from thaum_nexus.resources import plan_resource_usage


class ResourcePlanningTests(unittest.TestCase):
    def test_direct_available_aspect_needs_no_synthesis(self):
        kb = KnowledgeBase.load()

        plan = plan_resource_usage(kb, ["lux"], {"lux": 2})

        self.assertTrue(plan.is_sufficient)
        self.assertEqual(plan.synthesis, ())
        self.assertEqual(plan.remaining["lux"], 1)

    def test_missing_composite_is_synthesized_from_components(self):
        kb = KnowledgeBase.load()

        plan = plan_resource_usage(kb, ["lux"], {"aer": 1, "ignis": 1})

        self.assertTrue(plan.is_sufficient)
        self.assertEqual([step.to_dict() for step in plan.synthesis], [{"output": "lux", "left": "aer", "right": "ignis"}])
        self.assertEqual(plan.remaining, {})

    def test_shortage_reports_missing_component(self):
        kb = KnowledgeBase.load()

        plan = plan_resource_usage(kb, ["lux"], {"aer": 1})

        self.assertFalse(plan.is_sufficient)
        self.assertEqual(plan.shortages, {"ignis": 1})
        self.assertEqual(plan.synthesis, ())
        self.assertEqual(plan.remaining, {"aer": 1})


if __name__ == "__main__":
    unittest.main()
