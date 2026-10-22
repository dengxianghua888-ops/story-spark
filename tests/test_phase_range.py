"""Exercise CLI phase bounds without starting an external runner."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PhaseRangeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="story-phase-range-")
        self.addCleanup(self.directory.cleanup)
        self.story = Path(self.directory.name) / "story"
        self.story.mkdir()
        (self.story / "source.md").write_text("合成阶段范围测试原文。", encoding="utf-8")

    def run_cli(self, mode, *arguments):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "storyforge.py"), "run",
             "--story", str(self.story), "--runner", "mock", "--mode", mode,
             "--run-id", "phase-range", *map(str, arguments)],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )

    def assert_rejected_without_run(self, result):
        self.assertEqual(result.returncode, 11, result.stderr + result.stdout)
        self.assertFalse((self.story / "runs").exists())
        self.assertEqual(list(self.story.iterdir()), [self.story / "source.md"])

    def test_start_phase_outside_mode_is_rejected_before_run_creation(self):
        for mode, maximum in [("v4", 5), ("production", 8), ("ultra_short", 8)]:
            for phase in range(maximum + 1, 10):
                with self.subTest(mode=mode, phase=phase):
                    result = self.run_cli(mode, "--from-phase", phase)
                    self.assert_rejected_without_run(result)
                    self.assertIn("--from-phase", result.stderr)

    def test_end_phase_outside_mode_is_rejected_instead_of_truncated(self):
        for mode, phase in [("v4", 6), ("production", 9), ("ultra_short", 9)]:
            with self.subTest(mode=mode):
                result = self.run_cli(mode, "--to-phase", phase)
                self.assert_rejected_without_run(result)
                self.assertIn("--to-phase", result.stderr)

    def test_reversed_range_is_rejected_before_run_creation(self):
        result = self.run_cli("v4", "--from-phase", 3, "--to-phase", 2)
        self.assert_rejected_without_run(result)
        self.assertIn("must be >= --from-phase", result.stderr)

    def test_last_phase_and_aliases_are_accepted_in_each_mode(self):
        for mode, maximum in [("v4", 5), ("full", 5), ("production", 8),
                              ("prod", 8), ("ultra_short", 8), ("production_v6", 9),
                              ("v6", 9)]:
            with self.subTest(mode=mode):
                result = self.run_cli(mode, "--from-phase", maximum,
                                      "--to-phase", maximum, "--dry-run")
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertTrue((self.story / "runs" / "phase-range" /
                                 f"phase{maximum}.prompt.md").is_file())


if __name__ == "__main__":
    unittest.main()
