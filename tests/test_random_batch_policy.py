"""Actual Bash/picker handoff uses synthetic source and forbidden-dispatch sentinels."""
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def batch_root(tmp_path):
    root = tmp_path / "cloud batch with spaces"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    for file in (ROOT / "scripts").glob("*.py"):
        (scripts / file.name).symlink_to(file)
    for name in ("batch-run.sh", "corpus-picker.py", "batch-quality-report.py"):
        target = scripts / name
        if target.is_symlink():
            target.unlink()
        shutil.copy2(ROOT / "scripts" / name, target)
    entries = []
    for slug in ("one", "two"):
        source = root / "corpus" / slug / "source.md"
        source.parent.mkdir(parents=True)
        source.write_text(f"Synthetic {slug} source only.", encoding="utf-8")
        entries.append({"slug": slug, "source_path": f"corpus/{slug}/source.md", "genre": slug})
    (root / "corpus/_index.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return root


def run_batch(root, runner=None, *, forbid_dispatch=True, dry_run=False):
    binary = root / "bin"
    binary.mkdir()
    dispatch = root / "dispatch.log"
    report = root / "report.log"
    provider = root / "provider.log"
    python = binary / "python3"
    # Importing the canonical policy helper is allowed; CLI dispatch and report
    # generation are separately observable, and forbidden for blocked batches.
    python.write_text(
        "#!/usr/bin/env bash\n"
        f"case \"$1\" in\n  */storyforge.py) printf dispatch >> {shlex.quote(str(dispatch))} ;;\n"
        f"  */batch-quality-report.py) printf report >> {shlex.quote(str(report))} ;;\nesac\n"
        + ("case \"$1\" in */storyforge.py|*/batch-quality-report.py) exit 98 ;; esac\n"
           if forbid_dispatch else "")
        + f"exec {shlex.quote(sys.executable)} \"$@\"\n",
        encoding="utf-8",
    )
    python.chmod(0o700)
    for name in ("codex", "openclaw", "claude", "ollama"):
        executable = binary / name
        executable.write_text(f"#!/bin/sh\nprintf forbidden >> {shlex.quote(str(provider))}\nexit 99\n")
        executable.chmod(0o700)
    command = ["bash", str(root / "scripts/batch-run.sh"), "--mode", "random-batch",
               "--count", "2", "--seed", "7", "--no-rubric"]
    if runner is not None:
        command += ["--runner", runner]
    if dry_run:
        command.append("--dry-run")
    result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False,
                            env={**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
                                 "PYTHONDONTWRITEBYTECODE": "1"})
    return result, dispatch, report, provider


def fixed_picker(root, stories):
    picker = root / "scripts/corpus-picker.py"
    picker.write_text("import json\nprint(json.dumps(" + repr({"stories": [str(s) for s in stories]}) + "))\n")


def story_snapshot(story):
    return {str(path.relative_to(story)): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
            for path in story.rglob("*") if path.is_file()}


@pytest.mark.parametrize("runner", ["agent", "codex", "openclaw", "claude"])
def test_random_batch_new_denied_stories_handoff_before_any_dispatch(tmp_path, runner):
    root = batch_root(tmp_path)
    result, dispatch, report, provider = run_batch(root, runner)
    assert result.returncode == 30, result.stdout + result.stderr
    stories = sorted(path for path in (root / "stories").iterdir() if not path.name.startswith("."))
    assert len(stories) == 2
    assert "等待人工批准" in result.stdout and "不要重新随机选样" in result.stdout
    commands = [shlex.split(line) for line in result.stdout.splitlines() if line.startswith("python3 ")]
    assert sorted(command[command.index("--story") + 1] for command in commands) == [str(s) for s in stories]
    for command in commands:
        assert command[command.index("--runner") + 1] == runner
        assert "--no-human-gates" not in command
    for story in stories:
        assert f"固定选中故事: {story}" in result.stdout
        assert f"待批准 (source_policy.access=denied): {story}" in result.stdout
        assert yaml.safe_load((story / "story.yaml").read_text())["source_policy"]["access"] == "denied"
        assert not (story / "runs").exists()
    assert not dispatch.exists() and not report.exists() and not provider.exists()
    assert not (root / "exports").exists()
    assert "random-batch 完成" not in result.stdout and "汇总批次报告" not in result.stdout
    history = (root / "runs/picker-history.jsonl").read_text().splitlines()
    assert len(history) == 1  # One selection, retained for a fixed-path human handoff.


def test_random_batch_late_denied_stops_entire_batch_preserving_legacy_and_approved(tmp_path):
    root = batch_root(tmp_path)
    stories = []
    for name, policy in (("approved", "trusted_runners_allowed"), ("legacy", None), ("denied", "denied")):
        story = root / "stories" / name
        story.mkdir(parents=True)
        (story / "source.md").write_text("Synthetic existing source.")
        if policy is not None:
            (story / "story.yaml").write_text(f"source_policy:\n  access: {policy}\n")
        stories.append(story)
    before = [story_snapshot(story) for story in stories]
    fixed_picker(root, stories)
    result, dispatch, report, provider = run_batch(root, "agent")
    assert result.returncode == 30, result.stdout + result.stderr
    assert not dispatch.exists() and not report.exists() and not provider.exists()
    pending = [line for line in result.stdout.splitlines() if line.startswith("待批准 ")]
    assert pending == [f"待批准 (source_policy.access=denied): {stories[-1]}"]
    for story, snapshot in zip(stories, before):
        assert f"固定选中故事: {story}" in result.stdout
        assert story_snapshot(story) == snapshot
        assert not (story / "runs").exists()


def test_random_batch_preserves_existing_approved_and_legacy_preflight_access(tmp_path):
    root = batch_root(tmp_path)
    stories = []
    for name in ("approved", "legacy"):
        story = root / "stories" / name
        story.mkdir(parents=True)
        (story / "source.md").write_text("Synthetic existing source.")
        if name == "approved":
            (story / "story.yaml").write_text("source_policy:\n  access: trusted_runners_allowed\n")
        stories.append(story)
    before = [story_snapshot(story) for story in stories]
    fixed_picker(root, stories)
    # Exit98 marks the test's forbidden CLI/report boundary, not a real runner.
    result, dispatch, report, provider = run_batch(root, "agent")
    assert result.returncode == 98, result.stdout + result.stderr
    assert dispatch.read_text() == "dispatchdispatch" and report.read_text() == "report"
    assert not provider.exists() and "等待人工批准" not in result.stdout
    assert [story_snapshot(story) for story in stories] == before


@pytest.mark.parametrize("bad_policy", ["invalid-yaml", "unreadable-manifest"])
def test_random_batch_policy_read_failure_stops_before_dispatch(tmp_path, bad_policy):
    root = batch_root(tmp_path)
    story = root / "stories/bad-policy"
    story.mkdir(parents=True)
    if bad_policy == "invalid-yaml":
        (story / "story.yaml").write_text("source_policy: [invalid")
    else:
        (story / "story.yaml").mkdir()  # Deterministic read failure, even under root.
    fixed_picker(root, [story])
    result, dispatch, report, provider = run_batch(root, "codex")
    assert result.returncode != 0, result.stdout + result.stderr
    assert not dispatch.exists() and not report.exists() and not provider.exists()
    assert not (root / "exports").exists()
    assert not (story / "runs").exists()
    assert "random-batch 完成" not in result.stdout


@pytest.mark.parametrize("runner", [None, "mock"])
def test_random_batch_retains_offline_default_manual_and_mock_paths(tmp_path, runner):
    root = batch_root(tmp_path)
    result, dispatch, report, provider = run_batch(root, runner, forbid_dispatch=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert dispatch.read_text() == "dispatchdispatch"
    assert report.read_text() == "report"
    assert not provider.exists()
    stories = [path for path in (root / "stories").iterdir() if not path.name.startswith(".")]
    assert len(stories) == 2
    assert all(list((story / "runs").glob("*/phase1.prompt.md")) for story in stories)
    assert list((root / "exports").glob("auto-batch-*/batch-summary.json"))
    assert "等待人工批准" not in result.stdout


def test_random_batch_dry_run_does_not_select_or_dispatch(tmp_path):
    root = batch_root(tmp_path)
    result, dispatch, report, provider = run_batch(root, "agent", dry_run=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (root / "stories").exists() and not (root / "runs").exists()
    assert not dispatch.exists() and not report.exists() and not provider.exists()
