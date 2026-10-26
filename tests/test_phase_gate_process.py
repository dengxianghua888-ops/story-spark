"""Gate JSON must agree with process success; these subprocesses are synthetic."""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import phase_gate as gate  # noqa: E402


class PhaseGateProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="phase-gate-process-")
        self.addCleanup(self.temp.cleanup)
        self.story = Path(self.temp.name)
        # The repository benchmark is only an existence gate for rubric dispatch.
        # Do not depend on the owner's benchmark data in these synthetic tests.
        self.root = self.story / "repo"
        (self.root / "context").mkdir(parents=True)
        (self.root / "context/tomato-benchmark.json").write_text("{}")

    @staticmethod
    def process(payload, code):
        return subprocess.run([
            sys.executable, "-c", "import sys; print(sys.argv[1]); sys.exit(int(sys.argv[2]))",
            payload, str(code),
        ], capture_output=True, text=True, check=False)

    def invoke(self, proc, *, rubric=False):
        with patch.object(gate, "ROOT", self.root), patch.object(
                gate, "_run_repairs", return_value={"status": "ok"}), patch.object(
                gate.subprocess, "run", return_value=proc):
            if rubric:
                with patch.object(gate, "_run_validator", return_value={"status": "pass"}):
                    return gate.run_gate(self.story, 7, "production", 8, True)
            return gate.run_gate(self.story, 1, "production", 8, False)

    def test_nonzero_validator_cannot_pass_even_when_its_json_says_pass(self):
        result = self.invoke(self.process('{"status":"pass"}', 23))
        self.assertEqual(result["status"], "validator_fail")
        self.assertEqual(result["validator"]["exit_code"], 23)
        self.assertIn("validator exited with code 23", result["failures"])

    def test_nonzero_rubric_cannot_pass_even_when_its_json_says_pass(self):
        result = self.invoke(self.process('{"status":"pass"}', 25), rubric=True)
        self.assertEqual(result["status"], "rubric_fail")
        self.assertEqual(result["rubric"]["exit_code"], 25)
        self.assertIn("rubric exited with code 25", result["rubric"]["failures"])

    def test_invalid_or_nonobject_json_fails_with_a_report_for_both_tools(self):
        for rubric in (False, True):
            for raw in ("", "not JSON", "[]", "null", "true", '"text"',
                        "{}", '{"status":"skipped"}', '{"status":[]}',
                        '{"status":"fail","failures":"a reason"}'):
                with self.subTest(rubric=rubric, raw=raw):
                    result = self.invoke(self.process(raw, 0), rubric=rubric)
                    self.assertEqual(result["status"], "rubric_fail" if rubric else "validator_fail")
                    written = json.loads((self.story / "phase-gate-report.json").read_text())
                    self.assertEqual(written["status"], result["status"])

    def test_successful_pass_and_explicit_failure_stay_distinct(self):
        for rubric in (False, True):
            for status in ("pass", "fail"):
                with self.subTest(rubric=rubric, status=status):
                    result = self.invoke(self.process(json.dumps({"status": status}), 0), rubric=rubric)
                    expected = "pass" if status == "pass" else "rubric_fail" if rubric else "validator_fail"
                    self.assertEqual(result["status"], expected)

    def test_cli_exit_codes_follow_checked_gate_result(self):
        for rubric, expected in ((False, 23), (True, 25)):
            proc = self.process('{"status":"pass"}', expected)
            with self.subTest(rubric=rubric), patch.object(gate, "ROOT", self.root), patch.object(
                    gate, "_run_repairs", return_value={"status": "ok"}), patch.object(
                    gate.subprocess, "run", return_value=proc), patch.object(sys, "argv", [
                        "phase_gate.py", "--story", str(self.story), "--phase", "7", "--json",
                    ] + ([] if rubric else ["--no-rubric"])), contextlib.redirect_stdout(io.StringIO()):
                if rubric:
                    with patch.object(gate, "_run_validator", return_value={"status": "pass"}):
                        self.assertEqual(gate.main(), expected)
                else:
                    self.assertEqual(gate.main(), expected)


if __name__ == "__main__":
    unittest.main()
