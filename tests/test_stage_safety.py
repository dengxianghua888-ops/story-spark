"""Source authorization, V6 role gates and failure-atomic publication regressions."""
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
# These imports intentionally follow the repository script-path setup.

import storyforge  # noqa: E402
import storyforge_lib as lib  # noqa: E402
from production_normalize import normalize_story  # noqa: E402
from production_quality import machine_evaluate  # noqa: E402
from test_production_quality import add_common_production_artifacts, make_story_text, write_bundle  # noqa: E402
from test_storyforge_runner import run_storyforge, write  # noqa: E402


def block(files):
    return "".join(f"<<<FILE: {p}>>>\n{v}\n<<<END FILE>>>\n" for p, v in files.items())


def tree_bytes(story):
    return {str(p.relative_to(story)): p.read_bytes() for p in story.rglob("*")
            if p.is_file() and "runs" not in p.relative_to(story).parts}


def test_gate_approval_preserves_source_policy_and_automation(tmp_path, monkeypatch):
    story = tmp_path / "story"
    write(story / "source.md", "private source")
    original = {"slug": "story", "source_policy": {"access": "denied", "notes": "owner only"},
                "automation": {"runner": "agent", "current_phase": 3, "custom": "keep",
                               "human_gates": {"another_gate": "pending"}}}
    write(story / "story.yaml", yaml.safe_dump(original))
    import argparse
    import subprocess
    from approval_snapshots import configuration
    write(story / "blueprint.md", "reviewed blueprint")
    write(story / "adaptation.md", "reviewed adaptation")
    run_args = storyforge.build_parser().parse_args(["run", "--story", str(story)])
    lib.write_json(story / "runs/r/blueprint-pending.json", {"configuration": configuration(run_args)})
    monkeypatch.setattr(storyforge, "validate_phase", lambda *a, **kw: subprocess.CompletedProcess([], 0))
    assert storyforge.approve_gate(argparse.Namespace(story=str(story), run_id="r", gate="phase2_blueprint_review")) == 0
    after = yaml.safe_load((story / "story.yaml").read_text())
    assert after["source_policy"] == original["source_policy"]
    assert after["automation"] == original["automation"] | {"human_gates": {
        "another_gate": "pending", "phase2_blueprint_review": "approved"}}
    result = run_storyforge("run", "--story", story, "--runner", "agent")
    assert result.returncode == 30


@pytest.mark.parametrize("mode,critic,final", [("v4",4,5), ("production",6,7),
                                              ("ultra_short",6,7), ("production_v6",7,8)])
def test_role_coordinates(mode, critic, final):
    assert lib.phase_for_role(mode, "critic") == critic
    assert lib.phase_for_role(mode, "final") == final


def test_v6_rejects_unlisted_source_before_writes(tmp_path):
    story = tmp_path / "story"
    write(story / "source.md", "original")
    before = tree_bytes(story)
    with pytest.raises(ValueError, match="not allowed"):
        lib.apply_artifact_bundle(story, 1, block({"market-brief.json": "{}", "source.md": "bad"}),
                                  story / "runs" / "r", mode="production_v6")
    assert tree_bytes(story) == before


def test_second_candidate_write_failure_retains_live_bytes(tmp_path, monkeypatch):
    story = tmp_path / "story"
    write(story / "draft.md", "old draft")
    write(story / "draft-scenes/old.md", "old scene")
    before = tree_bytes(story)
    original = lib.write_text
    def fail_second(path, text):
        if path.name == "draft.md" and ".attempt-" in str(path):
            raise OSError("injected write failure")
        original(path, text)
    monkeypatch.setattr(lib, "write_text", fail_second)
    with pytest.raises(OSError, match="injected"):
        lib.apply_artifact_bundle(story, 6, block({"draft-scenes/new.md": "new", "draft.md": "new"}),
                                  story / "runs" / "r", mode="production_v6")
    assert tree_bytes(story) == before


def test_stale_outputs_replaced_and_attempt_backups_unique(tmp_path):
    story = tmp_path / "story"
    write(story / "draft.md", "first")
    write(story / "draft-scenes/old.md", "old")
    for text in ["second", "third"]:
        lib.apply_artifact_bundle(story, 6, block({"draft-scenes/new.md": text, "draft.md": text}),
                                  story / "runs/r", mode="production_v6")
    assert not (story / "draft-scenes/old.md").exists()
    backups = list(tmp_path.glob(".story.attempt-*/story/draft.md"))
    assert sorted(p.read_text().strip() for p in backups) == ["first", "second"]
    assert (story / "draft.md").read_text().strip() == "third"


def test_unsupported_atomic_exchange_fails_without_publication(tmp_path, monkeypatch):
    story = tmp_path / "story"
    write(story / "draft.md", "old")
    with lib.StagedStory(story, story / "runs/r", 6) as stage:
        write(stage.path / "draft.md", "candidate")
        monkeypatch.setattr(lib.sys, "platform", "unsupported")
        with pytest.raises(OSError, match="Atomic story exchange"):
            stage.publish()
    assert (story / "draft.md").read_text() == "old"


def test_v6_critic_reads_current_draft_and_does_not_finalize(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text())
    write(story / "story.yaml", "slug: story\nstatus: phase6\n")
    write(story / "final.md", "stale final")
    metrics = machine_evaluate(story, 7, "production_v6")
    assert metrics["text_path"].endswith("draft.md")
    assert metrics["chapters"]["count"] == 0
    normalize_story(story, 7, "production_v6")
    assert yaml.safe_load((story / "story.yaml").read_text())["status"] == "phase6"
    assert (story / "final.md").read_text() == "stale final"


def v6_fixtures(tmp_path):
    template = tmp_path / "template"
    add_common_production_artifacts(template, make_story_text())
    write(template / "analysis/chapter-soul-map.json", "{}")
    write(template / "hook/opening-hook.md", "导语：证据忽然被送到门口。")
    write(template / "hook/hook-meta.json", "{}")
    bible = json.loads((template / "beat-bible.json").read_text())
    bible["chapters"] = [{"chapter_id": "c1", "scenes": ["scene-01"], "target_char_count": [10000, 18000]}]
    write(template / "beat-bible.json", json.dumps(bible))
    market = json.loads((template / "market-brief.json").read_text())
    market["pipeline_mode"] = "production_v6"
    write(template / "market-brief.json", json.dumps(market))
    write(template / "feedback-learning.json", json.dumps({"story_slug":"story", "pipeline_mode":"production_v6",
          "failure_types":[], "successful_hooks":[], "manual_revision_delta":[],
          "quality_scores": {k:8 for k in ["platform","emotion","style","logic"]}}))
    fixtures = tmp_path / "fixtures"
    for phase in range(1, 10):
        files = {}
        for pattern in lib.load_phase_bundle(phase, mode="production_v6").required_outputs:
            for path in template.glob(pattern):
                files[str(path.relative_to(template))] = path.read_text()
        write_bundle(fixtures / f"phase{phase}.bundle.txt", files)
    return fixtures


def test_v6_full_mock_from_empty_final_and_current_final_rubric(tmp_path):
    fixtures = v6_fixtures(tmp_path)
    story = tmp_path / "story"
    write(story / "source.md", "合成测试原文")
    result = run_storyforge("run", "--story", story, "--runner", "mock", "--mode", "production_v6",
                           "--run-id", "full", "--max-retries", 0, "--no-human-gates",
                           env={"STORYFORGE_MOCK_FIXTURE_DIR": str(fixtures)})
    assert result.returncode == 0, result.stderr + result.stdout + (story / "runs/full/execution-summary.md").read_text()
    assert (story / "runs/full/phase8.rubric.log").exists()
    assert not (story / "runs/full/phase7.rubric.log").exists()
    assert yaml.safe_load((story / "story.yaml").read_text())["status"] == "test_fixture"
    assert json.loads((story / "runs/full/run-manifest.json").read_text())["last_completed_phase"] == 9


def test_v6_critic_fail_cannot_publish_or_reach_final(tmp_path):
    fixtures = v6_fixtures(tmp_path)
    files = lib.parse_artifact_bundle((fixtures / "phase7.bundle.txt").read_text())
    report = json.loads(files["quality-report.json"])
    report["gate_status"] = "fail"
    files["quality-report.json"] = json.dumps(report)
    write_bundle(fixtures / "phase7.bundle.txt", files)
    story = tmp_path / "story"
    write(story / "source.md", "合成测试原文")
    result = run_storyforge("run", "--story", story, "--runner", "mock", "--mode", "production_v6",
                           "--run-id", "fail", "--max-retries", 0, "--no-human-gates",
                           env={"STORYFORGE_MOCK_FIXTURE_DIR": str(fixtures)})
    assert result.returncode == 23
    assert "quality gate failed" in (story / "runs/fail/phase7.validator.log").read_text()
    assert not (story / "quality-report.json").exists()
    assert not (story / "final.md").exists()
    assert not (story / "runs/fail/phase8.runner.log").exists()


def test_model_story_metadata_cannot_change_source_permission(tmp_path):
    story = tmp_path / "story"
    write(story / "story.yaml", "source_policy:\n  access: 'denied'\n  notes: retained\n")
    assert storyforge.story_source_access(story) == "denied"
    bundle = (ROOT / "tests/fixtures/mock-runs/phase5.bundle.txt").read_text().replace("{{STORY_SLUG}}", "story")
    lib.apply_artifact_bundle(story, 5, bundle, story / "runs/r")
    assert yaml.safe_load((story / "story.yaml").read_text())["source_policy"] == {
        "access": "denied", "notes": "retained"}


def test_v6_bad_replacement_final_is_checked_and_not_published(tmp_path):
    fixtures = v6_fixtures(tmp_path)
    story = tmp_path / "story"
    write(story / "source.md", "合成测试原文")
    args = ["run", "--story", story, "--runner", "mock", "--mode", "production_v6",
            "--max-retries", 0, "--no-human-gates"]
    env = {"STORYFORGE_MOCK_FIXTURE_DIR": str(fixtures)}
    assert run_storyforge(*args, "--run-id", "first", env=env).returncode == 0
    before = tree_bytes(story)
    files = lib.parse_artifact_bundle((fixtures / "phase8.bundle.txt").read_text())
    files["final.md"] = files["final.md"].replace("闻夏", "张三")
    write_bundle(fixtures / "phase8.bundle.txt", files)
    result = run_storyforge(*args, "--run-id", "replacement", "--from-phase", 8,
                           "--rubric-threshold", 10, env=env)
    assert result.returncode == 23
    rubric = json.loads((story / "runs/replacement/phase8.rubric.log").read_text())
    assert rubric["status"] == "fail"
    assert tree_bytes(story) == before


def test_changes_during_validation_are_not_overwritten(tmp_path):
    story = tmp_path / "story"
    write(story / "draft.md", "original")
    with lib.StagedStory(story, story / "runs/r", 6) as stage:
        write(stage.path / "draft.md", "candidate")
        write(story / "draft.md", "external editor change")
        with pytest.raises(OSError, match="changed during validation"):
            stage.publish()
    assert (story / "draft.md").read_text() == "external editor change"


def test_concurrent_pipeline_writer_is_rejected(tmp_path):
    story = tmp_path / "story"
    write(story / "source.md", "source")
    with lib.story_write_lock(story):
        result = run_storyforge("run", "--story", story, "--runner", "mock")
    assert result.returncode == 23
    assert "active writer" in result.stderr
    assert not (story / "final.md").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Darwin dispatch mock uses Linux native exchange; native macOS is covered end-to-end")
@pytest.mark.parametrize("fail", [False, True])
def test_macos_exchange_argument_mapping_and_errno(tmp_path, monkeypatch, fail):
    # Exercise Darwin dispatch in Linux without claiming a macOS filesystem test.
    import ctypes
    import errno
    import os
    import types

    story = tmp_path / "story"
    write(story / "draft.md", "old")
    native = ctypes.CDLL(None, use_errno=True).renameat2
    native.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    native.restype = ctypes.c_int
    calls = []
    def renamex_np(live, candidate, flags):
        calls.append((live, candidate, flags))
        if fail:
            ctypes.set_errno(errno.ENOTSUP)
            return -1
        return native(-100, live, -100, candidate, flags)
    with lib.StagedStory(story, story / "runs/r", 6) as stage:
        write(stage.path / "draft.md", "new")
        monkeypatch.setattr(lib.sys, "platform", "darwin")
        monkeypatch.setattr(lib.ctypes, "CDLL", lambda *a, **k: types.SimpleNamespace(renamex_np=renamex_np))
        if fail:
            with pytest.raises(OSError) as error:
                stage.publish()
            assert error.value.errno == errno.ENOTSUP
        else:
            stage.publish()
        assert calls == [(os.fsencode(story), os.fsencode(stage.path), 2)]
    assert (story / "draft.md").read_text() == ("old" if fail else "new")


@pytest.mark.parametrize("publish", [False, True])
def test_process_exit_around_exchange_retains_recoverable_trees(tmp_path, publish):
    import subprocess
    story = tmp_path / "story"
    write(story / "draft.md", "old")
    code = '''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from storyforge_lib import StagedStory, story_write_lock
story = Path(sys.argv[2])
with story_write_lock(story), StagedStory(story, story / "runs/r", 6) as stage:
    (stage.path / "draft.md").write_text("new")
    if sys.argv[3] == "True":
        stage.publish()
    os._exit(73)
'''
    result = subprocess.run([sys.executable, "-c", code, str(ROOT / "scripts"), str(story), str(publish)], check=False)
    assert result.returncode == 73
    retained = next(tmp_path.glob(".story.attempt-*/story"))
    assert (story / "draft.md").read_text() == ("new" if publish else "old")
    assert (retained / "draft.md").read_text() == ("old" if publish else "new")
    if publish:
        record = json.loads((retained.parent / "attempt.json").read_text())
        assert lib.story_fingerprint(story) == record["candidate_fingerprint"]
        assert lib.story_fingerprint(retained) == record["original_fingerprint"]
    with lib.story_write_lock(story):
        pass  # Process death must not strand ownership.


def test_failed_critic_feedback_reaches_next_scene_prompt(tmp_path):
    fixtures = v6_fixtures(tmp_path)
    files = lib.parse_artifact_bundle((fixtures / "phase7.bundle.txt").read_text())
    report = json.loads(files["quality-report.json"])
    report["gate_status"] = "fail"
    report["evidence"] = ["RETRY_MARKER: clarify the ledger before the reversal"]
    files["quality-report.json"] = json.dumps(report)
    write_bundle(fixtures / "phase7.bundle.txt", files)
    story = tmp_path / "story"
    write(story / "source.md", "合成测试原文")
    result = run_storyforge("run", "--story", story, "--runner", "mock", "--mode", "production_v6",
                           "--run-id", "retry", "--max-retries", 1, "--no-human-gates",
                           env={"STORYFORGE_MOCK_FIXTURE_DIR": str(fixtures)})
    assert result.returncode == 23
    prompt = (story / "runs/retry/phase6.prompt.md").read_text()
    assert "Rejected attempt feedback" in prompt
    assert "RETRY_MARKER" in prompt
    assert "quality gate failed" in prompt
    assert not (story / "quality-report.json").exists()


def test_automation_write_failure_preserves_denied_yaml(tmp_path, monkeypatch):
    story = tmp_path / "story"
    original = "source_policy:\n  access: denied\nautomation:\n  runner: agent\n"
    write(story / "story.yaml", original)
    def fail_replace(*args):
        raise OSError("injected metadata replacement failure")
    monkeypatch.setattr(lib.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        storyforge.update_story_automation(story, {"phase2_blueprint_review": "approved"})
    assert (story / "story.yaml").read_text() == original
    assert storyforge.story_source_access(story) == "denied"


def test_approval_does_not_race_pipeline_lock(tmp_path):
    story = tmp_path / "story"
    write(story / "story.yaml", "source_policy:\n  access: denied\n")
    with lib.story_write_lock(story):
        result = run_storyforge("approve-gate", "--story", story, "--gate", "phase2_blueprint_review")
    assert result.returncode == 23
    assert "active writer" in result.stderr
    assert "automation" not in (story / "story.yaml").read_text()


def phase_harness(tmp_path, monkeypatch, runner):
    from types import SimpleNamespace
    story = tmp_path / "story"
    run = story / "runs/r"
    run.mkdir(parents=True)
    write(story / "draft.md", "APPROVED")
    args = SimpleNamespace(mode="v4", dry_run=False, runner="mock", model="",
                           heartbeat_seconds=0, run_id="r", no_human_gates=True)
    monkeypatch.setattr(storyforge, "render_phase_prompt", lambda target, *a: (f"Story: {target}", {}))
    monkeypatch.setattr(storyforge, "load_phase_bundle", lambda *a: SimpleNamespace(role="scene"))
    monkeypatch.setattr(storyforge, "run_command_with_heartbeat", runner)
    return args, story, run


@pytest.mark.parametrize("runner_success", [False, True])
def test_runner_direct_writes_never_touch_live_or_publish(tmp_path, monkeypatch, runner_success):
    import subprocess
    seen = {}
    def runner(cmd, *a, **kw):
        target = Path(cmd[cmd.index("--story") + 1])
        prompt = Path(cmd[cmd.index("--prompt") + 1])
        output = Path(cmd[cmd.index("--run-dir") + 1]) / "phase3.model.out"
        seen.update(target=target, cwd=kw["cwd"], runner_dir=output.parent, prompt=prompt.read_text())
        write(target / "draft.md", "RUNNER_BAD")
        write(output, "bad bundle")
        return subprocess.CompletedProcess(cmd, 0 if runner_success else 1,
            json.dumps({"status": "success" if runner_success else "failed", "output_bundle": str(output)}), ""), {}
    args, story, run = phase_harness(tmp_path, monkeypatch, runner)
    before = tree_bytes(story)
    assert not storyforge.run_phase(args, story, run, run / "summary.md", 3, 0)
    assert tree_bytes(story) == before
    assert seen["target"] != story and seen["cwd"] == seen["runner_dir"]
    assert not seen["cwd"].is_relative_to(story.parent)
    assert str(story) not in seen["prompt"]
    assert (seen["target"] / "draft.md").read_text() == "RUNNER_BAD"


def successful_phase_harness(tmp_path, monkeypatch):
    import subprocess
    def runner(cmd, *a, **kw):
        output = Path(cmd[cmd.index("--run-dir") + 1]) / "phase3.model.out"
        write(output, block({"draft.md": "NEW"}))
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"status": "success", "output_bundle": str(output)}), ""), {}
    args, story, run = phase_harness(tmp_path, monkeypatch, runner)
    def apply(target, *a, **kw):
        write(target / "draft.md", "NEW")
        return {"written": ["draft.md"]}
    monkeypatch.setattr(storyforge, "apply_artifact_bundle", apply)
    monkeypatch.setattr(storyforge, "validate_phase", lambda *a, **kw: subprocess.CompletedProcess([], 0, "", ""))
    return args, story, run


def test_metadata_failure_before_commit_preserves_live(tmp_path, monkeypatch):
    args, story, run = successful_phase_harness(tmp_path, monkeypatch)
    before = tree_bytes(story)
    def fail(*a, **kw):
        raise OSError("metadata disk full")
    monkeypatch.setattr(storyforge, "update_story_automation", fail)
    with pytest.raises(OSError, match="metadata disk full"):
        storyforge.run_phase(args, story, run, run / "summary.md", 3, 0)
    assert tree_bytes(story) == before


@pytest.mark.parametrize("failing_audit", ["append_summary", "update_manifest"])
def test_postcommit_audit_failure_does_not_report_phase_failure(tmp_path, monkeypatch, failing_audit):
    args, story, run = successful_phase_harness(tmp_path, monkeypatch)
    original = getattr(storyforge, failing_audit)
    def fail_after_commit(*a, **kw):
        if (story / "draft.md").read_text() == "NEW":
            raise OSError("audit disk full")
        return original(*a, **kw)
    monkeypatch.setattr(storyforge, failing_audit, fail_after_commit)
    assert storyforge.run_phase(args, story, run, run / "summary.md", 3, 0)
    assert (story / "draft.md").read_text() == "NEW"
    assert yaml.safe_load((story / "story.yaml").read_text())["automation"]["current_phase"] == 3


def test_atomic_write_preserves_existing_modes_and_new_umask(tmp_path):
    import os
    path = tmp_path / "artifact.md"
    path.write_text("old")
    path.chmod(0o640)
    lib.write_text(path, "new")
    assert path.stat().st_mode & 0o777 == 0o640
    previous = os.umask(0o027)
    try:
        lib.write_text(tmp_path / "new.md", "new")
    finally:
        os.umask(previous)
    assert (tmp_path / "new.md").stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize("phase", [1, 2])
def test_v4_early_phase_repair_has_no_missing_role(tmp_path, phase):
    from auto_repair import run_repair_pass
    assert run_repair_pass(tmp_path, phase, "v4")["results"] == []


def test_retry_omits_unchanged_approved_feedback(tmp_path):
    story = tmp_path / "story"
    run = story / "runs/r"
    write(story / "review.md", "OLD_APPROVED_REVIEW")
    write(story / "quality-report.json", '{"approved": true}')
    with lib.StagedStory(story, run, 7) as staged:
        write(staged.path / "diff.md", "NEW_FAILED_DIFF")
    prompt, manifest = lib.retry_feedback_prompt(story, run)
    assert "OLD_APPROVED_REVIEW" not in prompt
    assert '"approved": true' not in prompt
    assert "NEW_FAILED_DIFF" in prompt
    assert manifest["included"] == ["diff.md"]


def test_provider_readonly_arguments_and_openclaw_compatibility(tmp_path, monkeypatch):
    import importlib.util
    import subprocess
    from types import SimpleNamespace
    spec = importlib.util.spec_from_file_location("agent_runner", ROOT / "scripts/runners/agent-runner.py")
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    monkeypatch.setattr(agent.shutil, "which", lambda name: "/fake/" + name)
    calls = []
    def fake(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, "bundle", "")
    monkeypatch.setattr(agent, "run", fake)
    args = SimpleNamespace(story=str(tmp_path), run_dir=str(tmp_path), phase=1, model="")
    agent.run_codex(args, "prompt", tmp_path / "bundle")
    cmd, kw = calls[-1]
    assert "--ignore-user-config" in cmd
    assert "--full-auto" not in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert cmd[cmd.index("--cd") + 1] == str(tmp_path)
    assert kw["cwd"] == tmp_path
    agent.run_claude(args, "prompt", tmp_path / "bundle")
    cmd, kw = calls[-1]
    assert "--bare" in cmd and cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--disallowedTools") + 1] == "mcp__*"
    count = len(calls)
    ok, data, _ = agent.run_openclaw(args, "prompt", tmp_path / "bundle")
    assert ok and data["status"] == "success"
    assert len(calls) == count + 1
    cmd, kw = calls[-1]
    assert cmd[:3] == ["openclaw", "agent", "--local"]
    assert kw["cwd"] == tmp_path


def test_retry_diagnostics_are_attempt_scoped(tmp_path):
    story = tmp_path / "story"
    run = story / "runs/r"
    write(story / "draft.md", "approved")
    write(run / "phase7.validator.log", "OLD_VALIDATOR")
    with lib.StagedStory(story, run, 7):
        write(run / "phase7.parse-report.json", "CURRENT_PARSE_FAILURE")
    write(run / "phase7.parse-report.json", "LATER_DIFFERENT_FAILURE")
    prompt, _ = lib.retry_feedback_prompt(story, run)
    assert "CURRENT_PARSE_FAILURE" in prompt
    assert "OLD_VALIDATOR" not in prompt
    assert "LATER_DIFFERENT_FAILURE" not in prompt


def test_dry_run_does_not_stage_or_mark_retry_failed(tmp_path, monkeypatch):
    args, story, run = phase_harness(tmp_path, monkeypatch, lambda *a, **kw: pytest.fail("runner called"))
    args.dry_run = True
    assert storyforge.run_phase(args, story, run, run / "summary.md", 3, 0)
    assert not list(tmp_path.glob(".story.attempt-*"))
    assert not (run / "retry-feedback.json").exists()


def test_identical_rewritten_failure_is_current_attempt_diagnostic(tmp_path):
    story = tmp_path / "story"
    run = story / "runs/r"
    write(story / "draft.md", "approved")
    for _ in range(2):
        with lib.StagedStory(story, run, 3):
            lib.write_text(run / "phase3.validator.log", "SAME_VALIDATOR_FAILURE")
        prompt, manifest = lib.retry_feedback_prompt(story, run)
        assert "SAME_VALIDATOR_FAILURE" in prompt
        assert "phase3.validator.log" in manifest["included"]


@pytest.mark.parametrize("runner_name", ["manual-prompt-pack", "agent"])
def test_manual_pack_instructions_resume_from_canonical_bundle(tmp_path, monkeypatch, runner_name):
    import subprocess
    def runner(cmd, *a, **kw):
        return subprocess.run(cmd, cwd=kw["cwd"], text=True, capture_output=True), {}
    args, story, run = phase_harness(tmp_path, monkeypatch, runner)
    args.runner = runner_name
    monkeypatch.setenv("STORYFORGE_AGENT_PROVIDER_PHASE_3", "manual-prompt-pack")
    assert not storyforge.run_phase(args, story, run, run / "summary.md", 3, 0)
    todo = (run / "manual-prompt-pack/phase3.todo.md").read_text()
    assert f"Save the response as `{run / 'phase3.model.out'}`" in todo
    assert "storyforge-runner-" not in todo
    write(run / "phase3.model.out", block({"draft.md": "MANUAL_NEW"}))
    monkeypatch.setattr(storyforge, "validate_phase", lambda *a, **kw: subprocess.CompletedProcess([], 0, "", ""))
    assert storyforge.run_phase(args, story, run, run / "summary.md", 3, 1)
    assert (story / "draft.md").read_text().strip() == "MANUAL_NEW"


@pytest.mark.parametrize("command", ["run", "approve-gate"])
@pytest.mark.parametrize("run_id", ["..", "../../outside", "nested/run"])
def test_cli_rejects_run_path_escape_before_artifacts(tmp_path, command, run_id):
    story = tmp_path / "story"
    write(story / "source.md", "original source")
    args = [command, "--story", story, "--run-id", run_id]
    if command == "run":
        args += ["--runner", "manual-prompt-pack", "--dry-run", "--to-phase", "1"]
    else:
        args += ["--gate", "phase2_blueprint_review"]
    result = run_storyforge(*args)
    assert result.returncode == storyforge.RUNNER_EXIT_VALIDATION_FAILED
    assert "Run ID must be" in result.stderr
    assert not (story / "runs").exists()
    assert not (story / "run-manifest.json").exists()
    assert not (tmp_path / "outside").exists()
    assert (story / "source.md").read_text() == "original source"


@pytest.mark.parametrize("command", ["run", "approve-gate"])
@pytest.mark.parametrize("kind", ["absolute", "symlink"])
def test_cli_rejects_external_run_directory(tmp_path, command, kind):
    story = tmp_path / "story"
    outside = tmp_path / "outside"
    outside.mkdir()
    write(outside / "keep.txt", "keep")
    write(story / "source.md", "original source")
    run_id = str(outside)
    if kind == "symlink":
        (story / "runs").mkdir()
        (story / "runs" / "linked").symlink_to(outside, target_is_directory=True)
        run_id = "linked"
    args = [command, "--story", story, "--run-id", run_id]
    if command == "run":
        args += ["--runner", "manual-prompt-pack", "--dry-run", "--to-phase", "1"]
    else:
        args += ["--gate", "phase2_blueprint_review"]
    result = run_storyforge(*args)
    assert result.returncode == storyforge.RUNNER_EXIT_VALIDATION_FAILED
    assert sorted(p.name for p in outside.iterdir()) == ["keep.txt"]
    assert (outside / "keep.txt").read_text() == "keep"
