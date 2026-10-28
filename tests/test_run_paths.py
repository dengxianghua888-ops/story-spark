"""Run-path regressions also execute without third-party test dependencies."""
import sys
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_paths import run_directory  # noqa: E402


class RunPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.story = self.root / "story"
        self.story.mkdir()

    def test_rejects_unsafe_ids_without_writes(self):
        for value in ("", " ", ".", "..", "../other", "nested/run", "nested\\run",
                      str(self.root / "outside"), "bad\x00name", None, 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run_directory(self.story, value)
        self.assertEqual(list(self.story.iterdir()), [])

    def test_valid_names_and_existing_runs(self):
        for name in ("20261019_024500", "retry-2", "测试运行"):
            target = run_directory(self.story, name)
            self.assertEqual(target, self.story / "runs" / name)
            target.mkdir(parents=True)
            (target / "run-manifest.json").write_text("{}")
            self.assertEqual(run_directory(self.story, name), target)

    def test_rejects_symlinked_runs_root(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.story / "runs").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            run_directory(self.story, "new")
        self.assertEqual(list(outside.iterdir()), [])

    def test_rejects_symlinked_run(self):
        runs = self.story / "runs"
        runs.mkdir()
        (runs / "linked").symlink_to(self.root / "missing", target_is_directory=True)
        with self.assertRaises(ValueError):
            run_directory(self.story, "linked")

    def test_rejects_symlinked_run_contents(self):
        target = self.story / "runs" / "r"
        target.mkdir(parents=True)
        (target / "blueprint-approvals").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            run_directory(self.story, "r")

    def test_rejects_file_instead_of_run_directory(self):
        target = self.story / "runs" / "r"
        target.parent.mkdir()
        target.write_text("keep")
        with self.assertRaises(ValueError):
            run_directory(self.story, "r")
        self.assertEqual(target.read_text(), "keep")

    def test_split_cli_rejects_unsafe_run_paths_before_writes(self):
        for kind in ("runs-root", "run", "content", "invalid-id"):
            with self.subTest(kind=kind):
                story = self.root / kind / "story"
                story.mkdir(parents=True)
                (story / "story.yaml").write_text("source_policy:\n  access: trusted_runners_allowed\n")
                outside = story.parent / "outside"
                outside.mkdir()
                (outside / "owner.txt").write_text("OWNER_BYTES")
                run_id = "attempt"
                if kind == "runs-root":
                    (story / "runs").symlink_to(outside, target_is_directory=True)
                elif kind == "run":
                    (story / "runs").mkdir()
                    (story / "runs" / run_id).symlink_to(outside, target_is_directory=True)
                elif kind == "content":
                    target = story / "runs" / run_id
                    target.mkdir(parents=True)
                    (target / "progress.log").symlink_to(outside / "owner.txt")
                else:
                    run_id = "nested\\run"
                marker = story.parent / "provider-called"
                binary = story.parent / "bin"
                binary.mkdir()
                executable = binary / "codex"
                executable.write_text(f"#!{sys.executable}\nfrom pathlib import Path\n"
                                      f"Path({str(marker)!r}).write_text('called')\nraise SystemExit(77)\n")
                executable.chmod(0o700)
                result = subprocess.run([
                    sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/generate_scene_batches.py"),
                    "--story", str(story), "--run-id", run_id, "--no-human-gates",
                ], capture_output=True, text=True,
                    env={**os.environ, "PATH": str(binary) + os.pathsep + os.environ.get("PATH", "")})
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Run", result.stderr)
                self.assertFalse(marker.exists())
                self.assertEqual([(p.name, p.read_bytes()) for p in outside.iterdir()],
                                 [("owner.txt", b"OWNER_BYTES")])
                self.assertFalse(list(story.parent.glob(".story.attempt-*")))


if __name__ == "__main__":
    unittest.main()
