"""Approval content binding and fail-closed restart regressions."""
import argparse
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import approval_snapshots as snapshots  # noqa: E402
import storyforge  # noqa: E402
from storyforge_lib import write_json  # noqa: E402


def setup(tmp_path):
    story = tmp_path / "story"
    story.mkdir()
    for name in ["source.md", "blueprint.md", "adaptation.md"]:
        (story / name).write_text(name)
    (story / "story.yaml").write_text("slug: example\nautomation:\n  human_gates:\n    phase2_blueprint_review: approved\n")
    run = story / "runs" / "r"
    run.mkdir(parents=True)
    args = storyforge.build_parser().parse_args(["run", "--story", str(story), "--run-id", "r", "--runner", "openclaw"])
    return story, run, args


def approve(story, run, args, monkeypatch):
    write_json(run / "blueprint-pending.json", {"configuration": snapshots.configuration(args)})
    monkeypatch.setattr(storyforge, "validate_phase", lambda *a, **kw: subprocess.CompletedProcess([], 0))
    approval = argparse.Namespace(story=str(story), run_id="r", gate="phase2_blueprint_review")
    assert storyforge.approve_gate(approval) == 0


def test_legacy_approved_does_not_authorize_execution(tmp_path):
    story, run, args = setup(tmp_path)
    with pytest.raises(ValueError, match="missing"):
        snapshots.require_approval(story, run, ROOT, args)
    args.from_phase = 3
    args.to_phase = 3
    assert storyforge.run_pipeline(args) == 24
    assert not (run / "phase3.prompt.md").exists()


@pytest.mark.parametrize("change", ["candidate", "input", "model", "runner", "environment", "rules", "prompt"])
def test_each_material_change_invalidates_approval(tmp_path, monkeypatch, change):
    story, run, args = setup(tmp_path)
    approve(story, run, args, monkeypatch)
    snapshots.require_approval(story, run, ROOT, args)
    if change == "candidate":
        (story / "blueprint.md").write_text("edited blueprint")
    elif change == "input":
        (story / "dissection.md").write_text("new upstream input")
    elif change in {"model", "runner"}:
        setattr(args, change, "changed")
    elif change == "environment":
        monkeypatch.setenv("STORYFORGE_CODEX_REASONING_EFFORT", "high")
    else:
        original = snapshots.dependencies
        monkeypatch.setattr(snapshots, "dependencies", lambda root: original(root) | {change: "changed"})
    with pytest.raises(ValueError, match="stale"):
        snapshots.require_approval(story, run, ROOT, args)


def test_logs_and_operational_metadata_do_not_invalidate(tmp_path, monkeypatch):
    story, run, args = setup(tmp_path)
    approve(story, run, args, monkeypatch)
    (run / "noise.log").write_text("progress")
    (story / "notes.log").write_text("unrelated")
    storyforge.update_story_automation(story, {"current_phase": 4, "retry_count": 9})
    monkeypatch.setenv("STORYFORGE_HEARTBEAT_SECONDS", "1")
    snapshots.require_approval(story, run, ROOT, args)


def test_explicit_reapproval_binds_new_candidate_and_model(tmp_path, monkeypatch):
    story, run, args = setup(tmp_path)
    approve(story, run, args, monkeypatch)
    (story / "blueprint.md").write_text("reviewed revision")
    monkeypatch.setenv("STORYFORGE_CODEX_REASONING_EFFORT", "high")
    approval = argparse.Namespace(story=str(story), run_id="r", gate="phase2_blueprint_review", model="new", runner="openclaw")
    assert storyforge.approve_gate(approval) == 0
    args.model = "new"
    snapshots.require_approval(story, run, ROOT, args)


def test_approval_needs_pending_record_and_valid_artifacts(tmp_path, monkeypatch):
    story, run, args = setup(tmp_path)
    approval = argparse.Namespace(story=str(story), run_id="r", gate="phase2_blueprint_review")
    assert storyforge.approve_gate(approval) == 23
    write_json(run / "blueprint-pending.json", {"configuration": snapshots.configuration(args)})
    monkeypatch.setattr(storyforge, "validate_phase", lambda *a, **kw: subprocess.CompletedProcess([], 1))
    assert storyforge.approve_gate(approval) == 23
    assert not (run / "blueprint-approval.json").exists()


def test_prompt_story_yaml_excludes_only_operational_metadata(tmp_path):
    story, run, args = setup(tmp_path)
    first = snapshots.snapshot(story, 3, ROOT, snapshots.configuration(args))
    storyforge.update_story_automation(story, {"runner": "something"})
    assert snapshots.snapshot(story, 3, ROOT, snapshots.configuration(args)) == first
    (story / "story.yaml").write_text("source_policy:\n  access: denied\n")
    assert snapshots.snapshot(story, 3, ROOT, snapshots.configuration(args)) != first


def test_completed_resume_requires_identical_input_output_and_validation(tmp_path, monkeypatch):
    from test_stage_safety import successful_phase_harness
    args, story, run = successful_phase_harness(tmp_path, monkeypatch)
    args.resume = True
    assert storyforge.run_phase(args, story, run, run / "summary.md", 3, 0)
    def forbidden_runner(*a, **kw):
        pytest.fail("matching completed stage should be reused")
    monkeypatch.setattr(storyforge, "run_command_with_heartbeat", forbidden_runner)
    assert storyforge.run_phase(args, story, run, run / "summary.md", 3, 0)
    assert "| 3 | reused |" in (run / "summary.md").read_text()
    (story / "blueprint.md").write_text("changed")
    with pytest.raises(pytest.fail.Exception, match="should be reused"):
        storyforge.run_phase(args, story, run, run / "summary.md", 3, 0)


@pytest.mark.parametrize("cause", ["output", "validation"])
def test_resume_does_not_trust_completion_marker(tmp_path, monkeypatch, cause):
    from test_stage_safety import successful_phase_harness
    args, story, run = successful_phase_harness(tmp_path, monkeypatch)
    args.resume = True
    assert storyforge.run_phase(args, story, run, run / "summary.md", 3, 0)
    if cause == "output":
        (story / "draft.md").write_text("tampered")
    else:
        monkeypatch.setattr(storyforge, "validate_phase", lambda *a, **kw: subprocess.CompletedProcess([], 1))
    def regenerated(*a, **kw):
        raise RuntimeError("regeneration required")
    monkeypatch.setattr(storyforge, "run_command_with_heartbeat", regenerated)
    with pytest.raises(RuntimeError, match="regeneration required"):
        storyforge.run_phase(args, story, run, run / "summary.md", 3, 0)


def test_stale_manual_bundle_is_not_reused(tmp_path, monkeypatch):
    from test_stage_safety import block, phase_harness
    def runner(cmd, *a, **kw):
        return subprocess.run(cmd, cwd=kw["cwd"], text=True, capture_output=True), {}
    args, story, run = phase_harness(tmp_path, monkeypatch, runner)
    args.runner = "manual-prompt-pack"
    assert not storyforge.run_phase(args, story, run, run / "summary.md", 3, 0)
    (run / "phase3.model.out").write_text(block({"draft.md": "STALE"}))
    (story / "blueprint.md").write_text("new blueprint")
    assert not storyforge.run_phase(args, story, run, run / "summary.md", 3, 0)
    assert (story / "draft.md").read_text() == "APPROVED"
    assert not storyforge.run_phase(args, story, run, run / "summary.md", 3, 0)
    assert (story / "draft.md").read_text() == "APPROVED"
    assert list(run.glob("phase3.model.out.stale-*"))


def test_split_scene_generation_checks_approved_model(tmp_path, monkeypatch):
    from generate_scene_batches import check_blueprint_approval
    story, run, args = setup(tmp_path)
    args.runner = "codex"
    args.model = "reviewed-model"
    approve(story, run, args, monkeypatch)
    batch = argparse.Namespace(no_human_gates=False, approval_run_id="r", model=args.model, effort="medium")
    check_blueprint_approval(story, batch)
    batch.model = "different"
    with pytest.raises(ValueError, match="stale"):
        check_blueprint_approval(story, batch)


@pytest.mark.parametrize("mode,phase", [("v4", 2), ("production", 4), ("production_v6", 5), ("ultra_short", 4)])
def test_review_binds_actual_blueprint_role(mode, phase, tmp_path):
    story, run, args = setup(tmp_path)
    args.mode = mode
    before = snapshots.approval_snapshot(story, ROOT, snapshots.configuration(args))
    assert before["data"]["phase"] == phase
    if mode != "v4":
        (story / "scene-cards").mkdir()
        (story / "scene-cards/scene-01.json").write_text('{"scene_id":"scene-01"}')
        after = snapshots.approval_snapshot(story, ROOT, snapshots.configuration(args))
        assert before != after
        assert "story/scene-cards/scene-01.json" in after["data"]["candidate"]


def test_cli_explicit_approval_and_stale_rejection(tmp_path):
    from test_storyforge_runner import run_storyforge
    story = tmp_path / "cli-story"
    story.mkdir()
    (story / "source.md").write_text("合成测试原文")
    result = run_storyforge("run", "--story", story, "--run-id", "r", "--runner", "mock", "--to-phase", "2")
    assert result.returncode == 0, result.stderr
    result = run_storyforge("approve-gate", "--story", story, "--run-id", "r",
                           "--gate", "phase2_blueprint_review", "--runner", "manual-prompt-pack")
    assert result.returncode == 0, result.stderr
    result = run_storyforge("run", "--story", story, "--run-id", "r", "--runner", "manual-prompt-pack",
                           "--from-phase", "3", "--to-phase", "3")
    assert result.returncode == 23  # runner waits for manual response, not blocked by gate
    assert (story / "runs/r/phase3.prompt.md").exists()
    (story / "blueprint.md").write_text("changed after review")
    result = run_storyforge("run", "--story", story, "--run-id", "r", "--runner", "manual-prompt-pack",
                           "--from-phase", "3", "--to-phase", "3")
    assert result.returncode == 24
    assert "stale" in result.stderr


def test_dependency_logs_do_not_change_identity(tmp_path):
    (tmp_path / "context").mkdir()
    (tmp_path / "context/rules.json").write_text("{}")
    before = snapshots.dependencies(tmp_path)
    (tmp_path / "context/progress.log").write_text("new log")
    assert snapshots.dependencies(tmp_path) == before
    (tmp_path / "context/rules.json").write_text('{"version":2}')
    assert snapshots.dependencies(tmp_path) != before
