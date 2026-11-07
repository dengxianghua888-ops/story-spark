"""Hook coverage belongs to delivered chapter identities, not row totals."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from phase_gate import run_gate
from production_quality import chapter_hook_coverage, machine_evaluate
from storyforge_lib import phase_for_role
from test_submission_mode_thresholds import prepare_story


def write_map(story, rows, header="| 章 | 字数 | 本章钩子 |", separator="|---|---:|---|"):
    text = "\n".join([header, separator, *rows]) + "\n"
    (story / "final-chapters/_chapters-map.md").write_text(text, encoding="utf-8")
    return text


@pytest.mark.parametrize("mode,chars", [("production", 10200), ("ultra_short", 6300), ("production_v6", 3200)])
@pytest.mark.parametrize("mutation", ["duplicate", "unknown", "unrelated", "conflicting", "valid_keywords"])
def test_real_gate_binds_hooks_to_unique_delivered_chapters(tmp_path, mode, chars, mutation):
    prepare_story(tmp_path, mode, chars)
    chapters = sorted((tmp_path / "final-chapters").glob("ch*.md"))
    rows = []
    for index, _ in enumerate(chapters, 1):
        key = "01" if mutation == "duplicate" else str(900 + index) if mutation == "unknown" else f"{index:02}"
        hook = "Hook 计划---下一章揭开钩子的秘密" if mutation == "valid_keywords" else "门外是谁？"
        rows.append(f"| {key} | 800 | {hook} |")
    if mutation == "conflicting":
        rows.append("| 第1章 | 800 | - |")
    header = "| 编号 | 字数 | 备注 |" if mutation == "unrelated" else "| 章 | 字数 | 本章钩子 |"
    before = write_map(tmp_path, rows, header)
    phase = phase_for_role(mode, "final")
    metrics = machine_evaluate(tmp_path, phase, mode)
    result = run_gate(tmp_path, phase, mode, 7, False)
    if mutation == "valid_keywords":
        assert metrics["chapters"]["hook_coverage"] == 1
        assert result["status"] == "pass", result["failures"]
    else:
        assert metrics["chapters"]["hook_coverage"] < 1
        assert result["status"] == "validator_fail"
        assert any("chapter_hooks:" in item for item in result["failures"])
    assert (tmp_path / "final-chapters/_chapters-map.md").read_text(encoding="utf-8") == before


def chapter_story(tmp_path):
    directory = tmp_path / "final-chapters"
    directory.mkdir()
    for name in ("ch01.md", "ch02.md"):
        (directory / name).write_text("正文。", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("labels", [("01", "02"), ("1", "2"), ("第 1 章", "第2章"), ("ch01", "ch02"), ("ch01.md", "ch02.md")])
@pytest.mark.parametrize("header", ["| 章 | 字数 | 本章钩子 |", "| 章节 | 文件 | Hook |", "| Chapter | Words | Hook |", "| 章 | 字数 | 本章悬念 |"])
def test_existing_chapter_label_and_header_formats(tmp_path, labels, header):
    story = chapter_story(tmp_path)
    write_map(story, [f"| {labels[0]} | 800 | 问号？ |", f"| {labels[1]} | 800 | 门开了 |"], header,
              "| :--- | ---: | :---: |")
    assert chapter_hook_coverage(story) == (2, 2, 1.0)


@pytest.mark.parametrize("hook", ["", "-", "—", "无", "none", "None", "NONE"])
def test_empty_or_placeholder_hook_does_not_cover_chapter(tmp_path, hook):
    story = chapter_story(tmp_path)
    write_map(story, ["| 1 | 800 | 门外是谁？ |", f"| 2 | 800 | {hook} |"])
    assert chapter_hook_coverage(story) == (1, 2, 0.5)


def test_unrelated_tables_and_fenced_examples_cannot_supply_missing_chapter(tmp_path):
    story = chapter_story(tmp_path)
    text = write_map(story, ["| 1 | 800 | 门外是谁？ |"])
    text += "\n## 统计\n| 编号 | 字数 | 备注 |\n|---|---|---|\n| 2 | 800 | 非钩子 |\n"
    text += "\n```markdown\n| 章 | 字数 | 本章钩子 |\n|---|---|---|\n| 2 | 800 | 仅示例 |\n```\n"
    (story / "final-chapters/_chapters-map.md").write_text(text, encoding="utf-8")
    assert chapter_hook_coverage(story) == (1, 2, 0.5)


def test_hook_content_escaped_pipe_and_keywords_are_not_control_rows(tmp_path):
    story = chapter_story(tmp_path)
    write_map(story, [r"| 1 | 800 | Hook 计划---下一章揭开钩子的秘密 \| 是谁？ |",
                      "| 2 | 800 | 门开了 |"])
    assert chapter_hook_coverage(story) == (2, 2, 1.0)


def test_missing_map_or_chapters_has_no_coverage(tmp_path):
    assert chapter_hook_coverage(tmp_path) == (0, 0, 0.0)
    story = chapter_story(tmp_path)
    assert chapter_hook_coverage(story) == (0, 2, 0.0)


def test_file_number_gaps_bind_actual_files_not_row_positions(tmp_path):
    story = chapter_story(tmp_path)
    (story / "final-chapters/ch02.md").rename(story / "final-chapters/ch07.md")
    write_map(story, ["| 1 | 800 | 门外是谁？ |", "| 2 | 800 | 门开了 |"])
    assert chapter_hook_coverage(story) == (1, 2, 0.5)
    write_map(story, ["| 7 | 800 | 门开了 |", "| 1 | 800 | 门外是谁？ |"])
    assert chapter_hook_coverage(story) == (2, 2, 1.0)


def test_ambiguous_file_number_aliases_do_not_pass(tmp_path):
    story = chapter_story(tmp_path)
    (story / "final-chapters/ch1.md").write_text("重复身份。", encoding="utf-8")
    write_map(story, ["| 1 | 800 | 门外是谁？ |", "| 2 | 800 | 门开了 |", "| 01 | 800 | 门外是谁？ |"])
    assert chapter_hook_coverage(story)[2] < 1


@pytest.mark.parametrize("mode", ["production", "ultra_short", "production_v6"])
@pytest.mark.parametrize("valid", [False, True])
def test_actual_cli_publication_respects_chapter_identity(tmp_path, mode, valid):
    import json

    from storyforge_lib import parse_artifact_bundle
    from test_production_quality import write_bundle
    from test_repair_failure_gates import prepare_final
    from test_stage_safety import tree_bytes
    from test_storyforge_runner import run_storyforge

    story, phase, fixtures, args = prepare_final(tmp_path, mode)
    before = tree_bytes(story)
    bundle = fixtures / f"phase{phase}.bundle.txt"
    files = parse_artifact_bundle(bundle.read_text())
    count = len(list((story / "final-chapters").glob("ch*.md")))
    rows = ["| 章 | 字数 | 本章钩子 |", "|---|---:|---|"]
    for index in range(1, count + 1):
        key = str(index) if valid else "1"
        hook = "Hook 计划---下一章揭开钩子的秘密" if valid else "门外是谁？"
        rows.append(f"| {key} | 800 | {hook} |")
    files["final-chapters/_chapters-map.md"] = "\n".join(rows) + "\n"
    write_bundle(bundle, files)
    result = run_storyforge(*args, env={"STORYFORGE_MOCK_FIXTURE_DIR": str(fixtures)})
    snapshot = story / f"runs/repair/phase{phase}.completed-snapshot.json"
    manifest = json.loads((story / "runs/repair/run-manifest.json").read_text())
    if valid:
        assert result.returncode == 0, result.stdout + result.stderr
        assert snapshot.exists()
        assert manifest["status"] == "completed"
        assert (story / "final-chapters/_chapters-map.md").read_text() == files["final-chapters/_chapters-map.md"]
    else:
        assert result.returncode == 23, result.stdout + result.stderr
        assert not snapshot.exists()
        assert manifest["status"] == "failed"
        assert tree_bytes(story) == before
        assert "chapter_hooks" in (story / f"runs/repair/phase{phase}.validator.log").read_text()


@pytest.mark.parametrize("mode", ["production", "ultra_short", "production_v6"])
def test_reused_completed_run_records_validator_failure_without_replacing_snapshot(tmp_path, mode):
    import json

    from storyforge_lib import parse_artifact_bundle
    from test_production_quality import write_bundle
    from test_repair_failure_gates import prepare_final
    from test_stage_safety import tree_bytes
    from test_storyforge_runner import run_storyforge

    story, phase, fixtures, args = prepare_final(tmp_path, mode)
    env = {"STORYFORGE_MOCK_FIXTURE_DIR": str(fixtures)}
    assert run_storyforge(*args, env=env).returncode == 0
    before = tree_bytes(story)
    snapshot = story / f"runs/repair/phase{phase}.completed-snapshot.json"
    old_snapshot = snapshot.read_bytes()
    bundle = fixtures / f"phase{phase}.bundle.txt"
    files = parse_artifact_bundle(bundle.read_text())
    count = len(list((story / "final-chapters").glob("ch*.md")))
    files["final-chapters/_chapters-map.md"] = (
        "| 章 | 字数 | 本章钩子 |\n|---|---|---|\n" + "| 01 | 800 | 门外是谁？ |\n" * count)
    write_bundle(bundle, files)
    result = run_storyforge(*args, env=env)
    assert result.returncode == 23, result.stdout + result.stderr
    assert tree_bytes(story) == before
    assert snapshot.read_bytes() == old_snapshot
    manifest = json.loads((story / "runs/repair/run-manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["last_failure"] == "validator failed"
