import json
from pathlib import Path
import subprocess
import sys
import unittest

class SolverBenchmarkTests(unittest.TestCase):
    def test_cli_reports_validity_resources_and_timing_on_real_fixtures(self):
        result = subprocess.run([sys.executable, 'tools/benchmark_solver.py', '--generated', '0'],
                                text=True, capture_output=True, check=True)
        report = json.loads(result.stdout)
        self.assertEqual(report['summary']['valid'], 2)
        self.assertEqual(report['summary']['failed'], 0)
        self.assertEqual([row['placements'] for row in report['cases']], [2, 1])
        for row in report['cases']:
            self.assertGreaterEqual(row['seconds'], 0)
            self.assertIn('shortages', row)
            self.assertIn('synthesis_steps', row)
