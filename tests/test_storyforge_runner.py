import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_production_quality import direct_submission_final, add_common_production_artifacts, count_nonspace, make_story_text, split_story_text, write_bundle


def run_storyforge(*args, env=None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "storyforge.py"), *map(str, args)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=merged_env,
    )


def run_script(script, *args):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_mock_runner_completes_full_pipeline(tmp_path):
    story = tmp_path / "mock_story"
    write(story / "source.md", "这是一篇合成测试原文。")

    result = run_storyforge(
        "run",
        "--story",
        story,
        "--runner",
        "mock",
        "--run-id",
        "mock_full",
        "--no-human-gates",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert (story / "final.md").exists()
    assert (story / "quality-report.json").exists()
    manifest = json.loads((story / "runs" / "mock_full" / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["last_provider"] == "mock"


def test_artifact_bundle_rejects_path_escape(tmp_path):
    story = tmp_path / "story"
    run_dir = story / "runs" / "bad"
    write(story / "source.md", "source")
    write(run_dir / "phase1.model.out", "<<<FILE: ../evil.md>>>\nno\n<<<END FILE>>>\n")

    result = run_script(
        "apply-artifact-bundle.py",
        "--story",
        story,
        "--phase",
        "1",
        "--bundle",
        run_dir / "phase1.model.out",
        "--run-dir",
        run_dir,
    )

    assert result.returncode != 0
    assert "cannot contain '..'" in result.stderr
    assert not (tmp_path / "evil.md").exists()


def test_agent_runner_falls_back_to_mock_provider(tmp_path):
    story = tmp_path / "fallback_story"
    write(story / "source.md", "这是一篇合成测试原文。")

    result = run_storyforge(
        "run",
        "--story",
        story,
        "--runner",
        "agent",
        "--run-id",
        "fallback",
        "--no-human-gates",
        env={"STORYFORGE_AGENT_PROVIDER_PRIORITY": "missing,mock"},
    )

    assert result.returncode == 0, result.stderr + result.stdout
    manifest = json.loads((story / "runs" / "fallback" / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["last_provider"] == "mock"
    summary = (story / "runs" / "fallback" / "execution-summary.md").read_text(encoding="utf-8")
    assert "| 5 | completed |" in summary


def test_phase2_human_gate_stops_agent_runner(tmp_path):
    story = tmp_path / "gated_story"
    write(story / "source.md", "这是一篇合成测试原文。")

    result = run_storyforge(
        "run",
        "--story",
        story,
        "--runner",
        "agent",
        "--run-id",
        "gate",
        env={"STORYFORGE_AGENT_PROVIDER_PRIORITY": "mock"},
    )

    assert result.returncode == 24
    assert "Human gate required" in result.stdout
    assert (story / "adaptation.md").exists()
    assert not (story / "draft.md").exists()


def test_source_policy_denied_blocks_trusted_agent(tmp_path):
    story = tmp_path / "denied_story"
    write(story / "source.md", "source")
    write(
        story / "story.yaml",
        """slug: denied_story
status: phase1
source_policy:
  access: denied
""",
    )

    result = run_storyforge("run", "--story", story, "--runner", "agent", "--run-id", "denied")

    assert result.returncode == 30
    assert "source_policy.access=denied" in result.stderr


def test_manual_prompt_pack_resumes_from_existing_output_bundle(tmp_path):
    story = tmp_path / "manual_resume_story"
    write(story / "source.md", "这是一篇合成测试原文。")
    run_dir = story / "runs" / "manual_resume"
    fixture = ROOT / "tests" / "fixtures" / "mock-runs" / "phase1.bundle.txt"
    # A manual bundle must answer a previously captured input snapshot.
    first = run_storyforge("run", "--story", story, "--runner", "manual-prompt-pack",
                          "--run-id", "manual_resume", "--max-retries", "0", "--no-human-gates")
    assert first.returncode == 23
    write(run_dir / "phase1.model.out", fixture.read_text(encoding="utf-8"))

    result = run_storyforge(
        "run",
        "--story",
        story,
        "--runner",
        "manual-prompt-pack",
        "--run-id",
        "manual_resume",
        "--max-retries",
        "0",
        "--no-human-gates",
    )

    assert result.returncode == 23
    assert (story / "dissection.md").exists()
    summary = (run_dir / "execution-summary.md").read_text(encoding="utf-8")
    assert "| 1 | completed |" in summary
    assert "manual prompt pack generated" in summary


def test_render_phase_prompt_expands_story_glob_inputs(tmp_path):
    story = tmp_path / "glob_story"
    write(story / "source.md", "源文")
    write(story / "beat-bible.json", "{}")
    write(story / "analysis" / "style-dna.md", "# style\n")
    write(story / "analysis" / "soul-contract.md", "# soul\n")
    write(story / "scene-cards" / "scene-01.json", '{"scene_id":"scene-01","must_include":["遗嘱"]}')
    write(story / "scene-cards" / "scene-02.json", '{"scene_id":"scene-02","must_include":["录音"]}')

    result = run_script(
        "render-phase-prompt.py",
        "--story",
        story,
        "--phase",
        "5",
        "--mode",
        "production",
    )

    assert result.returncode == 0, result.stderr
    assert "### story/scene-cards/scene-01.json" in result.stdout
    assert "### story/scene-cards/scene-02.json" in result.stdout
    assert "遗嘱" in result.stdout
    assert "[MISSING INPUT: " + str(story / "scene-cards") not in result.stdout
    assert "scene-rewrite-todo.json" in result.stdout


def test_storyforge_normalizes_phase3_and_phase4_fixture_drift(tmp_path):
    story = tmp_path / "normalize_story"
    add_common_production_artifacts(story, make_story_text(10500))
    fixtures = tmp_path / "fixtures"
    write_bundle(
        fixtures / "phase3.bundle.txt",
        {
            "adaptation.md": "# adaptation\n",
            "adaptation-room.json": json.dumps(
                {
                    "selected_candidate": {"id": "A", "premise": "遗嘱触发谜题"},
                    "candidates": [
                        {"id": "A", "premise": "遗嘱触发谜题", "freshness_score": 8.6, "fidelity_score": 8.8, "tomato_score": 8.7, "logic_score": 8.8, "risks": []},
                        {"id": "B", "premise": "审计触发谜题", "freshness_score": 8.6, "fidelity_score": 8.6, "tomato_score": 8.6, "logic_score": 8.6, "risks": []},
                        {"id": "C", "premise": "押金触发谜题", "freshness_score": 8.6, "fidelity_score": 8.6, "tomato_score": 8.6, "logic_score": 8.6, "risks": []},
                    ],
                    "replacement_map": {"原文载体": "遗嘱"},
                    "mechanism_preservation": {"M6": {"carrier": "遗嘱第二页"}},
                    "sensitive_topic_policy": "不猎奇。",
                },
                ensure_ascii=False,
            ),
        },
    )
    bible = json.loads((story / "beat-bible.json").read_text(encoding="utf-8"))
    for beat in bible["beats"]:
        beat["forbidden_summary"] = beat["forbidden_summary"][0]
    phase4_files = {"beat-bible.json": json.dumps(bible, ensure_ascii=False)}
    for path in sorted((story / "scene-cards").glob("*.json")):
        phase4_files[f"scene-cards/{path.name}"] = path.read_text(encoding="utf-8")
    write_bundle(fixtures / "phase4.bundle.txt", phase4_files)

    result = run_storyforge(
        "run",
        "--story",
        story,
        "--runner",
        "mock",
        "--mode",
        "production",
        "--from-phase",
        "3",
        "--run-id",
        "normalize",
        "--max-retries",
        "0",
        "--no-human-gates",
        env={"STORYFORGE_MOCK_FIXTURE_DIR": str(fixtures)},
    )

    assert result.returncode == 23
    summary = (story / "runs" / "normalize" / "execution-summary.md").read_text(encoding="utf-8")
    assert "| 3 | completed |" in summary
    assert "| 4 | completed |" in summary
    assert json.loads((story / "adaptation-room.json").read_text(encoding="utf-8"))["selected_candidate"] == "A"
    normalized_bible = json.loads((story / "beat-bible.json").read_text(encoding="utf-8"))
    assert all(isinstance(beat["forbidden_summary"], list) for beat in normalized_bible["beats"])


def test_storyforge_phase6_normalizes_scores_but_preserves_fail_gate(tmp_path):
    story = tmp_path / "phase6_fail_story"
    draft_text = make_story_text(10500)
    add_common_production_artifacts(story, draft_text)
    fixtures = tmp_path / "fixtures"
    report = {
        "schema_version": 2,
        "pipeline_mode": "production",
        "gate_status": "fail",
        "critical_failures": [{"id": "logic", "issue": "证据链断裂"}],
        "important_failures": [],
        "machine_metrics": {"target_length": {"actual": 42, "status": "pass"}},
        "critic_scores": {"platform": 78, "emotion": 90, "style": 82, "logic": 64},
        "evidence": [{"id": "E1", "quote": "证据链断裂"}],
    }
    write_bundle(
        fixtures / "phase6.bundle.txt",
        {
            "review.md": "# Critic Gauntlet Review\n\n## Gate Status: FAIL\n",
            "quality-report.json": json.dumps(report, ensure_ascii=False),
            "diff.md": "# diff\n",
            "evaluation/platform.json": json.dumps({"status": "pass", "score": 78, "evidence": ["开篇金额反差成立"]}, ensure_ascii=False),
            "evaluation/emotion.json": json.dumps({"status": "pass", "score": 90, "evidence": ["母女误解债有偿还"]}, ensure_ascii=False),
            "evaluation/style.json": json.dumps({"status": "pass", "score": 82, "evidence": ["动作细节推动情绪"]}, ensure_ascii=False),
            "evaluation/logic.json": json.dumps({"status": "fail", "score": 64, "evidence": ["证据链断裂"]}, ensure_ascii=False),
        },
    )

    result = run_storyforge(
        "run",
        "--story",
        story,
        "--runner",
        "mock",
        "--mode",
        "production",
        "--from-phase",
        "6",
        "--run-id",
        "phase6fail",
        "--max-retries",
        "0",
        "--no-human-gates",
        env={"STORYFORGE_MOCK_FIXTURE_DIR": str(fixtures)},
    )

    assert result.returncode == 23
    validator_log = (story / "runs" / "phase6fail" / "phase6.validator.log").read_text(encoding="utf-8")
    assert "quality gate failed: gate_status=fail" in validator_log
    assert "score must be a number from 0 to 10" not in validator_log
    assert "missing machine-readable gate block" not in validator_log
    # A rejected attempt must leave the previously published passing report untouched.
    assert json.loads((story / "quality-report.json").read_text(encoding="utf-8"))["critic_scores"]["logic"] == 8
    candidates = list(tmp_path.glob(".phase6_fail_story.attempt-*/phase6_fail_story/quality-report.json"))
    assert any(json.loads(path.read_text())["critic_scores"]["logic"] == 6.4 for path in candidates)


def test_storyforge_phase7_fallback_repacks_overlong_chapters_from_scenes(tmp_path):
    story = tmp_path / "phase7_fallback_story"
    draft_text = make_story_text(10500)
    add_common_production_artifacts(story, draft_text)
    chunks = split_story_text(draft_text)
    fixtures = tmp_path / "fixtures"
    overlong = "\n".join(chunks[:2])
    phase7_files = {
        "final.md": direct_submission_final(chunks),
        "craft-notes.md": "# craft\n",
        "tomato-submission.md": "# submission\n",
        "story.yaml": "slug: phase7_fallback_story\npipeline_mode: production\nstatus: final\n",
        "final-chapters/_chapters-map.md": "| 章 | 字数 | 本章悬念 |\n|---|---:|---|\n| 01 | 1300 | 下一章 |\n",
        "final-chapters/ch01.md": overlong,
    }
    for index in range(2, 9):
        phase7_files[f"final-chapters/ch{index:02d}.md"] = chunks[min(index, len(chunks)) - 1]
    write_bundle(fixtures / "phase7.bundle.txt", phase7_files)
    write_bundle(
        fixtures / "phase8.bundle.txt",
        {
            "feedback-learning.json": json.dumps(
                {
                    "story_slug": "phase7_fallback_story",
                    "pipeline_mode": "production",
                    "failure_types": [],
                    "successful_hooks": ["遗嘱触发失踪亲属信息差"],
                    "quality_scores": {"platform": 8, "emotion": 8, "style": 8, "logic": 8},
                    "manual_revision_delta": [],
                },
                ensure_ascii=False,
            )
        },
    )

    result = run_storyforge(
        "run",
        "--story",
        story,
        "--runner",
        "mock",
        "--mode",
        "production",
        "--from-phase",
        "7",
        "--run-id",
        "phase7fallback",
        "--max-retries",
        "0",
        "--no-human-gates",
        "--heartbeat-seconds",
        "1",
        env={"STORYFORGE_MOCK_FIXTURE_DIR": str(fixtures)},
    )

    assert result.returncode == 0, result.stderr + result.stdout
    chapter_files = sorted((story / "final-chapters").glob("ch*.md"))
    assert len(chapter_files) == len(chunks)
    assert all(500 <= count_nonspace(path.read_text(encoding="utf-8")) <= 1200 for path in chapter_files)
    assert "status: test_fixture" in (story / "story.yaml").read_text(encoding="utf-8")
    progress = (story / "runs" / "phase7fallback" / "phase7.runner.progress.log").read_text(encoding="utf-8")
    assert "phase=7" in progress
    assert "elapsed=" in progress
    assert "pid=" in progress
