import errno
import subprocess
import unittest

from thaum_nexus.client_bridge import OperationCancelled, UnsafeAgentStateError
from thaum_nexus.diagnostics import diagnose_error
from thaum_nexus.solver import NoSolutionError


class DiagnosticsTests(unittest.TestCase):
    def test_concrete_bridge_failures_have_actionable_diagnoses(self):
        cases = [
            ("aspect resources are insufficient: {'aer': 2}", "insufficient_aspects"),
            ("Java agent attach failed with exit code 1", "attach_failed"),
            ("Java agent exported an error: Minecraft currentScreen is null; open the Thaumcraft research table first", "research_table_closed"),
            ("Java agent apply returned an error: unable to read current Thaumcraft research note", "research_note_missing"),
            ("open the GTNH client first, then open the Thaumcraft research table", "client_missing"),
            ("Java agent build script was not found: build.ps1", "agent_missing"),
            ("Failed to build Java agent\nSTDERR: compilation failed", "agent_build_failed"),
            ("Java agent apply finished but did not create result JSON", "agent_result_missing"),
            ("another Thaumcraft Nexus operation is still using JVM 123", "target_busy"),
        ]
        for message, expected in cases:
            with self.subTest(message=message):
                diagnosis = diagnose_error(RuntimeError(message))
                self.assertEqual(diagnosis.code, expected)
                self.assertTrue(diagnosis.title)
                self.assertTrue(diagnosis.advice)
                self.assertIn(message, diagnosis.details)

    def test_uncertain_cancellation_requires_restart_and_is_not_normal_cancellation(self):
        result = diagnose_error(UnsafeAgentStateError("Java Agent did not confirm cancellation"))
        self.assertEqual(result.code, "unsafe_agent_state")
        self.assertIn("重启", result.advice)
        self.assertIn("不要", result.advice)
        self.assertEqual(diagnose_error(OperationCancelled("cancelled")).code, "cancelled")

    def test_file_errors_are_not_misdiagnosed_as_missing_java(self):
        cases = [(FileNotFoundError(errno.ENOENT, "missing", "note.json"), "file_missing"),
                 (PermissionError("denied"), "permission_denied"),
                 (OSError(errno.ENOSPC, "disk full"), "disk_full")]
        for error, expected in cases:
            self.assertEqual(diagnose_error(error).code, expected)

    def test_solver_failure_does_not_claim_no_solution_proven(self):
        result = diagnose_error(NoSolutionError("solver exceeded 256 iterations"))
        self.assertEqual(result.code, "solver_no_solution")
        self.assertIn("未找到", result.title)

    def test_java_missing_requires_executable_path_evidence(self):
        for filename in ("java", r"C:\JDK\bin\java.exe", "/opt/jdk/bin/java"):
            with self.subTest(filename=filename):
                error = FileNotFoundError(errno.ENOENT, "missing", filename)
                self.assertEqual(diagnose_error(error).code, "java_missing")
        self.assertEqual(diagnose_error(FileNotFoundError("missing")).code, "file_missing")

    def test_timeout_preserves_subprocess_output(self):
        result = diagnose_error(subprocess.TimeoutExpired(["java"], 5, output=b"partial", stderr=b"trace"))
        self.assertEqual(result.code, "timeout")
        self.assertIn("partial", result.details)
        self.assertIn("trace", result.details)

    def test_builtin_timeout_is_not_a_filesystem_failure(self):
        result = diagnose_error(TimeoutError("attach timed out"))
        self.assertEqual(result.code, "timeout")
        self.assertIn("attach timed out", result.details)

    def test_unknown_failure_retains_original_technical_details(self):
        result = diagnose_error(ValueError("novel failure: metadata=42"))
        self.assertEqual(result.code, "unknown")
        self.assertIn("ValueError", result.details)
        self.assertIn("novel failure: metadata=42", result.details)
