"""Repair diagnostics must block publication, even when validation passes."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import auto_repair
import phase_gate
import storyforge
from storyforge_lib import phase_for_role
from test_production_quality import write_bundle
from test_stage_safety import tree_bytes
from test_storyforge_runner import run_storyforge
from test_submission_mode_thresholds import prepare_story


def prepare_final(tmp_path, mode="production", *, missing_table=False):
    story = tmp_path / "story"
    prepare_story(story, mode, 6300 if mode == "ultra_short" else 10500)
    phase = phase_for_role(mode, "final")
    files = {name: (story / name).read_text() for name in
             ("final.md", "craft-notes.md", "story.yaml", "tomato-submission.md")}
    if missing_table:
        files["tomato-submission.md"] = (
            "## 付费节点地图（直接投稿版）\n\n第1章 第2章 第3章 第4章\n")
    files.update({str(path.relative_to(story)): path.read_text()
                  for path in (story / "final-chapters").glob("*.md")})
    fixtures = tmp_path / "fixtures"
    write_bundle(fixtures / f"phase{phase}.bundle.txt", files)
    args = ["run", "--story", str(story), "--runner", "mock", "--mode", mode,
            "--from-phase", str(phase), "--to-phase", str(phase), "--run-id", "repair",
            "--max-retries", "0", "--no-human-gates", "--skip-rubric"]
    return story, phase, fixtures, args


@pytest.mark.parametrize("mode", ["production", "ultra_short", "production_v6"])
def test_actual_cli_does_not_publish_manual_review_candidate(tmp_path, mode):
    story, phase, fixtures, args = prepare_final(tmp_path, mode, missing_table=True)
    before = tree_bytes(story)
    result = run_storyforge(*args, env={"STORYFORGE_MOCK_FIXTURE_DIR": str(fixtures)})
    repair = json.loads((story / f"runs/repair/phase{phase}.repair-report.json").read_text())
    assert repair["status"] == "manual_review_required"
    assert result.returncode == 23, result.stderr + result.stdout
    assert tree_bytes(story) == before
    manifest = json.loads((story / "runs/repair/run-manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert "repair" in manifest["last_failure"]
    assert not (story / f"runs/repair/phase{phase}.completed-snapshot.json").exists()
    assert list(tmp_path.glob(".story.attempt-*/story/tomato-submission.md"))


@pytest.mark.parametrize("outcome", ["exception", "fail", "invalid", "unknown"])
def test_repair_failure_is_not_aggregated_as_success(tmp_path, monkeypatch, outcome):
    def repair(*args, **kwargs):
        if outcome == "exception":
            raise OSError("synthetic repair write failure")
        if outcome == "invalid":
            return None
        return {"name": "metadata", "status": "fail" if outcome == "fail" else "mystery",
                "reason": "synthetic failure"}

    monkeypatch.setattr(auto_repair.repair_metadata, "run", repair)
    result = auto_repair.run_repair_pass(tmp_path, 8, "production")
    assert result["status"] == "fail"
    assert result["blocking"]
    assert result["results"][0]["status"] == "fail"
    assert json.loads((tmp_path / "repair-report.json").read_text()) == result


def test_standalone_gate_reports_repair_failure_despite_passing_validator(tmp_path, monkeypatch):
    story, _, _, _ = prepare_final(tmp_path)
    monkeypatch.setattr(auto_repair.repair_metadata, "run", lambda *a, **kw:
                        {"name": "metadata", "status": "fail", "reason": "synthetic failure"})
    result = phase_gate.run_gate(story, 7, "production", 8, False)
    assert result["validator"]["status"] == "pass", result
    assert result["repairs"]["status"] == "fail"
    assert result["status"] == "repair_fail"
    assert result["failures"]
    monkeypatch.setattr(phase_gate, "run_gate", lambda *a, **kw: result)
    monkeypatch.setattr(sys, "argv", ["phase_gate.py", "--story", str(story), "--phase", "7"])
    assert phase_gate.main() == 26


@pytest.mark.parametrize("failure", ["returned", "exception"])
def test_pipeline_repair_failure_keeps_live_story(tmp_path, monkeypatch, failure):
    story, phase, fixtures, args = prepare_final(tmp_path)
    before = tree_bytes(story)

    def repair(*a, **kw):
        if failure == "exception":
            raise OSError("synthetic repair report failure")
        return {"status": "fail", "blocking": ["metadata"], "results": []}

    monkeypatch.setattr(auto_repair, "run_repair_pass", repair)
    monkeypatch.setenv("STORYFORGE_MOCK_FIXTURE_DIR", str(fixtures))
    monkeypatch.setattr(sys, "argv", ["storyforge.py", *args])
    assert storyforge.main() == 23
    assert tree_bytes(story) == before
    report = json.loads((story / f"runs/repair/phase{phase}.repair-report.json").read_text())
    assert report["status"] == "fail"
    assert not (story / f"runs/repair/phase{phase}.completed-snapshot.json").exists()


def test_valid_repairs_still_publish(tmp_path):
    story, phase, fixtures, args = prepare_final(tmp_path)
    result = run_storyforge(*args, env={"STORYFORGE_MOCK_FIXTURE_DIR": str(fixtures)})
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads((story / f"runs/repair/phase{phase}.repair-report.json").read_text())
    assert report["status"] == "ok"
    assert (story / f"runs/repair/phase{phase}.completed-snapshot.json").exists()


def test_failed_retry_cannot_keep_prior_completed_run_status(tmp_path):
    story, phase, fixtures, args = prepare_final(tmp_path)
    env = {"STORYFORGE_MOCK_FIXTURE_DIR": str(fixtures)}
    assert run_storyforge(*args, env=env).returncode == 0
    before = tree_bytes(story)
    snapshot = story / f"runs/repair/phase{phase}.completed-snapshot.json"
    prior_snapshot = snapshot.read_bytes()
    bundle = fixtures / f"phase{phase}.bundle.txt"
    text = bundle.read_text()
    start = text.index("<<<FILE: tomato-submission.md>>>")
    end = text.index("<<<END FILE>>>", start)
    bundle.write_text(text[:start] + "<<<FILE: tomato-submission.md>>>\n"
                      "## 付费节点地图\n\n第1章 第2章 第3章 第4章\n" + text[end:])
    assert run_storyforge(*args, env=env).returncode == 23
    assert tree_bytes(story) == before
    manifest = json.loads((story / "runs/repair/run-manifest.json").read_text())
    assert manifest["status"] == "failed"
    # Preserve the prior successful snapshot, never overwrite it for a rejected attempt.
    assert snapshot.read_bytes() == prior_snapshot
