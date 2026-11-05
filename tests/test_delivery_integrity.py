"""Regressions for story-grounded delivery and finite score evidence."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from production_quality import (chapter_text_consistency, machine_evaluate,
                                validate_quality_report_shape, validate_evaluation_files)
from repairs.repair_direct_submission import run as repair_submission
from test_production_quality import (add_common_production_artifacts, make_story_text,
                                     production_quality_report, write)


def test_missing_paywall_map_requests_editorial_review_without_inventing_story(tmp_path):
    write(tmp_path / "final.md", "# 火星航行\n\n# 第1章\n\n宇航员打开气闸。\n")
    original = "# 投稿材料\n\n宇航员寻找失联探测器。\n"
    write(tmp_path / "tomato-submission.md", original)
    result = repair_submission(tmp_path)
    assert result["status"] == "manual_review_required"
    assert result["manual_review"]
    assert result["paywall_map"] == {"required": 3, "actual": 0}
    assert (tmp_path / "tomato-submission.md").read_text() == original
    assert "## 第1章" in (tmp_path / "final.md").read_text()
    assert result["changes"] == ["chapter_headings_h1_to_h2"]


def test_partial_paywall_map_is_preserved_and_sufficient_map_is_unchanged(tmp_path):
    original = "## 付费节点地图\n\n| 节点 | 位置 | 悬念 |\n|---|---|---|\n| 1 | 第一章 | 气闸外传来敲击 |\n"
    write(tmp_path / "tomato-submission.md", original)
    result = repair_submission(tmp_path)
    assert result["status"] == "manual_review_required"
    assert result["paywall_map"]["actual"] == 1
    assert (tmp_path / "tomato-submission.md").read_text() == original
    complete = original + "| 2 | 第二章 | 信标重启 |\n| 3 | 第三章 | 救援抵达 |\n"
    write(tmp_path / "tomato-submission.md", complete)
    assert repair_submission(tmp_path)["status"] == "ok"
    assert (tmp_path / "tomato-submission.md").read_text() == complete


def test_missing_submission_is_not_created(tmp_path):
    assert repair_submission(tmp_path)["status"] == "manual_review_required"
    assert not (tmp_path / "tomato-submission.md").exists()


@pytest.mark.parametrize("mutation", ["duplicate", "swap", "missing", "extra", "edited"])
def test_chapter_delivery_drift_fails_machine_gate(tmp_path, mutation):
    add_common_production_artifacts(tmp_path, make_story_text())
    assert not machine_evaluate(tmp_path, 7, "production")["failures"]
    chapters = sorted((tmp_path / "final-chapters").glob("ch*.md"))
    first, second = chapters[0].read_text(), chapters[1].read_text()
    if mutation == "duplicate":
        chapters[0].write_text(second)
    elif mutation == "swap":
        chapters[0].write_text(second)
        chapters[1].write_text(first)
    elif mutation == "missing":
        chapters[-1].unlink()
    elif mutation == "extra":
        write(tmp_path / "final-chapters/ch99.md", first)
    else:
        chapters[0].write_text(first.replace("闻夏", "宇航员", 1))
    result = machine_evaluate(tmp_path, 7, "production")
    assert any("chapter_text_consistency" in fail for fail in result["failures"])
    assert result["chapters"]["status"] == "fail"


def test_consistency_ignores_only_heading_and_whitespace_packaging(tmp_path):
    write(tmp_path / "ch01.md", "# 启航\n\n甲。\n\n乙。\n")
    write(tmp_path / "ch02.md", "丙。\n")
    result = chapter_text_consistency("# 标题\n\n导语：引子。\n\n## 第一章 启航\n甲。乙。\n## 第 2 章 归航\n丙。\n", [tmp_path / "ch01.md", tmp_path / "ch02.md"])
    assert result["status"] == "pass"


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_critic_and_evaluation_scores_are_rejected(tmp_path, score):
    import json
    report = production_quality_report()
    report["critic_scores"]["platform"] = score
    errors = validate_quality_report_shape(report, {"failures": []}, 7)
    assert any("critic_scores.platform must be a number" in item for item in errors)
    write(tmp_path / "evaluation/platform.json", json.dumps({"status": "pass", "score": score, "evidence": ["正文气闸动作"]}))
    errors = validate_evaluation_files(tmp_path, report)
    assert any("platform.json score must be a number" in item for item in errors)


def test_internal_h2_heading_is_compared_as_body_not_new_chapter(tmp_path):
    body = "## 日记摘录\n\n甲。\n\n## 记录续篇\n\n乙。"
    write(tmp_path / "ch01.md", body)
    assert chapter_text_consistency("# 标题\n\n## 第1章\n" + body, [tmp_path / "ch01.md"])["status"] == "pass"


def test_real_repair_orchestrator_and_gate_block_missing_map(tmp_path):
    from auto_repair import run_repair_pass
    from phase_gate import run_gate
    add_common_production_artifacts(tmp_path, make_story_text())
    original = "# 投稿材料\n\n宇航员寻找失联探测器。\n"
    write(tmp_path / "tomato-submission.md", original)
    repaired = run_repair_pass(tmp_path, 7, "production")
    assert repaired["status"] == "manual_review_required"
    assert "direct_submission" in repaired["blocking"]
    gated = run_gate(tmp_path, 7, "production", 7, False)
    assert gated["status"] != "pass"
    assert any("submission_paywall_map" in error for error in gated["failures"])
    assert (tmp_path / "tomato-submission.md").read_text() == original
