"""Offline entry-point regressions; never invoke an external model."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_scene_batches as batches  # noqa: E402
import storyforge  # noqa: E402
from source_policy import story_source_access  # noqa: E402
from storyforge_lib import write_json, write_text  # noqa: E402


class SplitSourcePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="split-source-policy-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.story = self.base / "story"
        write_text(self.story / "source.md", "完全合成的离线原文。")
        write_text(self.story / "story.yaml", "source_policy:\n  access: denied\n")
        write_text(self.story / "analysis/style-dna.md", "短句")
        write_json(self.story / "beat-bible.json", {})
        write_json(self.story / "scene-cards/scene-01.json", {
            "scene_id": "scene-01", "target_chars_min": 100, "target_chars_max": 200,
        })
        write_text(self.story / "draft.md", "已审阅旧稿")

    def invoke(self, *options):
        argv = ["generate_scene_batches.py", "--story", str(self.story),
                "--run-id", "test", "--retries", "1", *options]
        with patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()):
            return batches.main()

    def artifacts(self):
        return {str(p.relative_to(self.story)): p.read_bytes()
                for p in self.story.rglob("*") if p.is_file()
                and "runs" not in p.relative_to(self.story).parts}

    def test_denial_precedes_blueprint_bypass_and_review_and_preserves_story(self):
        for options in (("--no-human-gates",), ("--approval-run-id", "approved")):
            with self.subTest(options=options):
                before = self.artifacts()
                with patch.object(batches, "run_codex") as provider, patch.object(
                        batches, "check_blueprint_approval") as approval:
                    self.assertEqual(self.invoke(*options), 30)
                    provider.assert_not_called()
                    approval.assert_not_called()
                self.assertEqual(self.artifacts(), before)
                self.assertFalse((self.story / "runs").exists())
                self.assertFalse(list(self.base.glob(".story.attempt-*")))

    def test_malformed_policies_match_pipeline_and_block_before_prompt(self):
        for text in ("source_policy: [broken", "[]", "null", "source_policy: null",
                     "source_policy: []", "source_policy:\n  access: 'denied'\n"):
            with self.subTest(text=text):
                write_text(self.story / "story.yaml", text)
                self.assertEqual(story_source_access(self.story), "denied")
                self.assertEqual(storyforge.story_source_access(self.story), "denied")
                with patch.object(batches, "prompt_for_batch") as prompt, patch.object(
                        batches, "run_codex") as provider:
                    self.assertEqual(self.invoke("--no-human-gates"), 30)
                    prompt.assert_not_called()
                    provider.assert_not_called()

    def fake_codex(self):
        executable = self.base / "bin" / "codex"
        write_text(executable, f"#!{sys.executable}\nfrom pathlib import Path\n"
                   f"Path({str(self.base / 'provider-started')!r}).write_text('started')\n"
                   "raise SystemExit(42)\n")
        executable.chmod(0o700)
        return {**os.environ, "PATH": str(executable.parent) + os.pathsep + os.environ.get("PATH", "")}

    def test_actual_denied_cli_never_starts_synthetic_provider(self):
        result = subprocess.run([
            sys.executable, str(ROOT / "scripts/generate_scene_batches.py"),
            "--story", str(self.story), "--run-id", "cli", "--no-human-gates",
        ], env=self.fake_codex(), capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 30, result.stdout + result.stderr)
        self.assertIn("source_policy.access=denied", result.stderr)
        self.assertFalse((self.base / "provider-started").exists())
        self.assertFalse((self.story / "runs").exists())

    def test_explicit_approval_and_legacy_cli_reach_synthetic_provider(self):
        for text in ("source_policy:\n  access: trusted_runners_allowed\n", None):
            with self.subTest(text=text):
                manifest = self.story / "story.yaml"
                if text is None:
                    manifest.unlink()
                else:
                    write_text(manifest, text)
                before = self.artifacts()
                result = subprocess.run([
                    sys.executable, str(ROOT / "scripts/generate_scene_batches.py"),
                    "--story", str(self.story), "--run-id", "allowed", "--no-human-gates",
                ], env=self.fake_codex(), capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("codex failed", result.stderr)
                self.assertTrue((self.base / "provider-started").exists())
                self.assertEqual(self.artifacts(), before)
                (self.base / "provider-started").unlink()

    def test_revoked_source_stops_retry_without_second_provider_or_publication(self):
        write_text(self.story / "story.yaml", "source_policy:\n  access: trusted_runners_allowed\n")
        def revoke_and_fail(prompt, output, *args):
            write_text(self.story / "story.yaml", "source_policy:\n  access: denied\n")
            write_text(output, "invalid bundle")
            return subprocess.CompletedProcess([], 0, "", "")
        with patch.object(batches, "run_codex", side_effect=revoke_and_fail) as provider:
            self.assertEqual(self.invoke("--no-human-gates"), 30)
            self.assertEqual(provider.call_count, 1)
        self.assertEqual((self.story / "draft.md").read_text(), "已审阅旧稿")
        self.assertEqual(story_source_access(self.story), "denied")
        report = json.loads((self.story / "runs/test/split-scene-report.json").read_text())
        self.assertEqual(report["status"], "failed")
        self.assertIn("source_policy.access=denied", report["error"])

    def test_revocation_during_last_call_preserves_live_story(self):
        write_text(self.story / "story.yaml", "source_policy:\n  access: trusted_runners_allowed\n")
        prose = '“阿白轻轻拿着纸条，站在窗边问话吗？”\n' * 8
        def revoke_and_succeed(prompt, output, *args):
            write_text(output, f"<<<FILE: draft-scenes/scene-01.md>>>\n{prose}\n<<<END FILE>>>\n")
            write_text(self.story / "story.yaml", "source_policy:\n  access: denied\n")
            return subprocess.CompletedProcess([], 0, "", "")
        with patch.object(batches, "run_codex", side_effect=revoke_and_succeed) as provider:
            self.assertEqual(self.invoke("--no-human-gates"), 30)
            self.assertEqual(provider.call_count, 1)
        self.assertEqual((self.story / "draft.md").read_text(), "已审阅旧稿")
        self.assertFalse((self.story / "draft-scenes").exists())
        self.assertEqual(story_source_access(self.story), "denied")


if __name__ == "__main__":
    unittest.main()
