#!/usr/bin/env python3
"""Generate production draft scenes in smaller Codex batches.

The normal phase-5 prompt asks the model to emit every scene plus draft.md in
one response. That is brittle for 10k+ Chinese short fiction: slow responses
fail late, and a single over-cranked rhythm choice can infect the whole draft.
This utility keeps the same scene cards, but writes a few scenes per call and
assembles draft.md locally after every expected scene exists.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rhythm_metrics import rhythm_profile  # noqa: E402
from scene_context import LEDGER, context_for_batch, scene_order  # noqa: E402
from storyforge_lib import StagedStory, story_write_lock, now_stamp, parse_artifact_bundle, write_json, write_text  # noqa: E402
from repairs import repair_fragmentation_and_soft_words  # noqa: E402


def count_nonspace(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def adaptive_line_contract(source_profile: Dict[str, Any]) -> Dict[str, float]:
    source_avg = float(source_profile.get("avg_line_chars") or 15.0)
    avg_min = max(11.0, round(source_avg * 0.78, 2))
    avg_max = min(32.0, round(max(18.0, source_avg * 1.22), 2))
    return {
        "avg_min": avg_min,
        "avg_max": avg_max,
        "very_short_max": 0.30,
    }


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def chunks(items: List[Path], size: int) -> Iterable[List[Path]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def relative(path: Path) -> str:
    return os.path.relpath(path, ROOT)


def prompt_for_batch(story: Path, batch: List[Path], batch_index: int, batch_total: int, *, context_max_chars: int = 16000) -> str:
    continuity = context_for_batch(story, batch, max_chars=context_max_chars)
    scene_contract = (ROOT / "prompts" / "production" / "scene-writer.md").read_text(encoding="utf-8")
    style_dna = (story / "analysis" / "style-dna.md").read_text(encoding="utf-8")
    bible = load_json(story / "beat-bible.json")
    source_profile = rhythm_profile((story / "source.md").read_text(encoding="utf-8"))
    line_contract = adaptive_line_contract(source_profile)
    rhythm_contract = bible.get("rhythm_contract", {})
    chapters = bible.get("chapters", [])
    target_length = bible.get("target_length", {})
    cards = []
    for path in batch:
        card = load_json(path)
        min_chars = int(card.get("target_chars_min", 0) or 0)
        max_chars = int(card.get("target_chars_max", 0) or 0)
        if min_chars and max_chars:
            card = dict(card)
            card["visual_line_count_range"] = [
                max(1, math.ceil(min_chars / line_contract["avg_max"])),
                max(1, math.floor(max_chars / line_contract["avg_min"])),
            ]
            card["avg_visual_line_chars_required"] = [line_contract["avg_min"], line_contract["avg_max"]]
            card["very_short_line_rate_lte_8_max"] = line_contract["very_short_max"]
        cards.append(card)
    required = [f"draft-scenes/{card['scene_id']}.md" for card in cards]
    return "\n".join(
        [
            "# StoryForge production Phase 5 split scene batch",
            "",
            "Role: Scene Writer",
            "",
            f"Batch: {batch_index}/{batch_total}",
            "",
            "你正在执行 StoryForge production 自动产线的分批正文生成。必须只输出 artifact bundle 文件块。",
            "不要调用工具、不要修改文件系统、不要说“已写入文件”。唯一交付方式是下面的 artifact bundle。",
            "",
            "## Output Protocol",
            "",
            "每个产物必须使用以下格式：",
            "",
            "<<<FILE: draft-scenes/scene-NN.md>>>",
            "正文",
            "<<<END FILE>>>",
            "",
            "禁止输出 draft.md；脚本会在所有 scene 达标后自动拼接。",
            "禁止输出解释、质检报告、Markdown 表格或未列入 Required Outputs 的文件。",
            "",
            "## Required Outputs",
            "",
            *[f"- {item}" for item in required],
            "",
            "## Hard Rhythm Targets",
            "",
            f"- source_profile: {json.dumps(source_profile, ensure_ascii=False)}",
            f"- beat_bible.rhythm_contract: {json.dumps(rhythm_contract, ensure_ascii=False)}",
            "- 这是一条双向约束：不能拖成长段，也不能碎成诗行。",
            f"- 目标均行长贴近原文：每场平均可视行长必须在 {line_contract['avg_min']}-{line_contract['avg_max']} 字之间，不要长期低于源文下限。",
            "- 单场可视行数必须按 scene card 的 visual_line_count_range 控制；长句源文不要被切成短行源文。",
            "- 把相邻的动作+反应、台词+小动作合成完整短句；不要把一个完整句子拆成三四行。",
            "- 禁止在行尾使用两个空格制造 Markdown 硬换行。",
            "- 每个非空行都必须是一个完整可读的移动端段落，不得让“纸角很硬 / 离婚协议 / 我眨眼”这类碎片单独成行。",
            f"- 8 字以内极短行不得超过 {line_contract['very_short_max']:.0%}。",
            "- 每场必须有低压承接：弹幕/吐槽/慢半拍反应/生活动作/证据动作/留白至少一种。",
            "- 问号和逼问不能超量；不要连续写‘逼问、黑屏、崩溃、宣告、全场死寂’。",
            "- 不够字只补有效戏剧信息：台词交锋、证据变化、动作反制、弹幕误导；不要补解释、情绪总结、流程说明。",
            "- 每个 scene 必须落在自己的 target_chars_min/target_chars_max 内，按非空白字符计数。",
            "- 输出前逐场自检：非空白字数在区间内，视觉行数在 scene card 的 visual_line_count_range 内。",
            "",
            "## Scene Writer Contract",
            "",
            scene_contract,
            "",
            "## Style DNA",
            "",
            style_dna,
            "",
            "## Beat Bible Global Context",
            "",
            json.dumps(
                {
                    "title": bible.get("title"),
                    "genre": bible.get("genre"),
                    "target_length": target_length,
                    "chapters": [] if (story / LEDGER).exists() else chapters,
                    "mechanisms": [] if (story / LEDGER).exists() else bible.get("mechanisms", []),
                },
                ensure_ascii=False,
                indent=2,
            ),
            "",
            "## Position-scoped Continuity (plans are not facts)",
            continuity,
            "",
            "## Current Batch Scene Cards",
            "",
            json.dumps(cards, ensure_ascii=False, indent=2),
            "",
            "## Final Self Check Before Output",
            "",
            "- 每个 scene 有行动、信息变化、微钩。",
            "- 没有为了凑字写无效心理独白或重复说明。",
            "- 弹幕/吐槽没有被全部替换成角色逼问。",
            "- 行长像源文：短、清楚、但不是机械碎句。",
            "",
        ]
    )


def run_codex(prompt: str, output_path: Path, model: str, effort: str, timeout: int) -> subprocess.CompletedProcess[str]:
    cmd = [
        "codex",
        "exec",
        "--model",
        model,
        "-c",
        f"model_reasoning_effort={json.dumps(effort)}",
        "--sandbox",
        "read-only",
        "--cd",
        str(ROOT),
        "--skip-git-repo-check",
        "--output-last-message",
        str(output_path),
        "-",
    ]
    return subprocess.run(cmd, cwd=ROOT, input=prompt, text=True, capture_output=True, timeout=timeout)


def repair_prompt_for_batch(
    story: Path,
    batch: List[Path],
    expected: List[str],
    failures: List[str],
    previous_text: str,
    attempt: int,
    *, context_max_chars: int = 16000,
) -> str:
    cards = []
    source_profile = rhythm_profile((story / "source.md").read_text(encoding="utf-8"))
    line_contract = adaptive_line_contract(source_profile)
    for path in batch:
        card = load_json(path)
        min_chars = int(card.get("target_chars_min", 0) or 0)
        max_chars = int(card.get("target_chars_max", 0) or 0)
        card = dict(card)
        card["visual_line_count_range"] = [
            max(1, math.ceil(min_chars / line_contract["avg_max"])),
            max(1, math.floor(max_chars / line_contract["avg_min"])),
        ]
        card["avg_visual_line_chars_required"] = [line_contract["avg_min"], line_contract["avg_max"]]
        card["very_short_line_rate_lte_8_max"] = line_contract["very_short_max"]
        cards.append(card)
    style_dna = (story / "analysis" / "style-dna.md").read_text(encoding="utf-8")
    return "\n".join(
        [
            "# StoryForge split scene repair",
            "",
            f"Repair attempt: {attempt}",
            "",
            "上一版没有通过机器验收。必须重写完整 artifact bundle,只输出 Required Outputs。",
            "不要调用工具、不要修改文件系统、不要说“已重写文件”。唯一交付方式是 artifact bundle。",
            "",
            "## Required Outputs",
            "",
            *[f"- {item}" for item in expected],
            "",
            "## Machine Failures To Fix",
            "",
            *[f"- {item}" for item in failures],
            "",
            "## Rewrite Rules",
            "",
            "- 保留 scene card 的核心事件和章尾钩,不要新增新事件。",
            "- 删除冗余氛围、重复确认、重复追问、无信息心理总结。",
            "- 非空白字数必须落在 scene card 区间内。",
            f"- 平均可视行长 {line_contract['avg_min']}-{line_contract['avg_max']} 字；视觉行数必须落在 visual_line_count_range 内。",
            "- 禁止 3-8 字碎片连续成行；把动作+反应、台词+动作合成完整短句。",
            "- 禁止行尾两个空格硬换行。",
            "- 保留弹幕/吐槽/慢半拍反应,但不要靠增加短行制造节奏。",
            "",
            "## Scene Cards",
            "",
            json.dumps(cards, ensure_ascii=False, indent=2),
            "",
            "## Style DNA",
            "",
            style_dna,
            "",
            "## Position-scoped Continuity (failed draft is not accepted evidence)",
            context_for_batch(story, batch, max_chars=context_max_chars),
            "",
            "## Previous Failed Draft",
            "",
            previous_text,
            "",
        ]
    )


def write_batch_outputs(story: Path, expected: List[str], bundle_text: str) -> List[str]:
    try:
        parsed = parse_artifact_bundle(bundle_text)
    except ValueError:
        parsed = {}
        for rel in expected:
            pattern = re.compile(
                rf"^(?:\*\*{re.escape(rel)}\*\*|\[{re.escape(rel)}\]|{re.escape(rel)})\s*\n```(?:md|markdown)?\s*\n(?P<content>.*?)\n```\s*$",
                re.MULTILINE | re.DOTALL,
            )
            match = pattern.search(bundle_text)
            if match:
                parsed[rel] = match.group("content").rstrip() + "\n"
                continue
            unclosed = re.compile(
                rf"^<<<FILE:\s*{re.escape(rel)}\s*>>>\s*\n(?P<content>.*?)\s*$",
                re.MULTILINE | re.DOTALL,
            ).search(bundle_text)
            if unclosed:
                parsed[rel] = unclosed.group("content").rstrip() + "\n"
                continue
            xmlish = re.compile(
                rf"<artifact\s+path=[\"']{re.escape(rel)}[\"']\s*>\s*(?P<content>.*?)\s*</artifact>",
                re.MULTILINE | re.DOTALL,
            ).search(bundle_text)
            if xmlish:
                parsed[rel] = xmlish.group("content").rstrip() + "\n"
                continue
            stripped = bundle_text.strip()
            bracket = f"[{rel}]"
            bold = f"**{rel}**"
            banner = f"=== {rel} ==="
            dash_banner = f"--- {rel} ---"
            if stripped.startswith(bold):
                content = stripped[len(bold) :].lstrip()
                if content:
                    parsed[rel] = content.rstrip() + "\n"
                continue
            if stripped.startswith(bracket):
                content = stripped[len(bracket) :].lstrip()
                if content:
                    parsed[rel] = content.rstrip() + "\n"
                continue
            if stripped.startswith(banner):
                content = stripped[len(banner) :].lstrip()
                if content:
                    parsed[rel] = content.rstrip() + "\n"
                continue
            if stripped.startswith(dash_banner):
                content = stripped[len(dash_banner) :].lstrip()
                if content:
                    parsed[rel] = content.rstrip() + "\n"
                continue
            if stripped.startswith(rel):
                content = stripped[len(rel) :].lstrip()
                if content:
                    parsed[rel] = content.rstrip() + "\n"
        if not parsed:
            raise
    missing = [rel for rel in expected if rel not in parsed]
    if missing:
        raise ValueError("missing expected scene outputs: " + ", ".join(missing))
    extra = sorted(path for path in parsed if path not in expected)
    if extra:
        raise ValueError("unexpected outputs in split scene batch: " + ", ".join(extra))
    written = []
    for rel in expected:
        target = story / rel
        write_text(target, parsed[rel].rstrip() + "\n")
        written.append(rel)
    return written


def validate_scene_batch(story: Path, card_paths: List[Path], written: List[str]) -> List[str]:
    failures: List[str] = []
    source_profile = rhythm_profile((story / "source.md").read_text(encoding="utf-8"))
    line_contract = adaptive_line_contract(source_profile)
    card_by_rel = {}
    for card_path in card_paths:
        card = load_json(card_path)
        card_by_rel[f"draft-scenes/{card['scene_id']}.md"] = card
    for rel in written:
        card = card_by_rel.get(rel, {})
        text = (story / rel).read_text(encoding="utf-8")
        chars = count_nonspace(text)
        lo = int(card.get("target_chars_min", 0) or 0)
        hi = int(card.get("target_chars_max", 0) or 0)
        profile = rhythm_profile(text)
        avg_line = float(profile.get("avg_line_chars") or 0)
        very_short_units = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#") and count_nonspace(line) <= 8
        ]
        units = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        very_short_rate = len(very_short_units) / max(len(units), 1)
        required_avg = card.get("avg_visual_line_chars_required")
        if isinstance(required_avg, list) and len(required_avg) >= 2:
            avg_min = float(required_avg[0])
            avg_max = float(required_avg[1])
        else:
            avg_min = line_contract["avg_min"]
            avg_max = line_contract["avg_max"]
        very_short_max = float(card.get("very_short_line_rate_lte_8_max", line_contract["very_short_max"]))
        min_lines = math.ceil(lo / avg_max) if lo else 1
        max_lines = math.floor(hi / avg_min) if hi else 10**9
        if lo and chars < lo:
            failures.append(f"{rel} chars {chars} below min {lo}")
        if hi and chars > hi:
            failures.append(f"{rel} chars {chars} above max {hi}")
        if avg_line < avg_min:
            failures.append(f"{rel} avg_line_chars {avg_line:.2f} below {avg_min:.2f}; merge mechanical fragments")
        if avg_line > avg_max:
            failures.append(f"{rel} avg_line_chars {avg_line:.2f} above {avg_max:.2f}; tighten lines")
        if len(units) < min_lines or len(units) > max_lines:
            failures.append(f"{rel} visual lines {len(units)} outside {min_lines}-{max_lines}")
        if very_short_rate > very_short_max:
            failures.append(f"{rel} very_short_line_rate {very_short_rate:.3f} above {very_short_max:.2f}")
    return failures


def assemble_draft(story: Path, scene_cards: List[Path]) -> Dict[str, Any]:
    scene_texts = []
    scene_lengths = []
    for card_path in scene_cards:
        card = load_json(card_path)
        scene_id = str(card["scene_id"])
        scene_path = story / "draft-scenes" / f"{scene_id}.md"
        text = scene_path.read_text(encoding="utf-8").strip()
        chars = count_nonspace(text)
        scene_lengths.append(
            {
                "scene_id": scene_id,
                "chars": chars,
                "min": card.get("target_chars_min"),
                "max": card.get("target_chars_max"),
                "status": "pass" if card.get("target_chars_min", 0) <= chars <= card.get("target_chars_max", 10**9) else "fail",
            }
        )
        scene_texts.append(text)
    draft = "\n\n".join(scene_texts).strip() + "\n"
    write_text(story / "draft.md", draft)
    return {
        "draft_chars": count_nonspace(draft),
        "scene_lengths": scene_lengths,
    }


def check_blueprint_approval(story, args):
    """The split-scene entry point must honor the same reviewed blueprint."""
    if args.no_human_gates:
        return
    from approval_snapshots import require_approval
    if not args.approval_run_id or Path(args.approval_run_id).name != args.approval_run_id:
        raise ValueError("Use --approval-run-id for the explicitly approved pipeline run")
    approval_dir = story / "runs" / args.approval_run_id
    pending = load_json(approval_dir / "blueprint-pending.json")
    config = dict(pending["configuration"])
    config.update(runner="codex", model=args.model, effort=args.effort)
    require_approval(story, approval_dir, ROOT, argparse.Namespace(**config))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--story", required=True)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--approval-run-id", default="", help="pipeline run holding the reviewed blueprint snapshot")
    parser.add_argument("--no-human-gates", action="store_true", help="explicitly bypass blueprint review")
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--effort", default=os.environ.get("STORYFORGE_CODEX_REASONING_EFFORT", "medium"))
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--start-at", type=int, default=1, help="first scene number to generate")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--context-max-chars", type=int, default=16000, help="ledger context character budget (not model tokens)")
    args = parser.parse_args()

    story = Path(args.story)
    if not story.is_absolute():
        story = ROOT / story
    story = story.resolve()
    if args.run_id and (Path(args.run_id).name != args.run_id or args.run_id in {".", ".."}):
        raise ValueError("run ID must be a single directory name")
    run_id = args.run_id or f"scene_batches_{now_stamp().replace(' ', '_').replace(':', '')}"
    run_dir = story / "runs" / run_id
    # Own the same stable lock as the main pipeline, including approval checks.
    with story_write_lock(story):
        check_blueprint_approval(story, args)
        run_dir.mkdir(parents=True, exist_ok=True)
        with StagedStory(story, run_dir, 5) as staged:
            write_json(run_dir / "split-scene-report.json", {
                "run_id": run_id, "status": "staging", "candidate": str(staged.path),
                "started_at": now_stamp(), "batches": [],
            })
            try:
                manifest = generate_candidate(staged.path, story, run_dir, run_id, args)
                check_blueprint_approval(story, args)
                check_blueprint_approval(staged.path, args)
                manifest["status"] = "validated"
                manifest["attempt_backup"] = str(staged.path)
                write_json(run_dir / "split-scene-report.json", manifest)
                staged.publish()
            except (OSError, ValueError, subprocess.SubprocessError, SystemExit) as exc:
                report_path = run_dir / "split-scene-report.json"
                report = load_json(report_path) if report_path.exists() else {"run_id": run_id}
                report.update(status="failed", error=str(exc), candidate=str(staged.path), ended_at=now_stamp())
                write_json(report_path, report)
                raise
        manifest.update(status="success", ended_at=now_stamp())
        write_json(run_dir / "split-scene-report.json", manifest)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def generate_candidate(story, live_story, run_dir, run_id, args):
    """Generate and validate the whole replacement without mutating live artifacts."""
    check_blueprint_approval(story, args)
    if not (story / "beat-bible.json").exists():
        raise SystemExit("missing beat-bible.json; run phase 4 first")
    all_scene_cards = [story / "scene-cards" / f"{sid}.json" for sid in scene_order(story)]
    if not all_scene_cards:
        raise SystemExit("missing scene-cards")
    scene_cards = [
        path for path in all_scene_cards
        if int(re.search(r"scene-(\d+)", path.stem).group(1)) >= args.start_at
    ]
    if not scene_cards:
        raise SystemExit(f"no scene cards at or after scene {args.start_at}")
    if (story / LEDGER).exists() and args.force and args.start_at <= 1:
        raise SystemExit("--force would erase continuity evidence; retain reviewed drafts and regenerate selected scenes")
    if (story / "draft-scenes").exists() and args.force and args.start_at <= 1:
        shutil.rmtree(story / "draft-scenes")
    (story / "draft-scenes").mkdir(parents=True, exist_ok=True)

    manifest: Dict[str, Any] = {
        "story": relative(live_story),
        "run_id": run_id,
        "model": args.model,
        "effort": args.effort,
        "batch_size": args.batch_size,
        "started_at": now_stamp(),
        "batches": [],
    }
    effective_batch_size = 1 if (story / LEDGER).exists() else max(1, args.batch_size)
    manifest["effective_batch_size"] = effective_batch_size
    card_batches = list(chunks(scene_cards, effective_batch_size))
    for index, batch in enumerate(card_batches, start=1):
        cards = [load_json(path) for path in batch]
        expected = [f"draft-scenes/{card['scene_id']}.md" for card in cards]
        prompt = prompt_for_batch(story, batch, index, len(card_batches), context_max_chars=args.context_max_chars)
        if (story / LEDGER).exists():
            snapshot = json.loads(context_for_batch(story, batch, max_chars=args.context_max_chars))
            write_json(run_dir / "scene-context" / f"{cards[0]['scene_id']}.json", snapshot)
        prompt_path = run_dir / f"batch{index:02d}.prompt.md"
        out_path = run_dir / f"batch{index:02d}.codex.out"
        log_path = run_dir / f"batch{index:02d}.codex.log"
        write_text(prompt_path, prompt)
        batch_report = {
            "batch": index,
            "expected": expected,
        }
        written: List[str] = []
        scene_failures: List[str] = []
        current_prompt = prompt
        bundle_text = ""
        for attempt in range(0, args.retries + 1):
            suffix = "" if attempt == 0 else f".repair{attempt}"
            attempt_prompt_path = run_dir / f"batch{index:02d}{suffix}.prompt.md"
            attempt_out_path = run_dir / f"batch{index:02d}{suffix}.codex.out"
            attempt_log_path = run_dir / f"batch{index:02d}{suffix}.codex.log"
            write_text(attempt_prompt_path, current_prompt)
            check_blueprint_approval(live_story, args)
            check_blueprint_approval(story, args)
            completed = run_codex(current_prompt, attempt_out_path, args.model, args.effort, args.timeout)
            attempt_log_path.write_text((completed.stdout or "") + (completed.stderr or ""), encoding="utf-8")
            bundle_text = attempt_out_path.read_text(encoding="utf-8") if attempt_out_path.exists() else completed.stdout
            if completed.returncode != 0:
                batch_report["status"] = "failed"
                batch_report["returncode"] = completed.returncode
                batch_report["log_path"] = relative(attempt_log_path)
                manifest["batches"].append(batch_report)
                write_json(run_dir / "split-scene-report.json", manifest)
                raise SystemExit(f"codex failed for batch {index}: see {relative(attempt_log_path)}")
            try:
                written = write_batch_outputs(story, expected, bundle_text)
            except ValueError as exc:
                written = []
                scene_failures = [f"artifact_parse: {exc}"]
            else:
                repair_fragmentation_and_soft_words.run(story, scene_ids=[card["scene_id"] for card in cards])
                scene_failures = validate_scene_batch(story, batch, written)
            batch_report.setdefault("attempts", []).append(
                {
                    "attempt": attempt,
                    "status": "pass" if not scene_failures else "fail",
                    "output_path": relative(attempt_out_path),
                    "log_path": relative(attempt_log_path),
                    "failures": scene_failures,
                }
            )
            if not scene_failures:
                break
            if written:
                current_text = "\n\n".join((story / rel).read_text(encoding="utf-8") for rel in expected)
            else:
                current_text = bundle_text
            current_prompt = repair_prompt_for_batch(story, batch, expected, scene_failures, current_text, attempt + 1, context_max_chars=args.context_max_chars)
        if scene_failures:
            batch_report["status"] = "failed_validation"
            batch_report["failures"] = scene_failures
            batch_report["written"] = written
            manifest["batches"].append(batch_report)
            write_json(run_dir / "split-scene-report.json", manifest)
            raise SystemExit("scene batch failed validation:\n" + "\n".join(scene_failures))
        batch_report["status"] = "success"
        batch_report["written"] = written
        manifest["batches"].append(batch_report)
        write_json(run_dir / "split-scene-report.json", manifest)

    # Resume skips generation, never the final quality gate. Missing scenes fail
    # explicitly rather than allowing a partial draft to replace the live tree.
    expected_all = [f"draft-scenes/{load_json(path)['scene_id']}.md" for path in all_scene_cards]
    missing = [rel for rel in expected_all if not (story / rel).is_file()]
    failures = [f"missing scene: {rel}" for rel in missing]
    if not missing:
        failures.extend(validate_scene_batch(story, all_scene_cards, expected_all))
    if failures:
        manifest.update(status="failed_validation", failures=failures)
        write_json(run_dir / "split-scene-report.json", manifest)
        raise SystemExit("complete draft failed validation:\n" + "\n".join(failures))
    assembly = assemble_draft(story, all_scene_cards)
    manifest["assembly"] = assembly
    manifest["ended_at"] = now_stamp()
    return manifest


if __name__ == "__main__":
    raise SystemExit(main())
