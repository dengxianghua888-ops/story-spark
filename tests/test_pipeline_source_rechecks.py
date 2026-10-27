"""Source withdrawal must stop later external requests, not an in-flight one."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import storyforge


class PipelineSourceRechecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.story = self.base / "story"
        self.story.mkdir()
        (self.story / "source.md").write_text("SYNTHETIC_SOURCE_WITHDRAWAL", encoding="utf-8")
        setup = self.cli("run", "--runner", "mock", "--run-id", "setup", "--no-human-gates")
        self.assertEqual(setup.returncode, 0, setup.stderr)
        self.marker = self.base / "calls.jsonl"
        binary = self.base / "bin"
        binary.mkdir()
        executable = binary / "codex"
        executable.write_text("#!" + sys.executable + "\n" + '''
import json, os, re, sys
from pathlib import Path
prompt = sys.stdin.read()
story = Path(os.environ["SYNTHETIC_STORY"])
output = Path(sys.argv[sys.argv.index("--output-last-message") + 1])
phase = int(re.search(r"phase([0-9]+)\\.", output.name).group(1))
with Path(os.environ["SYNTHETIC_MARKER"]).open("a") as handle:
    handle.write(json.dumps({"phase": phase, "policy": (story / "story.yaml").read_text(),
                             "argv": sys.argv[1:], "live_path_in_prompt": str(story) in prompt}) + "\\n")
if os.environ.get("SYNTHETIC_REVOKE") == "1":
    (story / "story.yaml").write_text("source_policy:\\n  access: denied\\n")
if os.environ.get("SYNTHETIC_FAIL") == "1":
    sys.exit(1)
text = (Path(os.environ["SYNTHETIC_FIXTURES"]) / f"phase{phase}.bundle.txt").read_text()
output.write_text(text.replace("{{STORY_SLUG}}", story.name))
''', encoding="utf-8")
        executable.chmod(0o700)
        for name in ["openclaw", "claude"]:
            sentinel = binary / name
            sentinel.write_text("#!" + sys.executable + "\n" + '''
import json, os, sys
from pathlib import Path
with Path(os.environ["SYNTHETIC_MARKER"]).open("a") as handle:
    handle.write(json.dumps({"unexpected_provider": Path(sys.argv[0]).name}) + "\\n")
sys.exit(77)
''', encoding="utf-8")
            sentinel.chmod(0o700)
        self.env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"],
                        SYNTHETIC_STORY=str(self.story), SYNTHETIC_MARKER=str(self.marker),
                        SYNTHETIC_FIXTURES=str(ROOT / "tests/fixtures/mock-runs"))

    def cli(self, *arguments, env=None):
        return subprocess.run([sys.executable, str(ROOT / "scripts/storyforge.py"),
                               *map(str, arguments), "--story", str(self.story)],
                              text=True, capture_output=True, env=env, timeout=30)

    def calls(self):
        return [json.loads(line) for line in self.marker.read_text().splitlines()] if self.marker.exists() else []

    def revoke(self):
        (self.story / "story.yaml").write_text("source_policy:\n  access: denied\n", encoding="utf-8")

    def assert_denied(self):
        self.assertEqual(yaml.safe_load((self.story / "story.yaml").read_text())["source_policy"]["access"], "denied")

    def args(self, start, end):
        return storyforge.build_parser().parse_args([
            "run", "--story", str(self.story), "--runner", "codex", "--run-id", "recheck",
            "--from-phase", str(start), "--to-phase", str(end), "--no-human-gates"])

    def test_critic_failure_cannot_retry_writer_after_source_withdrawal(self):
        env = dict(self.env, SYNTHETIC_REVOKE="1", SYNTHETIC_FAIL="1")
        original = (self.story / "draft.md").read_bytes()
        result = self.cli("run", "--runner", "codex", "--run-id", "retry",
                          "--from-phase", 4, "--to-phase", 4, "--max-retries", 1,
                          "--no-human-gates", env=env)
        self.assertEqual(result.returncode, 30, result.stderr)
        self.assertEqual([call["phase"] for call in self.calls()], [4])
        self.assertNotIn("--source-story", self.calls()[0]["argv"])
        self.assertFalse(self.calls()[0]["live_path_in_prompt"])
        self.assertEqual((self.story / "draft.md").read_bytes(), original)
        self.assert_denied()
        manifest = json.loads((self.story / "runs/retry/run-manifest.json").read_text())
        self.assertEqual((manifest["status"], manifest["source_access"]), ("blocked", "denied"))

    def test_same_agent_invocation_cannot_fallback_after_source_withdrawal(self):
        env = dict(self.env, SYNTHETIC_REVOKE="1", SYNTHETIC_FAIL="1",
                   STORYFORGE_AGENT_PROVIDER_PRIORITY="codex,codex")
        result = self.cli("run", "--runner", "agent", "--run-id", "fallback",
                          "--from-phase", 3, "--to-phase", 3, "--max-retries", 0,
                          "--no-human-gates", env=env)
        self.assertEqual(result.returncode, 30, result.stderr)
        self.assertEqual(len(self.calls()), 1)
        self.assert_denied()

    def test_relative_story_cli_cannot_fallback_after_source_withdrawal(self):
        env = dict(self.env, SYNTHETIC_REVOKE="1", SYNTHETIC_FAIL="1",
                   STORYFORGE_AGENT_PROVIDER_PRIORITY="codex,claude")
        original = (self.story / "draft.md").read_bytes()
        result = subprocess.run([
            sys.executable, str(ROOT / "scripts/storyforge.py"),
            "run", "--story", "story", "--runner", "agent", "--run-id", "relative-fallback",
            "--from-phase", "3", "--to-phase", "3", "--max-retries", "0", "--no-human-gates"],
            cwd=self.base, text=True, capture_output=True, env=env, timeout=30)
        self.assertEqual(result.returncode, 30, result.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(calls[0]["phase"], 3)
        self.assertNotIn("--source-story", calls[0]["argv"])
        self.assertFalse(calls[0]["live_path_in_prompt"])
        self.assertEqual((self.story / "draft.md").read_bytes(), original)
        self.assert_denied()
        manifest = json.loads((self.story / "runs/relative-fallback/run-manifest.json").read_text())
        self.assertEqual((manifest["status"], manifest["source_access"]), ("blocked", "denied"))
        record = json.loads((self.story / "runs/relative-fallback/phase3.runner.log").read_text().splitlines()[-1])
        self.assertTrue(record["source_access_denied"])
        self.assertEqual(record["selected_providers"], ["codex", "claude"])

    def test_next_phase_checks_current_source_after_completed_phase(self):
        original = storyforge.run_phase
        completed = []

        def withdraw_after_phase(*args, **kwargs):
            result = original(*args, **kwargs)
            if result and args[4] == 1:
                completed.append((self.story / "dissection.md").read_bytes())
                self.revoke()
            return result

        with patch.dict(os.environ, self.env), patch.object(storyforge, "run_phase", withdraw_after_phase):
            code = storyforge.run_pipeline(self.args(1, 2))
        self.assertEqual(code, 30)
        self.assertEqual([call["phase"] for call in self.calls()], [1])
        self.assertEqual((self.story / "dissection.md").read_bytes(), completed[0])
        self.assert_denied()

    def test_withdrawal_during_prompt_preparation_prevents_dispatch(self):
        original = storyforge.render_phase_prompt

        def withdraw_during_prompt(*args, **kwargs):
            result = original(*args, **kwargs)
            self.revoke()
            return result

        with patch.dict(os.environ, self.env), patch.object(storyforge, "render_phase_prompt", withdraw_during_prompt):
            code = storyforge.run_pipeline(self.args(3, 3))
        self.assertEqual(code, 30)
        self.assertEqual(self.calls(), [])
        self.assert_denied()

    def test_last_response_after_withdrawal_cannot_publish(self):
        original = b"OWNER_REVIEWED_DRAFT\n" + (self.story / "draft.md").read_bytes()
        (self.story / "draft.md").write_bytes(original)
        env = dict(self.env, SYNTHETIC_REVOKE="1")
        result = self.cli("run", "--runner", "codex", "--run-id", "last-response",
                          "--from-phase", 3, "--to-phase", 3, "--max-retries", 0,
                          "--no-human-gates", env=env)
        self.assertEqual(result.returncode, 30, result.stderr)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual((self.story / "draft.md").read_bytes(), original)
        self.assertTrue(list(self.base.glob(".story.attempt-*/story")))
        self.assert_denied()

    def test_local_mock_manual_and_dry_run_policy_contracts_stay_allowed(self):
        self.revoke()
        for runner, dry_run in [("mock", False), ("manual-prompt-pack", False),
                                ("local-ollama", False), ("codex", True)]:
            with self.subTest(runner=runner, dry_run=dry_run):
                args = self.args(1, 1)
                args.runner = runner
                args.dry_run = dry_run
                args.run_id = runner + str(dry_run)
                with patch.object(storyforge, "run_phase", return_value=True):
                    self.assertEqual(storyforge.run_pipeline(args), 0)
        self.assertEqual(self.calls(), [])
        self.assert_denied()

    def test_agent_internal_mock_and_manual_do_not_gain_external_restriction(self):
        self.revoke()
        prompt = self.base / "prompt.md"
        prompt.write_text("SYNTHETIC_LOCAL_PROMPT")
        for provider, expected in [("mock", 0), ("manual-prompt-pack", 24)]:
            with self.subTest(provider=provider):
                output = self.base / provider
                output.mkdir()
                result = subprocess.run([
                    sys.executable, str(ROOT / "scripts/runners/agent-runner.py"),
                    "--story", str(self.story), "--phase", "1", "--prompt", str(prompt),
                    "--run-dir", str(output), "--providers", provider],
                    capture_output=True, text=True, env=self.env, timeout=30)
                self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
                self.assertEqual(json.loads(result.stdout)["provider"], provider)
        self.assertEqual(self.calls(), [])

    def test_dispatcher_checks_both_stage_and_live_and_keeps_stale_output_unpublished(self):
        prompt = self.base / "prompt.md"
        prompt.write_text("SYNTHETIC_DISPATCH_PROMPT")
        for index, (stage_policy, live_policy, standalone) in enumerate([
            ("source_policy:\n  access: denied\n", "{}", False),
            ("source_policy: []", "{}", False),
            ("{}", "source_policy:\n  access: denied\n", False),
            ("source_policy:\n  access: denied\n", "{}", True),
        ]):
            stage = self.base / f"stage-{index}"
            live = self.base / f"live-{index}"
            stage.mkdir()
            live.mkdir()
            (stage / "story.yaml").write_text(stage_policy)
            (live / "story.yaml").write_text(live_policy)
            for provider in ["codex", "openclaw", "claude"]:
                with self.subTest(index=index, provider=provider):
                    output = self.base / f"dispatch-{index}-{provider}"
                    output.mkdir()
                    stale = output / "phase1.model.out"
                    stale.write_text("STALE_SUCCESS_MUST_NOT_BE_RELABELLED")
                    command = [sys.executable, str(ROOT / "scripts/runners/agent-runner.py"),
                               "--story", str(stage), "--phase", "1", "--prompt", str(prompt),
                               "--run-dir", str(output), "--providers", provider]
                    if not standalone:
                        command += ["--source-story", str(live)]
                    result = subprocess.run(command, capture_output=True, text=True,
                                            env=self.env, timeout=30)
                    self.assertEqual(result.returncode, 30, result.stderr + result.stdout)
                    record = json.loads(result.stdout)
                    self.assertTrue(record["source_access_denied"])
                    self.assertEqual(record["status"], "failed")
                    self.assertEqual(stale.read_text(), "STALE_SUCCESS_MUST_NOT_BE_RELABELLED")
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
