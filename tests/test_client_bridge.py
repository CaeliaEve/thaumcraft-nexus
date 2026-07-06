import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from thaum_nexus import client_bridge
from thaum_nexus.client_bridge import apply_solution_to_current_note, solution_to_apply_plan
from thaum_nexus.data_model import HexCoord, Solution
from thaum_nexus.resources import ResourcePlan, SynthesisStep


class ClientBridgeTests(unittest.TestCase):
    def test_java_attacher_recognizes_prism_launcher_entrypoint(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "java-agent"
            / "src"
            / "main"
            / "java"
            / "thaumnexus"
            / "agent"
            / "ThaumNexusAttacher.java"
        ).read_text(encoding="utf-8")

        self.assertIn("org.prismlauncher.entrypoint", source)
        self.assertIn("org.multimc.entrypoint", source)

    def test_java_agent_prefers_game_classloader_for_thaumcraft_classes(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "java-agent"
            / "src"
            / "main"
            / "java"
            / "thaumnexus"
            / "agent"
            / "ThaumNexusAgentV3.java"
        ).read_text(encoding="utf-8")

        self.assertIn("Thread.currentThread().setContextClassLoader(gameLoader)", source)
        self.assertIn("candidateGameClassLoaders", source)
        self.assertIn("findLoadedClass(name, loadedClasses, gameLoaders, false)", source)
        self.assertIn('name.startsWith("thaumcraft.")', source)
        self.assertIn("catch (LinkageError ignored)", source)
        self.assertNotIn("Class.forName(name);", source)

    def test_java_agent_apply_plan_supports_cancel_file(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "java-agent"
            / "src"
            / "main"
            / "java"
            / "thaumnexus"
            / "agent"
            / "ThaumNexusAgentV3.java"
        ).read_text(encoding="utf-8")

        self.assertIn('\\"cancelFile\\"', source)
        self.assertIn("sleepCancelled", source)
        self.assertIn("isCancelRequested(plan)", source)
        self.assertIn('"cancelled"', source)

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

    def test_solution_to_apply_plan_includes_cancel_file(self):
        solution = Solution(placements={HexCoord(1, 0): "lux"})

        plan = solution_to_apply_plan(solution, cancel_file=Path("runtime/apply.cancel"))

        self.assertEqual(plan["cancelFile"], "runtime\\apply.cancel" if os.name == "nt" else "runtime/apply.cancel")

    def test_cancellable_subprocess_stops_promptly(self):
        stop_event = threading.Event()
        timer = threading.Timer(0.15, stop_event.set)
        started = time.monotonic()
        timer.start()
        try:
            with self.assertRaises(client_bridge.OperationCancelled):
                client_bridge._run_cancellable_subprocess(
                    [sys.executable, "-c", "import time; time.sleep(5)"],
                    cwd=str(Path.cwd()),
                    timeout=10.0,
                    stop_event=stop_event,
                )
        finally:
            timer.cancel()

        self.assertLess(time.monotonic() - started, 2.0)

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

    def test_hidden_subprocess_kwargs_prevent_console_popups_on_windows(self):
        kwargs = client_bridge._hidden_subprocess_kwargs()

        if os.name == "nt":
            self.assertIn("creationflags", kwargs)
            self.assertIn("startupinfo", kwargs)
        else:
            self.assertEqual(kwargs, {})

    def test_java_diagnostics_reports_core_paths(self):
        with mock.patch.object(client_bridge, "find_java", return_value="java"), mock.patch.object(
            client_bridge,
            "find_tools_jar",
            return_value=None,
        ), mock.patch.object(client_bridge, "_java_version_text", return_value='java version "1.8.0_test"'):
            payload = client_bridge.java_environment_diagnostics()

        self.assertEqual(payload["java"], "java")
        self.assertIn("tools.jar", payload["warning"])
        self.assertEqual(payload["javaVersion"], 'java version "1.8.0_test"')

    def test_parse_jps_output_returns_pid_and_display_name(self):
        processes = client_bridge._parse_jps_output(
            "12808 org.prismlauncher.EntryPoint -Dfoo=bar\n"
            "8948 thaumnexus.agent.ThaumNexusAttacher agent.jar\n"
            "not-a-pid ignored\n"
        )

        self.assertEqual(processes[0].pid, "12808")
        self.assertIn("org.prismlauncher.EntryPoint", processes[0].display_name)
        self.assertEqual(processes[1].label, "8948  thaumnexus.agent.ThaumNexusAttacher agent.jar")

    def test_parse_java_major_version_supports_8_and_modern_versions(self):
        self.assertEqual(client_bridge._parse_java_major_version('java version "1.8.0_491"'), 8)
        self.assertEqual(client_bridge._parse_java_major_version('openjdk version "17.0.12" 2024-07-16'), 17)
        self.assertEqual(client_bridge._parse_java_major_version('openjdk version "21.0.5" 2024-10-15'), 21)
        self.assertEqual(client_bridge._parse_java_major_version('openjdk version "25" 2025-09-16'), 25)
        self.assertEqual(client_bridge._parse_java_major_version('openjdk version "25-ea" 2025-09-16'), 25)
        self.assertIsNone(client_bridge._parse_java_major_version("OpenJDK 64-Bit Server VM warning: INFO"))

    def test_attacher_command_uses_tools_jar_for_java8(self):
        runtime = client_bridge.JavaRuntime(
            java="C:/jdk8/bin/java.exe",
            java_home=Path("C:/jdk8"),
            major=8,
            tools_jar=Path("C:/jdk8/lib/tools.jar"),
            source="test",
        )

        cmd = client_bridge._build_attacher_command(
            runtime,
            Path("agent.jar"),
            ["export", "out.json"],
            pid="123",
        )

        self.assertNotIn("--add-modules", cmd)
        self.assertIn("-Xms16m", cmd)
        self.assertIn("-Xmx128m", cmd)
        self.assertIn("tools.jar", cmd[cmd.index("-cp") + 1])
        self.assertEqual(cmd[-1], "123")

    def test_attacher_command_uses_jdk_attach_module_for_java17_plus(self):
        runtime = client_bridge.JavaRuntime(
            java="C:/jdk21/bin/java.exe",
            java_home=Path("C:/jdk21"),
            major=21,
            source="test",
        )

        cmd = client_bridge._build_attacher_command(
            runtime,
            Path("agent.jar"),
            ["export", "out.json"],
            pid="456",
        )

        self.assertIn("-Xms16m", cmd)
        self.assertIn("-Xmx128m", cmd)
        self.assertIn("--add-modules", cmd)
        self.assertIn("jdk.attach", cmd)
        self.assertEqual(cmd[cmd.index("-cp") + 1], "agent.jar")
        self.assertEqual(cmd[-1], "456")

    def test_attacher_runtime_prefers_target_process_java_for_modern_jvm(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "jdk-21"
            bin_dir = home / "bin"
            bin_dir.mkdir(parents=True)
            java = bin_dir / "java.exe"
            javaw = bin_dir / "javaw.exe"
            java.write_bytes(b"")
            javaw.write_bytes(b"")

            with mock.patch.object(
                client_bridge,
                "_windows_process_info",
                return_value={"executablePath": str(javaw)},
            ), mock.patch.object(
                client_bridge,
                "_java_major_version",
                return_value=21,
            ), mock.patch.object(
                client_bridge,
                "_java_supports_jdk_attach",
                return_value=True,
            ):
                runtime = client_bridge._select_attacher_runtime("456")

        self.assertEqual(runtime.java, str(java))
        self.assertEqual(runtime.major, 21)
        self.assertEqual(runtime.source, "target-pid:456")

    def test_minecraft_pid_auto_detection_recognizes_prism_process(self):
        with mock.patch.object(
            client_bridge,
            "list_java_processes",
            return_value=[
                client_bridge.JavaProcess(pid="1", display_name="jdk.jcmd/sun.tools.jps.Jps"),
                client_bridge.JavaProcess(pid="2", display_name="org.prismlauncher.EntryPoint"),
            ],
        ):
            self.assertEqual(client_bridge._choose_minecraft_jvm_pid(), "2")

    def test_bundled_jdk_is_preferred_over_system_java(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "jdk"
            (bundled / "bin").mkdir(parents=True)
            (bundled / "lib").mkdir()
            java = bundled / "bin" / "java.exe"
            tools = bundled / "lib" / "tools.jar"
            java.write_bytes(b"")
            tools.write_bytes(b"")

            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
                client_bridge,
                "app_root",
                return_value=root,
            ), mock.patch.object(
                client_bridge,
                "resource_root",
                return_value=root,
            ), mock.patch.object(
                client_bridge.shutil,
                "which",
                return_value=None,
            ):
                self.assertEqual(client_bridge.find_java(), str(java))
                self.assertEqual(client_bridge.find_tools_jar(), tools)

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

    def test_wheelchair_reuses_initial_inventory_queue_between_notes(self):
        def current_note(key: str) -> client_bridge.CurrentNoteResult:
            return client_bridge.CurrentNoteResult(
                note=SimpleNamespace(complete=False, research_key=key, board=SimpleNamespace(name=key)),
                solution=Solution(placements={HexCoord(0, 0): "aer"}),
                note_json_path=Path(f"runtime/{key}.json"),
                resource_plan=None,
            )

        export_inventory = mock.Mock(
            side_effect=[
                (
                    {
                        "notes": [
                            {"slot": 1, "slotKind": "table-note", "researchKey": "TABLE", "complete": False},
                            {"slot": 3, "slotKind": "inventory", "researchKey": "A", "complete": False},
                            {"slot": 4, "slotKind": "inventory", "researchKey": "B", "complete": False},
                        ]
                    },
                    Path("runtime/inventory_notes.json"),
                    "",
                    "",
                ),
                (
                    {"notes": [{"slot": 1, "slotKind": "table-note", "researchKey": "B", "complete": True}]},
                    Path("runtime/wheelchair_inventory_final_03.json"),
                    "",
                    "",
                ),
            ]
        )
        read_current = mock.Mock(side_effect=[current_note("TABLE"), current_note("A"), current_note("B")])
        apply_current = mock.Mock(
            return_value=(
                {"placementsSent": 1, "combinesSent": 0},
                Path("runtime/apply_plan.json"),
                Path("runtime/apply_result.json"),
                "",
                "",
            )
        )
        load_note = mock.Mock(
            side_effect=[
                ({"status": "ok"}, Path("runtime/load_a.json"), "", ""),
                ({"status": "ok"}, Path("runtime/load_b.json"), "", ""),
            ]
        )

        with mock.patch.object(client_bridge, "export_inventory_notes", export_inventory), mock.patch.object(
            client_bridge, "read_and_solve_current_note", read_current
        ), mock.patch.object(client_bridge, "apply_solution_to_current_note", apply_current), mock.patch.object(
            client_bridge, "load_inventory_note_slot", load_note
        ):
            payload = client_bridge.solve_all_inventory_notes(Path("."), apply=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["solvedOrAttempted"], 3)
        self.assertEqual(export_inventory.call_count, 2)
        self.assertEqual(read_current.call_count, 3)
        self.assertEqual(apply_current.call_count, 3)
        self.assertEqual([call.args[0] for call in load_note.call_args_list], [3, 4])


if __name__ == "__main__":
    unittest.main()
