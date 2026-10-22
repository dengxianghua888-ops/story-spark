"""New picker stories require source approval; existing approvals are retained."""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

SPEC = importlib.util.spec_from_file_location("corpus_picker_policy", ROOT / "scripts/corpus-picker.py")
picker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(picker)

storyforge = importlib.import_module("storyforge")


class CorpusPickerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="picker-policy-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "corpus" / "synthetic" / "source.md"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("合成选样原文。", encoding="utf-8")
        self.entry = {"slug": "synthetic", "source_path": "corpus/synthetic/source.md"}
        for name, value in [("ROOT", self.root), ("STORIES_DIR", self.root / "stories")]:
            patcher = patch.object(picker, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def scaffold(self, prefix="picked"):
        return picker._scaffold_story(self.entry, prefix, "synthetic-run")

    def test_new_stories_never_inherit_or_invent_source_approval(self):
        for index, policy in enumerate((None, "denied", "trusted_runners_allowed")):
            with self.subTest(source_policy=policy):
                if policy is not None:
                    (self.source.parent / "story.yaml").write_text(
                        f"source_policy:\n  access: {policy}\n", encoding="utf-8")
                story = self.scaffold(f"picked{index}")
                manifest = yaml.safe_load((story / "story.yaml").read_text(encoding="utf-8"))
                self.assertEqual(manifest["source_policy"]["access"], "denied")
                self.assertEqual((story / "source.md").read_bytes(), self.source.read_bytes())
                self.assertEqual(storyforge.story_source_access(story), "denied")

    def test_new_story_blocks_external_runners_before_run_artifacts_or_provider(self):
        story = self.scaffold()
        for runner in ("agent", "codex", "openclaw", "claude"):
            with self.subTest(runner=runner):
                args = storyforge.build_parser().parse_args([
                    "run", "--story", str(story), "--runner", runner,
                    "--run-id", f"blocked-{runner}", "--no-human-gates",
                ])
                with patch.object(storyforge, "run_phase", side_effect=AssertionError(
                        "A denied source must never reach runner execution")) as execute:
                    self.assertEqual(storyforge.run_pipeline(args), 30)
                    execute.assert_not_called()
                self.assertFalse((story / "runs").exists())

    def test_rescaffolding_preserves_every_existing_story_byte_and_approval(self):
        story = self.scaffold()
        (story / "story.yaml").write_text(
            "slug: picked_synthetic\nsource_policy:\n"
            "  access: trusted_runners_allowed\n  approved_by: human\n"
            "  approved_at: synthetic-explicit-approval\n", encoding="utf-8")
        (story / "owner-note.txt").write_text("保留用户内容。", encoding="utf-8")
        before = {path.relative_to(story): path.read_bytes()
                  for path in story.rglob("*") if path.is_file()}
        self.source.write_text("稍后修订的合成输入。", encoding="utf-8")
        self.assertEqual(self.scaffold(), story)
        after = {path.relative_to(story): path.read_bytes()
                 for path in story.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        self.assertEqual(storyforge.story_source_access(story), "trusted_runners_allowed")

    def test_denied_default_keeps_offline_mock_and_manual_workflows_usable(self):
        for runner, expected in [("mock", 0), ("manual-prompt-pack", 23)]:
            with self.subTest(runner=runner):
                story = self.scaffold(runner)
                result = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/storyforge.py"), "run",
                     "--story", str(story), "--runner", runner, "--run-id", "offline",
                     "--max-retries", "0", "--no-human-gates"],
                    cwd=ROOT, capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
                self.assertEqual(storyforge.story_source_access(story), "denied")
                if runner == "mock":
                    self.assertTrue((story / "final.md").is_file())
                else:
                    self.assertTrue((story / "runs/offline/manual-prompt-pack/phase1.todo.md").is_file())


if __name__ == "__main__":
    unittest.main()
