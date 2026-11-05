"""Direct-submission repairs must enforce the evaluator's mode-aware threshold."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from phase_gate import run_gate
from production_quality import machine_evaluate
from repairs.repair_direct_submission import run as repair_submission
from storyforge_lib import phase_for_role
from test_production_quality import (
    add_common_production_artifacts,
    make_story_text,
    submission_with_paywall_map,
    write,
)


def prepare_story(story, mode, chars, source_chars=10, target_min=None):
    add_common_production_artifacts(story, make_story_text(chars), source_text="源" * source_chars)
    minimum, maximum = (6000, 9000) if mode == "ultra_short" else (10000, 18000)
    for filename in ("market-brief.json", "beat-bible.json"):
        path = story / filename
        data = json.loads(path.read_text(encoding="utf-8"))
        data["pipeline_mode"] = mode
        data["target_length"] = {"min": target_min or minimum, "max": maximum}
        if mode == "production_v6" and filename == "beat-bible.json":
            data["chapters"] = [{"chapter_id": "c1", "scenes": ["scene-01"],
                                 "target_char_count": [3000, 25000]}]
        write(path, json.dumps(data))
    write(story / "story.yaml", f"slug: story\npipeline_mode: {mode}\nstatus: final\n")
    if mode == "production_v6":
        write(story / "analysis/chapter-soul-map.json", "{}")
        write(story / "hook/opening-hook.md", "导语：证据忽然被送到门口。")
        write(story / "hook/hook-meta.json", "{}")


@pytest.mark.parametrize("mode,chars,source_chars,target_min,required", [
    ("production", 10200, 10, None, 3),
    ("ultra_short", 6300, 10, None, 2),
    ("production_v6", 3200, 10, None, 1),
    ("production_v6", 6300, 12500, None, 3),
    ("production_v6", 6300, 30000, None, 6),
    ("ultra_short", 8300, 10, 8000, 3),
])
@pytest.mark.parametrize("map_state", ["complete", "short", "missing"])
def test_final_gate_uses_mode_threshold_without_changing_submission(
    tmp_path, mode, chars, source_chars, target_min, required, map_state
):
    prepare_story(tmp_path, mode, chars, source_chars, target_min)
    actual = required if map_state == "complete" else required - 1
    original = (submission_with_paywall_map(actual) if map_state != "missing"
                else "# 投稿材料\n\n编辑尚未补充付费节点。\n")
    write(tmp_path / "tomato-submission.md", original)
    phase = phase_for_role(mode, "final")
    metrics = machine_evaluate(tmp_path, phase, mode)
    assert metrics["direct_submission"]["submission_paywall_map"]["required"] == required
    if map_state == "complete":
        assert metrics["failures"] == []

    result = run_gate(tmp_path, phase, mode, 7, False)
    direct = next(item for item in result["repairs"]["results"] if item["name"] == "direct_submission")
    assert direct["paywall_map"] == {"required": required, "actual": actual if map_state != "missing" else 0}
    if map_state == "complete":
        assert direct["status"] == "ok"
        assert result["validator"]["status"] == "pass", result["failures"]
        assert result["status"] == "pass", result["failures"]
    else:
        assert direct["status"] == "manual_review_required"
        assert "direct_submission" in result["repairs"]["blocking"]
        assert result["status"] != "pass"
        assert any("submission_paywall_map" in failure for failure in result["failures"])
    assert (tmp_path / "tomato-submission.md").read_text(encoding="utf-8") == original


@pytest.mark.parametrize("mode,chars,target_min,required", [
    ("production", 0, None, 3),
    ("ultra_short", 0, None, 2),
    ("production_v6", 0, None, 1),
    ("production_v6", 3500, None, 1),
    ("production_v6", 3501, None, 2),
    ("production", 10500, None, 3),
    ("production", 10501, None, 4),
    ("ultra_short", 6300, 8000, 3),
    ("production", 10200, 15000, 5),
])
def test_repair_threshold_matches_machine_at_boundaries(tmp_path, mode, chars, target_min, required):
    write(tmp_path / "final.md", "文" * chars)
    if target_min:
        write(tmp_path / "beat-bible.json", json.dumps({"target_length": {"min": target_min}}))
    write(tmp_path / "tomato-submission.md", submission_with_paywall_map(required))
    metrics = machine_evaluate(tmp_path, phase_for_role(mode, "final"), mode)
    repaired = repair_submission(tmp_path, mode)
    assert metrics["direct_submission"]["submission_paywall_map"]["required"] == required
    assert repaired["paywall_map"] == {"required": required, "actual": required}
    assert repaired["status"] == "ok"
    write(tmp_path / "tomato-submission.md", submission_with_paywall_map(required - 1))
    assert repair_submission(tmp_path, mode)["status"] == "manual_review_required"


@pytest.mark.parametrize("separator", [
    "|---|---|---|",
    "| :--- | ---: | :---: |",
    "| :-----: | :--- | ----: |",
])
@pytest.mark.parametrize("complete", [True, False])
def test_gate_counts_hyphens_in_content_but_not_table_separators(tmp_path, separator, complete):
    prepare_story(tmp_path, "ultra_short", 6300)
    original = ("## 付费节点地图（直接投稿版）\n\n| 节点 | 位置 | 自然卡点 |\n"
                + separator + "\n| 1 | 第一章末 | 信号---突然中断 |\n")
    if complete:
        original += "| 2 | 第二章末 | 新证据出现 |\n"
    # Neither a separator nor rows in the following section may supply a node.
    original += "\n## 其他材料\n\n| 3 | 第三章末 | 与节点地图无关 |\n"
    write(tmp_path / "tomato-submission.md", original)
    expected = 2 if complete else 1
    metrics = machine_evaluate(tmp_path, 7, "ultra_short")
    assert metrics["direct_submission"]["submission_paywall_map"]["actual"] == expected
    if complete:
        assert metrics["failures"] == []

    result = run_gate(tmp_path, 7, "ultra_short", 7, False)
    direct = next(item for item in result["repairs"]["results"] if item["name"] == "direct_submission")
    assert direct["paywall_map"] == {"required": 2, "actual": expected}
    if complete:
        assert result["validator"]["status"] == "pass", result["failures"]
        assert direct["status"] == "ok"
        assert result["status"] == "pass", result["failures"]
    else:
        assert direct["status"] == "manual_review_required"
        assert result["status"] != "pass"
        assert any("submission_paywall_map" in failure for failure in result["failures"])
    assert (tmp_path / "tomato-submission.md").read_text(encoding="utf-8") == original
