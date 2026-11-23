import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_script(script, *args):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


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


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_story_text(target=10500):
    locations = ["客厅", "律所", "礼堂", "档案室", "走廊", "教室", "门卫室", "会议室", "旧仓库", "天台", "后厨"]
    verbs = ["拿起", "推开", "按住", "递出", "翻开", "锁上", "拍下", "交给", "撕开", "举起", "放回", "打开", "关掉"]
    props = ["遗嘱", "录音笔", "缴费单", "监控截图", "旧钥匙", "亲子报告", "签收单", "短信记录", "档案袋", "水阀照片", "押金单", "合同"]
    opponents = ["父亲", "母亲", "周律师", "校长", "秘书", "保安", "店长", "经理", "审计员", "同学", "房东", "董事长", "邻居"]
    conflicts = ["挡在门口", "抢走文件", "关掉灯", "改了口径", "压低声音威胁", "把责任推给系统", "当众否认签字", "要求她马上道歉", "把证据藏进抽屉", "通知她退出名单"]
    hooks = ["门外有人敲了三下", "第二页露出一个陌生名字", "录音里传来另一道声音", "屏幕上的时间戳对不上", "旧钥匙刚好能打开暗门", "名单最底下多了一行转账编号", "消防记录显示阀门早被关过"]
    questions = ["这一次，你们准备让谁背锅", "这张单子为什么晚了三小时", "谁能解释这枚章的来源", "你们还想把哪页藏起来", "现在还要说系统不会错吗", "这笔钱究竟进了谁的账户", "门后的名字是谁写上去的"]
    parts = []
    index = 1
    while count_nonspace("".join(parts)) < target:
        location = locations[index % len(locations)]
        verb = verbs[index % len(verbs)]
        prop = props[index % len(props)]
        opponent = opponents[index % len(opponents)]
        conflict = conflicts[index % len(conflicts)]
        hook = hooks[index % len(hooks)]
        question = questions[index % len(questions)]
        parts.append(
            f"第{index:04d}场，闻夏在{location}{verb}{prop}。\n\n"
            f"{opponent}{conflict}，她把上一笔旧账记到纸边。\n\n"
            f"她看着众人问：“{question}？”\n\n"
            f"{hook}。\n\n"
        )
        index += 1
    return "".join(parts)


def make_repetitive_story_text(target=10500):
    parts = []
    index = 1
    while sum(len(part) for part in parts) < target:
        parts.append(
            f"第{index:04d}场，闻夏拿起第{index:04d}份证据走到门口。"
            f"母亲伸手拦她，父亲按住文件，周律师把录音笔推过来。"
            f"她看着门缝里的光问：“第{index:04d}个答案，你们还要藏多久？”\n"
        )
        index += 1
    return "".join(parts)[:target]


def count_nonspace(text):
    return sum(1 for char in text if not char.isspace())


def direct_submission_final(chunks):
    parts = [
        "# 合成测试终稿",
        "导语：闻夏被家人压在客厅里签退让协议时，门外忽然送来一份遗嘱。",
        "所有人都说她没资格问第二页，可她已经把录音笔打开。",
        "这一次，她不吵不闹，只等那扇门后的名字自己响起来。",
    ]
    for index, chunk in enumerate(chunks, start=1):
        parts.append(f"## 第 {index} 章")
        parts.append(chunk.strip())
    return "\n\n".join(parts).strip() + "\n"


def submission_with_paywall_map(required=3):
    rows = ["| 节点 | 位置 | 自然卡点 |", "|---|---|---|"]
    for index in range(1, required + 1):
        rows.append(f"| {index} | 第 {index * 3} 章末 | 录音里第 {index} 次露出陌生名字。 |")
    return "# submission\n\n## 付费节点地图（直接投稿版）\n\n正文不显式标注付费点，节点已自然落在章末。\n\n" + "\n".join(rows) + "\n"


def split_story_text(text, target=700):
    chunks = []
    current = []
    current_len = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        current.append(line)
        current_len += count_nonspace(line)
        if current_len >= target:
            chunks.append("\n\n".join(current) + "\n")
            current = []
            current_len = 0
    if current:
        tail = "\n\n".join(current) + "\n"
        if chunks and count_nonspace(tail) < 500:
            chunks[-1] = chunks[-1].rstrip() + "\n" + tail
        else:
            chunks.append(tail)
    return chunks


def production_quality_report(final_text=None, chapter_count=0, hook_coverage=0, paywall_actual=3):
    actual = count_nonspace(final_text) if final_text is not None else 10500
    paywall_required = max(1, math.ceil(max(actual, 10000) / 3500))
    return {
        "schema_version": 2,
        "pipeline_mode": "production",
        "gate_status": "pass",
        "critical_failures": [],
        "important_failures": [],
        "machine_metrics": {
            "target_length": {"min": 10000, "max": 18000, "actual": actual, "status": "pass"},
            "chapters": {"count": chapter_count, "hook_coverage": hook_coverage, "status": "pass"},
            "paywall_cards": {"required": paywall_required, "actual": paywall_actual, "status": "pass"},
            "direct_submission": {
                "status": "pass",
                "opening_guide": {"present": True, "paragraphs": 3, "chars": 91, "status": "pass"},
                "mobile_paragraphs": {"offending_paragraphs": 0, "max_sentence_endings": 1, "examples": [], "status": "pass"},
                "submission_paywall_map": {"required": paywall_required, "actual": max(paywall_required, 3), "present": True, "status": "pass"},
                "visible_paywall_labels": {"hits": [], "count": 0, "status": "pass"},
            },
            "source_rhythm_fit": {"status": "pass", "applicable": False},
            "source_overlap": {"max_continuous_overlap_chars": 0, "status": "pass"},
            "repeated_ngram": {"max_repeated_substring_chars": 0, "status": "pass"},
            "style_metrics": {"avg_sentence_length": 18, "dialogue_ratio": 0.35, "action_density_per_k": 12},
            "forbidden_words": {"hits": {}, "status": "pass"},
            "soft_forbidden_words": {"hits": {}, "status": "pass"},
        },
        "critic_scores": {"platform": 8, "emotion": 8, "style": 8, "logic": 8},
        "evidence": ["开篇用遗嘱和退让协议制造点击钩。", "中段用录音和签收单递进证据。", "结尾以审计报告完成规则回旋。"],
    }


def rhythm_contract():
    return {"avg_visual_line_chars_range": [10, 40],
            "short_line_rate_lte_16_min": 0, "short_line_rate_lte_16_max": 1,
            "direct_dialogue_line_rate_min": 0, "direct_dialogue_line_rate_max": 1,
            "barrage_line_rate_min": 0, "barrage_line_rate_max": 1,
            "question_mark_density_per_1000_chars_min": 0,
            "question_mark_density_per_1000_chars_max": 30}


def add_common_production_artifacts(story, final_text, hookless=False, source_text="合成测试原文"):
    write(story / "source.md", source_text)
    write(
        story / "market-brief.json",
        json.dumps({"pipeline_mode": "production", "target_platform": "tomato", "target_length": {"min": 10000, "max": 18000}}, ensure_ascii=False),
    )
    write(
        story / "story-brief.json",
        json.dumps(
            {
                "source_title": "合成测试原文",
                "genre": "family_ethics",
                "hook_type": "H1",
                "title_formula": "T1",
                "reversal_mechanisms": ["M6"],
                "source_length_chars": len(source_text),
                "reader_promise": "看主角用证据拿回被夺走的机会。",
                "emotional_debts": ["被家人忽视", "被规则压迫"],
                "payoff_pattern": "证据公开后反派按自己规则承担后果。",
                "forbidden_to_change": ["规则回旋", "公开反杀"],
                "replaceable_assets": ["遗嘱", "录音笔"],
            },
            ensure_ascii=False,
        ),
    )
    for rel in [
        "dissection.md",
        "analysis/beat-sheet.md",
        "analysis/style-dna.md",
        "analysis/soul-contract.md",
        "analysis/reader-engine.md",
        "analysis/tension-ledger.md",
        "adaptation.md",
    ]:
        write(story / rel, f"# {rel}\n")
    candidates = [
        {"id": "A", "premise": "遗嘱触发失踪亲属谜题", "freshness_score": 8.6, "fidelity_score": 8.8, "tomato_score": 8.7, "logic_score": 8.8, "risks": ["父母转变不能过快"]},
        {"id": "B", "premise": "助学金审计触发账本反杀", "freshness_score": 8.7, "fidelity_score": 8.6, "tomato_score": 8.6, "logic_score": 8.6, "risks": ["审计流程要简化"]},
        {"id": "C", "premise": "物业押金单触发商户联盟", "freshness_score": 8.8, "fidelity_score": 8.7, "tomato_score": 8.5, "logic_score": 8.7, "risks": ["商户站队要有利益动机"]},
    ]
    write(
        story / "adaptation-room.json",
        json.dumps(
            {
                "selected_candidate": "A",
                "candidates": candidates,
                "replacement_map": {"原文惩罚凭证": "遗嘱和录音笔", "原文公共场": "学校礼堂"},
                "mechanism_preservation": {"M6": {"carrier": "遗嘱第二页", "risk": "层级反转不足"}},
                "sensitive_topic_policy": "只写制度和证据，不写猎奇伤害。",
            },
            ensure_ascii=False,
        ),
    )
    write(
        story / "beat-bible.json",
        json.dumps(
            {
                "pipeline_mode": "production",
                "target_length": {"min": 10000, "max": 18000},
                "rhythm_contract": rhythm_contract(),
                "beats": [
                    {
                        "beat_id": "beat-01",
                        "target_chars": 3000,
                        "scene_location": "客厅",
                        "character_goal": "拿到信托文件",
                        "conflict_action": "父亲按住文件",
                        "information_gap": "哥哥身份",
                        "emotion_debt_balance": "被忽视多年",
                        "chapter_end_hook": "门后是谁",
                        "paywall_card": True,
                        "forbidden_summary": ["不能写成解释段"],
                    },
                    {
                        "beat_id": "beat-02",
                        "target_chars": 3500,
                        "scene_location": "律所",
                        "character_goal": "验证录音",
                        "conflict_action": "哥哥抢走档案",
                        "information_gap": "遗嘱第二页",
                        "emotion_debt_balance": "被替代多年",
                        "chapter_end_hook": "真名出现",
                        "paywall_card": True,
                        "forbidden_summary": ["不能一次讲完真相"],
                    },
                    {
                        "beat_id": "beat-03",
                        "target_chars": 4000,
                        "scene_location": "礼堂",
                        "character_goal": "公开证据",
                        "conflict_action": "父亲夺话筒",
                        "information_gap": "谁安排失踪",
                        "emotion_debt_balance": "现场偿还",
                        "chapter_end_hook": "录音播放",
                        "paywall_card": True,
                        "forbidden_summary": ["不能靠旁白释放情绪"],
                    },
                ],
            },
            ensure_ascii=False,
        ),
    )
    chunks = split_story_text(final_text)
    for index, chunk in enumerate(chunks, start=1):
        scene_id = f"scene-{index:02d}"
        length = count_nonspace(chunk)
        write(
            story / "scene-cards" / f"{scene_id}.json",
            json.dumps(
                {
                    "scene_id": scene_id,
                    "beat_id": f"beat-{min(3, ((index - 1) // 4) + 1):02d}",
                    "target_chars_min": max(500, length - 30),
                    "target_chars_max": min(1200, length + 30),
                    "location": "客厅",
                    "time": f"第{index}场",
                    "pov": "first_person",
                    "characters": ["闻夏", "父亲", "母亲", "周律师"],
                    "character_goal": "拿到信托文件",
                    "opposition_goal": "阻止她开门",
                    "conflict_action": "父亲按住文件",
                    "information_gap": "哥哥身份",
                    "emotional_debt_delta": "被忽视的旧债加一",
                    "payoff_or_hook": "门后传来哥哥名字",
                    "chapter_end_hook": "门后是谁",
                    "paywall_card": index in {1, 5, 9},
                    "rhythm_job": "生活动作与呼吸留白",
                    "must_include": ["遗嘱", "录音笔"],
                    "must_not_write_as_exposition": ["不能用旁白解释哥哥身份"],
                },
                ensure_ascii=False,
            ),
        )
        write(story / "draft-scenes" / f"{scene_id}.md", chunk)
    draft_text = "\n\n".join(chunk.strip() for chunk in chunks) + "\n"
    final_direct = direct_submission_final(chunks)
    write(story / "draft.md", draft_text)
    write(
        story / "review.md",
        "# 审校报告\n\n```yaml\ngate_status: pass\ncritical_failures: []\nimportant_failures: []\n```\n",
    )
    write(story / "quality-report.json", json.dumps(production_quality_report(final_text=final_direct), ensure_ascii=False))
    write(story / "diff.md", "# diff\n")
    for name in ["platform", "emotion", "style", "logic"]:
        write(story / "evaluation" / f"{name}.json", json.dumps({"status": "pass", "score": 8, "evidence": [f"{name} 已用正文证据核验"]}, ensure_ascii=False))
    write(story / "final.md", final_direct)
    write(story / "craft-notes.md", "# craft\n")
    write(story / "tomato-submission.md", submission_with_paywall_map(4))
    chapter_rows = ["| 章 | 字数 | 本章钩子 |", "|---|---:|---|"]
    for index, chunk in enumerate(chunks, start=1):
        write(story / "final-chapters" / f"ch{index:02d}.md", chunk)
        hook = "-" if hookless else f"她问：“第{index + 1}扇门后是谁？”"
        chapter_rows.append(f"| {index:02d} | {count_nonspace(chunk)} | {hook} |")
    write(story / "final-chapters" / "_chapters-map.md", "\n".join(chapter_rows) + "\n")
    report = production_quality_report(final_text=final_direct, chapter_count=len(chunks), hook_coverage=0 if hookless else 1.0, paywall_actual=6)
    write(story / "quality-report.json", json.dumps(report, ensure_ascii=False))
    write(
        story / "story.yaml",
        "slug: story\npipeline_mode: production\ntarget_platform: tomato\ngenre: family_ethics\nstatus: final\nquality_gate:\n  gate_status: pass\n",
    )


def test_production_validator_rejects_short_final_even_when_report_says_pass(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(5000))

    result = run_script("validate-production-story.py", "--story", story, "--phase", "7", "--mode", "production")

    assert result.returncode != 0
    assert "target_length" in result.stderr
    assert "self-reports pass" in result.stderr


def test_production_validator_rejects_missing_chapter_hooks(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500), hookless=True)

    result = run_script("validate-production-story.py", "--story", story, "--phase", "7", "--mode", "production")

    assert result.returncode != 0
    assert "chapter_hooks" in result.stderr


def test_production_validator_rejects_final_without_opening_guide(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500))
    final_text = (story / "final.md").read_text(encoding="utf-8")
    final_text = re.sub(r"\n\n导语：.*?\n\n## 第 1 章", "\n\n## 第 1 章", final_text, flags=re.DOTALL)
    write(story / "final.md", final_text)
    report = json.loads((story / "quality-report.json").read_text(encoding="utf-8"))
    report["machine_metrics"]["target_length"]["actual"] = count_nonspace(final_text)
    write(story / "quality-report.json", json.dumps(report, ensure_ascii=False))

    result = run_script("validate-production-story.py", "--story", story, "--phase", "7", "--mode", "production")

    assert result.returncode != 0
    assert "opening_guide" in result.stderr


def test_production_validator_rejects_multi_sentence_paragraphs(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500))
    final_text = (story / "final.md").read_text(encoding="utf-8")
    final_text = final_text.replace("导语：闻夏被家人压在客厅里签退让协议时，门外忽然送来一份遗嘱。", "导语：闻夏被家人压在客厅里签退让协议时，门外忽然送来一份遗嘱。" + "她没有哭，只是站在门边望着那些想要逼她签字的人。" * 6)
    write(story / "final.md", final_text)
    report = json.loads((story / "quality-report.json").read_text(encoding="utf-8"))
    report["machine_metrics"]["target_length"]["actual"] = count_nonspace(final_text)
    write(story / "quality-report.json", json.dumps(report, ensure_ascii=False))

    result = run_script("validate-production-story.py", "--story", story, "--phase", "7", "--mode", "production")

    assert result.returncode != 0
    assert "mobile_paragraphs" in result.stderr


def test_production_validator_rejects_missing_direct_submission_paywall_map(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500))
    write(story / "tomato-submission.md", "# submission\n\n## 简介\n\n闻夏拿到遗嘱后开始反击。\n")

    result = run_script("validate-production-story.py", "--story", story, "--phase", "7", "--mode", "production")

    assert result.returncode != 0
    assert "submission_paywall_map" in result.stderr


def test_production_validator_rejects_visible_paywall_labels_in_final(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500))
    final_text = (story / "final.md").read_text(encoding="utf-8") + "\n\n【付费节点】这里不能出现在直接投稿版正文。\n"
    write(story / "final.md", final_text)
    report = json.loads((story / "quality-report.json").read_text(encoding="utf-8"))
    report["machine_metrics"]["target_length"]["actual"] = count_nonspace(final_text)
    write(story / "quality-report.json", json.dumps(report, ensure_ascii=False))

    result = run_script("validate-production-story.py", "--story", story, "--phase", "7", "--mode", "production")

    assert result.returncode != 0
    assert "visible_paywall_labels" in result.stderr


def test_production_validator_rejects_source_overlap(tmp_path):
    story = tmp_path / "story"
    final_text = make_story_text(10500)
    add_common_production_artifacts(story, final_text, source_text=final_text)

    result = run_script("validate-production-story.py", "--story", story, "--phase", "7", "--mode", "production")

    assert result.returncode != 0
    assert "source_overlap" in result.stderr


def test_production_validator_fails_closed_without_source(tmp_path):
    # source.md is gitignored, so a checkout without it must not report "no overlap".
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500))
    (story / "source.md").unlink()

    result = run_script("validate-production-story.py", "--story", story, "--phase", "7", "--mode", "production")

    assert result.returncode != 0
    assert "source.md missing" in result.stderr


def test_production_validator_rejects_empty_quality_report_metrics(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500))
    report = production_quality_report()
    report["machine_metrics"] = {}
    report["evidence"] = []
    write(story / "quality-report.json", json.dumps(report, ensure_ascii=False))

    result = run_script("validate-production-story.py", "--story", story, "--phase", "7", "--mode", "production")

    assert result.returncode != 0
    assert "machine_metrics missing sections" in result.stderr
    assert "pass gate requires non-empty evidence" in result.stderr


def test_production_validator_rejects_pass_evaluation_without_evidence(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500))
    write(story / "evaluation" / "platform.json", json.dumps({"status": "pass", "score": 8}, ensure_ascii=False))

    result = run_script("validate-production-story.py", "--story", story, "--phase", "7", "--mode", "production")

    assert result.returncode != 0
    assert "evaluation/platform.json pass status requires non-empty evidence list" in result.stderr


def test_production_validator_rejects_placeholder_evidence(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500))
    report = production_quality_report(final_text=(story / "draft.md").read_text(encoding="utf-8"))
    report["evidence"] = ["platform evidence", "emotion evidence"]
    write(story / "quality-report.json", json.dumps(report, ensure_ascii=False))
    write(story / "evaluation" / "style.json", json.dumps({"status": "pass", "score": 8, "evidence": ["style evidence"]}, ensure_ascii=False))

    result = run_script("validate-production-story.py", "--story", story, "--phase", "7", "--mode", "production")

    assert result.returncode != 0
    assert "placeholder evidence" in result.stderr


def test_production_validator_rejects_quality_report_metric_drift(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500))
    report = json.loads((story / "quality-report.json").read_text(encoding="utf-8"))
    report["machine_metrics"]["target_length"]["actual"] = 42
    write(story / "quality-report.json", json.dumps(report, ensure_ascii=False))

    result = run_script("validate-production-story.py", "--story", story, "--phase", "7", "--mode", "production")

    assert result.returncode != 0
    assert "target_length.actual does not match machine recompute" in result.stderr


def test_production_validator_rejects_scene_outside_card_range(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500))
    card_path = story / "scene-cards" / "scene-01.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["target_chars_min"] = 50
    card["target_chars_max"] = 100
    write(card_path, json.dumps(card, ensure_ascii=False))

    result = run_script("validate-production-story.py", "--story", story, "--phase", "5", "--mode", "production")

    assert result.returncode != 0
    assert "draft-scenes/scene-01.md length" in result.stderr


def test_production_validator_rejects_draft_not_joined_scenes(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500))
    write(story / "draft.md", (story / "draft.md").read_text(encoding="utf-8") + "\n额外尾巴。\n")

    result = run_script("validate-production-story.py", "--story", story, "--phase", "5", "--mode", "production")

    assert result.returncode != 0
    assert "draft.md must equal draft-scenes" in result.stderr


def test_production_validator_rejects_repetitive_sentence_skeletons(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_repetitive_story_text(10500))

    result = run_script("validate-production-story.py", "--story", story, "--phase", "5", "--mode", "production")

    assert result.returncode != 0
    assert "semantic_repetition" in result.stderr


def test_production_validator_rejects_mock_final_without_fixture_status(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500))
    write(
        story / "story.yaml",
        """slug: story
pipeline_mode: production
target_platform: tomato
genre: family_ethics
status: final
quality_gate:
  gate_status: pass
automation:
  runner: mock
  provider: mock
""",
    )

    result = run_script("validate-production-story.py", "--story", story, "--phase", "7", "--mode", "production")

    assert result.returncode != 0
    assert "mock runner output cannot be marked as production final" in result.stderr


def test_production_validator_rejects_incomplete_feedback_learning(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500))
    write(story / "feedback-learning.json", json.dumps({"story_slug": "story", "quality_scores": {"platform": 8}}, ensure_ascii=False))

    result = run_script("validate-production-story.py", "--story", story, "--phase", "8", "--mode", "production")

    assert result.returncode != 0
    assert "feedback-learning.json pipeline_mode" in result.stderr
    assert "quality_scores missing" in result.stderr


def test_production_validator_rejects_summary_only_beat_bible(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500))
    write(
        story / "beat-bible.json",
        json.dumps(
            {
                "pipeline_mode": "production",
                "target_length": {"min": 10000, "max": 18000},
                "rhythm_contract": rhythm_contract(),
                "beats": [{"beat_id": "beat-01", "paywall_card": True}],
            },
            ensure_ascii=False,
        ),
    )

    result = run_script("validate-production-story.py", "--story", story, "--phase", "4", "--mode", "production")

    assert result.returncode != 0
    assert "beat-bible.json beats[1] missing required keys" in result.stderr
    assert "target_chars" in result.stderr


def test_production_validator_rejects_thin_scene_card(tmp_path):
    story = tmp_path / "story"
    add_common_production_artifacts(story, make_story_text(10500))
    write(
        story / "scene-cards" / "scene-01.json",
        json.dumps(
            {
                "scene_id": "scene-01",
                "beat_id": "beat-01",
                "target_chars_min": 800,
                "target_chars_max": 1200,
                "location": "客厅",
                "character_goal": "拿文件",
                "opposition_goal": "阻止",
                "conflict_action": "父亲按住文件",
                "information_gap": "哥哥身份",
                "chapter_end_hook": "门后是谁",
                "paywall_card": True,
            },
            ensure_ascii=False,
        ),
    )

    result = run_script("validate-production-story.py", "--story", story, "--phase", "4", "--mode", "production")

    assert result.returncode != 0
    assert "scene-cards/scene-01.json missing required keys" in result.stderr
    assert "must_include" in result.stderr


def write_bundle(path, files):
    blocks = []
    for rel, content in files.items():
        blocks.append(f"<<<FILE: {rel}>>>\n{content.rstrip()}\n<<<END FILE>>>\n")
    write(path, "\n".join(blocks))


def test_production_mock_runner_completes_8_phase_pipeline(tmp_path):
    story = tmp_path / "mock_production_story"
    write(story / "source.md", "这是一篇合成测试原文。")
    fixtures = tmp_path / "fixtures"
    final_text = make_story_text(10500)
    chapter_map = "| 章 | 字数 | 本章钩子 |\n|---|---:|---|\n"
    chunks = split_story_text(final_text)
    direct_final_text = direct_submission_final(chunks)
    phase7_files = {
        "final.md": direct_final_text,
        "craft-notes.md": "# craft\n",
        "tomato-submission.md": "# 投稿包\n\n## 标题A\n高考前遗嘱让我找回失踪哥哥\n\n" + submission_with_paywall_map(4),
        "story.yaml": "slug: mock_production_story\npipeline_mode: production\ntarget_platform: tomato\ngenre: family_ethics\nstatus: test_fixture\nquality_gate:\n  gate_status: pass\n",
    }
    for index, chapter in enumerate(chunks, start=1):
        phase7_files[f"final-chapters/ch{index:02d}.md"] = chapter
        chapter_map += f"| {index:02d} | {count_nonspace(chapter)} | 她问：“第{index}扇门后是谁？” |\n"
    phase7_files["final-chapters/_chapters-map.md"] = chapter_map

    write_bundle(fixtures / "phase1.bundle.txt", {"market-brief.json": json.dumps({"pipeline_mode": "production", "target_platform": "tomato", "target_length": {"min": 10000, "max": 18000}}, ensure_ascii=False)})
    write_bundle(
        fixtures / "phase2.bundle.txt",
        {
            "story-brief.json": json.dumps(
                {
                    "source_title": "合成测试原文",
                    "genre": "family_ethics",
                    "hook_type": "H1",
                    "title_formula": "T1",
                    "reversal_mechanisms": ["M6"],
                    "source_length_chars": 10,
                    "reader_promise": "读者看主角拿回真相。",
                    "emotional_debts": ["被隐瞒"],
                    "payoff_pattern": "公开证据反杀。",
                    "forbidden_to_change": ["规则回旋"],
                    "replaceable_assets": ["遗嘱"],
                },
                ensure_ascii=False,
            ),
            "dissection.md": "# dissection\n",
            "analysis/beat-sheet.md": "# beat\n",
            "analysis/style-dna.md": "# style\n",
            "analysis/soul-contract.md": "# soul\n",
            "analysis/reader-engine.md": "# reader\n",
            "analysis/tension-ledger.md": "# tension\n",
        },
    )
    write_bundle(
        fixtures / "phase3.bundle.txt",
        {
            "adaptation.md": "# adaptation\n",
            "adaptation-room.json": json.dumps(
                {
                    "selected_candidate": "A",
                    "candidates": [
                        {"id": "A", "premise": "遗嘱触发谜题", "freshness_score": 8.6, "fidelity_score": 8.8, "tomato_score": 8.7, "logic_score": 8.8, "risks": []},
                        {"id": "B", "premise": "审计触发谜题", "freshness_score": 8.6, "fidelity_score": 8.6, "tomato_score": 8.6, "logic_score": 8.6, "risks": []},
                        {"id": "C", "premise": "押金单触发谜题", "freshness_score": 8.6, "fidelity_score": 8.6, "tomato_score": 8.6, "logic_score": 8.6, "risks": []},
                    ],
                    "replacement_map": {"原文载体": "遗嘱"},
                    "mechanism_preservation": {"M6": {"carrier": "遗嘱第二页"}},
                    "sensitive_topic_policy": "不猎奇。",
                },
                ensure_ascii=False,
            ),
        },
    )
    write_bundle(
        fixtures / "phase4.bundle.txt",
        {
            "beat-bible.json": json.dumps(
                {
                    "pipeline_mode": "production",
                    "target_length": {"min": 10000, "max": 18000},
                    "rhythm_contract": rhythm_contract(),
                "beats": [
                        {
                            "beat_id": "b1",
                            "target_chars": 3000,
                            "scene_location": "客厅",
                            "character_goal": "找人",
                            "conflict_action": "父亲按住文件",
                            "information_gap": "门后",
                            "emotion_debt_balance": "被隐瞒多年",
                            "chapter_end_hook": "门开了",
                            "paywall_card": True,
                            "forbidden_summary": ["不能摘要化"],
                        },
                        {
                            "beat_id": "b2",
                            "target_chars": 3500,
                            "scene_location": "律所",
                            "character_goal": "验证证据",
                            "conflict_action": "哥哥夺走档案",
                            "information_gap": "第二页",
                            "emotion_debt_balance": "被替代多年",
                            "chapter_end_hook": "真名出现",
                            "paywall_card": True,
                            "forbidden_summary": ["不能解释完"],
                        },
                        {
                            "beat_id": "b3",
                            "target_chars": 4000,
                            "scene_location": "礼堂",
                            "character_goal": "公开证据",
                            "conflict_action": "父亲夺话筒",
                            "information_gap": "谁安排失踪",
                            "emotion_debt_balance": "现场偿还",
                            "chapter_end_hook": "录音播放",
                            "paywall_card": True,
                            "forbidden_summary": ["不能旁白释放"],
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            **{
                f"scene-cards/scene-{index:02d}.json": json.dumps(
                    {
                        "scene_id": f"scene-{index:02d}",
                        "beat_id": "b1",
                        "target_chars_min": max(500, count_nonspace(chunk) - 30),
                        "target_chars_max": min(1200, count_nonspace(chunk) + 30),
                        "location": "客厅",
                        "time": f"第{index}场",
                        "pov": "first_person",
                        "characters": ["闻夏", "父亲"],
                        "character_goal": "找人",
                        "opposition_goal": "阻止",
                        "conflict_action": "父亲按住文件",
                        "information_gap": "门后",
                        "emotional_debt_delta": "旧债加一",
                        "payoff_or_hook": "门开了",
                        "chapter_end_hook": "门开了",
                        "paywall_card": index in {1, 5, 9},
                        "rhythm_job": "生活动作与呼吸留白",
                        "must_include": ["遗嘱"],
                        "must_not_write_as_exposition": ["不能摘要化"],
                    },
                    ensure_ascii=False,
                )
                for index, chunk in enumerate(chunks, start=1)
            },
        },
    )
    draft_text = "\n\n".join(chunk.strip() for chunk in chunks) + "\n"
    write_bundle(
        fixtures / "phase5.bundle.txt",
        {
            **{f"draft-scenes/scene-{index:02d}.md": chunk for index, chunk in enumerate(chunks, start=1)},
            "draft.md": draft_text,
        },
    )
    write_bundle(
        fixtures / "phase6.bundle.txt",
        {
            "review.md": "# 审校报告\n\n```yaml\ngate_status: pass\ncritical_failures: []\nimportant_failures: []\n```\n",
            "quality-report.json": json.dumps(
                production_quality_report(final_text=draft_text, chapter_count=len(chunks), hook_coverage=1.0, paywall_actual=6),
                ensure_ascii=False,
            ),
            "diff.md": "# diff\n",
            "evaluation/platform.json": json.dumps({"status": "pass", "score": 8, "evidence": ["章末钩覆盖"]}, ensure_ascii=False),
            "evaluation/emotion.json": json.dumps({"status": "pass", "score": 8, "evidence": ["情绪债现场偿还"]}, ensure_ascii=False),
            "evaluation/style.json": json.dumps({"status": "pass", "score": 8, "evidence": ["动作密度达标"]}, ensure_ascii=False),
            "evaluation/logic.json": json.dumps({"status": "pass", "score": 8, "evidence": ["证据链闭合"]}, ensure_ascii=False),
        },
    )
    write_bundle(fixtures / "phase7.bundle.txt", phase7_files)
    write_bundle(
        fixtures / "phase8.bundle.txt",
        {
            "feedback-learning.json": json.dumps(
                {
                    "story_slug": "mock_production_story",
                    "pipeline_mode": "production",
                    "failure_types": [],
                    "successful_hooks": ["遗嘱触发失踪哥哥"],
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
        "--run-id",
        "prod_mock",
        "--no-human-gates",
        env={"STORYFORGE_MOCK_FIXTURE_DIR": str(fixtures)},
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert (story / "feedback-learning.json").exists()
    manifest = json.loads((story / "runs" / "prod_mock" / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "production"
    summary = (story / "runs" / "prod_mock" / "execution-summary.md").read_text(encoding="utf-8")
    assert "| 8 | completed |" in summary
