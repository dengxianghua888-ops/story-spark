"""Ragged map rows must not hide conflicting chapter declarations."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from phase_gate import run_gate
from production_quality import chapter_hook_coverage
from storyforge_lib import parse_artifact_bundle
from test_chapter_hook_bindings import chapter_story, write_map
from test_production_quality import write_bundle
from test_repair_failure_gates import prepare_final
from test_stage_safety import tree_bytes
from test_storyforge_runner import run_storyforge


@pytest.mark.parametrize("conflict", [
    "| 第1章 |",
    "| 第1章 | 800 |",
    "| 第1章 | 800 | another hook | extra |",
    "| --- | --- | --- |\n| 第1章 | 800 | - |",
    "| unknown |\n| 第1章 | 800 | - |",
    "| 章 | 字数 | 本章钩子 |\n| 第1章 | 800 | - |",
])
def test_ragged_and_control_looking_rows_cannot_hide_duplicate(tmp_path, conflict):
    story = chapter_story(tmp_path)
    before = write_map(story, ["| 1 | 800 | first hook |", "| 2 | 800 | second hook |", conflict])
    assert chapter_hook_coverage(story) == (1, 2, 0.5)
    assert (story / "final-chapters/_chapters-map.md").read_text() == before


@pytest.mark.parametrize("row", ["| 1 |", "| 1 | 800 |", "| 1 | 800 | hook | extra |"])
@pytest.mark.parametrize("position", [0, 1, 2])
def test_ragged_declared_identity_never_certifies_itself(tmp_path, row, position):
    story = chapter_story(tmp_path)
    rows = ["| 1 | 800 | first hook |", "| 2 | 800 | second hook |"]
    rows.insert(position, row)
    write_map(story, rows)
    assert chapter_hook_coverage(story) == (1, 2, 0.5)


@pytest.mark.parametrize("row", ["| 900 |", "| unknown |", "| --- | --- | --- |"])
def test_unrelated_body_rows_do_not_drop_later_actual_chapters(tmp_path, row):
    story = chapter_story(tmp_path)
    write_map(story, ["| 1 | 800 | first hook |", row, "| 2 | 800 | second hook |"])
    assert chapter_hook_coverage(story) == (2, 2, 1.0)


@pytest.mark.parametrize("columns", [3, 4])
@pytest.mark.parametrize("ragged", ["| 1 |", "| 1 | 800 | hook | extra | another |"])
def test_wrong_width_row_cannot_supply_hook_by_itself(tmp_path, columns, ragged):
    story = chapter_story(tmp_path)
    header = "| 章 | 字数 |" + (" 文件 |" if columns == 4 else "") + " 本章钩子 |"
    row = "| 2 | 800 |" + (" ch02.md |" if columns == 4 else "") + " second hook |"
    write_map(story, [ragged, row], header, "|" + "---|" * columns)
    assert chapter_hook_coverage(story) == (1, 2, 0.5)


@pytest.mark.parametrize("boundary", ["", "ordinary prose", "## New section"])
def test_nonrow_boundaries_still_require_a_new_chapter_header(tmp_path, boundary):
    story = chapter_story(tmp_path)
    text = write_map(story, ["| 1 | 800 | first hook |"])
    text += boundary + "\n| 编号 | 字数 | 备注 |\n|---|---|---|\n| 2 | 800 | not a hook declaration |\n"
    (story / "final-chapters/_chapters-map.md").write_text(text)
    assert chapter_hook_coverage(story) == (1, 2, 0.5)


@pytest.mark.parametrize("mode", ["production", "ultra_short", "production_v6"])
@pytest.mark.parametrize("conflict", ["| 第1章 | 800 |", "| unknown |\n| 第1章 | 800 | - |"])
def test_real_gate_and_reused_cli_reject_hidden_conflict(tmp_path, mode, conflict):
    story, phase, fixtures, args = prepare_final(tmp_path, mode)
    env = {"STORYFORGE_MOCK_FIXTURE_DIR": str(fixtures)}
    valid = run_storyforge(*args, env=env)
    assert valid.returncode == 0, valid.stdout + valid.stderr
    before = tree_bytes(story)
    snapshot = story / f"runs/repair/phase{phase}.completed-snapshot.json"
    prior_snapshot = snapshot.read_bytes()

    bundle = fixtures / f"phase{phase}.bundle.txt"
    files = parse_artifact_bundle(bundle.read_text())
    files["final-chapters/_chapters-map.md"] += conflict + "\n"
    write_bundle(bundle, files)
    rejected = run_storyforge(*args, env=env)
    assert rejected.returncode == 23, rejected.stdout + rejected.stderr
    assert tree_bytes(story) == before
    assert snapshot.read_bytes() == prior_snapshot
    manifest = json.loads((story / "runs/repair/run-manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert "chapter_hooks" in (story / f"runs/repair/phase{phase}.validator.log").read_text()

    # The standalone repair/validator gate must reject the same input without
    # changing the hook declarations or relying only on subprocess exit status.
    map_path = story / "final-chapters/_chapters-map.md"
    map_path.write_text(files["final-chapters/_chapters-map.md"])
    gate = run_gate(story, phase, mode, 7, False)
    assert gate["status"] == "validator_fail", gate
    assert any("chapter_hooks:" in item for item in gate["failures"])
    assert map_path.read_text() == files["final-chapters/_chapters-map.md"]
