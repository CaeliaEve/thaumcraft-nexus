import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from thaum_nexus import client_bridge
from thaum_nexus.client_bridge import apply_solution_to_current_note, solution_to_apply_plan
from thaum_nexus.data_model import HexCoord, Solution
from thaum_nexus.resources import ResourcePlan, SynthesisStep


class ClientBridgeTests(unittest.TestCase):
    def test_solution_to_apply_plan_is_java_agent_friendly(self):
        solution = Solution(
            placements={
                HexCoord(1, 0): "lux",
                HexCoord(-1, 2): "motus",
            }
        )

        plan = solution_to_apply_plan(solution, delay_ms=25, verify_delay_ms=50)

        self.assertEqual(plan["action"], "apply-placements")
        self.assertEqual(plan["delayMs"], 25)
        self.assertEqual(plan["verifyDelayMs"], 50)
        self.assertEqual(
            plan["placements"],
            [
                {"q": -1, "r": 2, "aspect": "motus"},
                {"q": 1, "r": 0, "aspect": "lux"},
            ],
        )
        self.assertEqual(plan["combines"], [])

    def test_solution_to_apply_plan_includes_synthesis_steps(self):
        solution = Solution(placements={HexCoord(1, 0): "lux"})
        resources = ResourcePlan(
            required={"lux": 1},
            available={"aer": 1, "ignis": 1},
            synthesis=(SynthesisStep(output="lux", left="aer", right="ignis"),),
        )

        plan = solution_to_apply_plan(solution, resource_plan=resources)

        self.assertEqual(plan["action"], "apply-synthesis-and-placements")
        self.assertEqual(plan["combines"], [{"output": "lux", "left": "aer", "right": "ignis"}])

    def test_empty_solution_apply_is_local_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload, plan, result, stdout, stderr = apply_solution_to_current_note(
                Solution(placements={}),
                root,
                build_if_needed=False,
            )

        self.assertEqual(payload["placementsRequested"], 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        self.assertTrue(plan.name.endswith("apply_plan.json"))
        self.assertTrue(result.name.endswith("apply_result.json"))

    def test_agent_jar_path_prefers_packaged_jar_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packaged = root / "java-agent" / "thaum-nexus-agent.jar"
            packaged.parent.mkdir(parents=True)
            packaged.write_bytes(b"jar")

            self.assertEqual(client_bridge.agent_jar_path(root), packaged)

    def test_wheelchair_honors_stop_after_safe_inventory_scan(self):
        stop_event = threading.Event()
        stop_event.set()
        progress: list[dict[str, object]] = []

        with mock.patch.object(
            client_bridge,
            "export_inventory_notes",
            return_value=(
                {"notes": [{"slot": 3, "slotKind": "inventory", "researchKey": "A", "complete": False}]},
                Path("runtime/inventory_notes.json"),
                "",
                "",
            ),
        ), mock.patch.object(client_bridge, "read_and_solve_current_note") as read_current:
            payload = client_bridge.solve_all_inventory_notes(
                Path("."),
                apply=True,
                stop_event=stop_event,
                progress_callback=progress.append,
            )

        self.assertEqual(payload["status"], "cancelled")
        self.assertEqual(payload["solvedOrAttempted"], 0)
        read_current.assert_not_called()
        self.assertTrue(any(item["event"] == "inventory-scan-done" for item in progress))


if __name__ == "__main__":
    unittest.main()
