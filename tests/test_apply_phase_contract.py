"""Standalone apply supports the same mode coordinates as the pipeline."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ApplyPhaseContract(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.story = self.base / "story"
        self.story.mkdir()
        (self.story / "source.md").write_text("SYNTHETIC_APPLY_SOURCE")
        self.bundle = self.base / "bundle.txt"
        self.bundle.write_text('<<<FILE: feedback-learning.json>>>\n{"marker":"feedback-nine"}\n<<<END FILE>>>\n')

    def cli(self, phase, mode):
        return subprocess.run([
            sys.executable, str(ROOT / "scripts/apply-artifact-bundle.py"),
            "--story", str(self.story), "--phase", str(phase), "--mode", mode,
            "--bundle", str(self.bundle), "--run-dir", str(self.story / "runs/apply")],
            capture_output=True, text=True, timeout=30)

    def test_v6_feedback_phase_nine_and_aliases_apply_atomically(self):
        for mode in ["production_v6", "prod_v6", "v6"]:
            with self.subTest(mode=mode):
                result = self.cli(9, mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual((report["phase"], report["mode"]), (9, "production_v6"))
                self.assertEqual(json.loads((self.story / "feedback-learning.json").read_text()),
                                 {"marker": "feedback-nine"})
        self.assertEqual((self.story / "source.md").read_text(), "SYNTHETIC_APPLY_SOURCE")

    def test_mode_range_rejection_preserves_legacy_exit_one_without_staging(self):
        for phase, mode in [(6, "v4"), (9, "production"), (9, "ultra_short")]:
            with self.subTest(phase=phase, mode=mode):
                result = self.cli(phase, mode)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(list(self.base.glob(".story.attempt-*")))
                self.assertFalse((self.story / "runs").exists())
        self.assertEqual((self.story / "source.md").read_text(), "SYNTHETIC_APPLY_SOURCE")

    def test_global_invalid_values_keep_argparse_exit_two(self):
        for phase in [0, 10, "invalid"]:
            with self.subTest(phase=phase):
                self.assertEqual(self.cli(phase, "production_v6").returncode, 2)
        self.assertFalse((self.story / "runs").exists())


if __name__ == "__main__":
    unittest.main()
