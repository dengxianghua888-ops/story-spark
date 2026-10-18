#!/usr/bin/env python3
"""Deterministic normalizers for StoryForge production artifacts.

The normalizer only fixes mechanical contract drift before validation. It does
not relax validator thresholds and does not convert a failed quality gate into a
passing one.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from storyforge_lib import phase_for_role
from production_quality import count_nonspace, machine_evaluate, validate_story


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_score(value: Any) -> Any:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return value
    if 10 < value <= 100:
        return round(float(value) / 10, 2)
    return value


def _candidate_id(candidate: Dict[str, Any]) -> str:
    return str(candidate.get("id") or candidate.get("candidate_id") or candidate.get("name") or "").strip()


def normalize_phase3(story: Path) -> List[str]:
    path = story / "adaptation-room.json"
    if not path.exists():
        return []
    data = load_json(path)
    selected = data.get("selected_candidate")
    if isinstance(selected, dict):
        selected_id = _candidate_id(selected)
        if selected_id:
            data["selected_candidate"] = selected_id
            write_json(path, data)
            return ["selected_candidate_object_to_id"]
    return []


def normalize_phase4(story: Path) -> List[str]:
    path = story / "beat-bible.json"
    if not path.exists():
        return []
    data = load_json(path)
    changes: List[str] = []
    rhythm_contract = data.get("rhythm_contract")
    if isinstance(rhythm_contract, dict):
        avg_range = rhythm_contract.get("avg_visual_line_chars_range") or rhythm_contract.get("avg_visual_line_len_range")
        if isinstance(avg_range, list) and len(avg_range) >= 2 and "avg_visual_line_chars_range" not in rhythm_contract:
            rhythm_contract["avg_visual_line_chars_range"] = avg_range[:2]
            changes.append("rhythm_contract.avg_visual_line_len_range_alias")

        alias_ranges = [
            (
                "short_line_rate_range",
                "short_line_rate_lte_16_min",
                "short_line_rate_lte_16_max",
            ),
            (
                "direct_dialogue_line_rate_range",
                "direct_dialogue_line_rate_min",
                "direct_dialogue_line_rate_max",
            ),
            (
                "barrage_comment_line_rate_range",
                "barrage_line_rate_min",
                "barrage_line_rate_max",
            ),
            (
                "question_density_range_per_1000_chars",
                "question_mark_density_per_1000_chars_min",
                "question_mark_density_per_1000_chars_max",
            ),
        ]
        for alias, min_key, max_key in alias_ranges:
            value = rhythm_contract.get(alias)
            if isinstance(value, list) and len(value) >= 2:
                if min_key not in rhythm_contract:
                    rhythm_contract[min_key] = value[0]
                    changes.append(f"rhythm_contract.{alias}_to_{min_key}")
                if max_key not in rhythm_contract:
                    rhythm_contract[max_key] = value[1]
                    changes.append(f"rhythm_contract.{alias}_to_{max_key}")
    beats = data.get("beats")
    if isinstance(beats, list):
        for index, beat in enumerate(beats, start=1):
            if not isinstance(beat, dict):
                continue
            value = beat.get("forbidden_summary")
            if isinstance(value, str) and value.strip():
                beat["forbidden_summary"] = [value.strip()]
                changes.append(f"forbidden_summary_string_to_list:beats[{index}]")
    if changes:
        write_json(path, data)
    return changes


def _failure_item_to_string(item: Any) -> str:
    if isinstance(item, str):
        return item
    if item is None:
        return ""
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def normalize_failure_lists(report: Dict[str, Any]) -> List[str]:
    changes: List[str] = []
    for key in ["critical_failures", "important_failures"]:
        value = report.get(key)
        if not isinstance(value, list):
            continue
        normalized = [_failure_item_to_string(item) for item in value]
        if normalized != value:
            report[key] = normalized
            changes.append(f"{key}_stringified")
    return changes


def normalize_report_scores(report: Dict[str, Any]) -> List[str]:
    changes: List[str] = []
    scores = report.get("critic_scores")
    if isinstance(scores, dict):
        for key, value in list(scores.items()):
            normalized = normalize_score(value)
            if normalized != value:
                scores[key] = normalized
                changes.append(f"critic_scores.{key}_0_100_to_0_10")
    return changes


def sync_evaluation_scores(story: Path, report: Dict[str, Any]) -> List[str]:
    changes: List[str] = []
    scores = report.get("critic_scores") if isinstance(report.get("critic_scores"), dict) else {}
    evaluation_dir = story / "evaluation"
    for path in sorted(evaluation_dir.glob("*.json")):
        data = load_json(path)
        original = data.get("score")
        normalized = normalize_score(original)
        key = path.stem
        if key in scores and isinstance(scores[key], (int, float)) and not isinstance(scores[key], bool):
            normalized = scores[key]
        if normalized != original:
            data["score"] = normalized
            write_json(path, data)
            changes.append(f"evaluation/{path.name}.score_synced")
    return changes


def _yaml_list(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "[]"
    lines = [""]
    for item in items:
        text = str(item).replace("\n", " ").strip()
        escaped = text.replace('"', '\\"')
        lines.append(f'  - "{escaped}"')
    return "\n".join(lines)


def build_gate_block(report: Dict[str, Any]) -> str:
    gate = str(report.get("gate_status", "fail")).strip().lower() or "fail"
    critical = _yaml_list(report.get("critical_failures", []))
    important = _yaml_list(report.get("important_failures", []))
    return "\n".join(
        [
            "```yaml",
            f"gate_status: {gate}",
            f"critical_failures: {critical}",
            f"important_failures: {important}",
            "```",
            "",
        ]
    )


def strip_existing_gate_block(text: str) -> str:
    stripped = text.lstrip()
    if stripped.startswith("```"):
        match = re.match(r"```ya?ml\s*\n.*?\n```\s*", stripped, flags=re.IGNORECASE | re.DOTALL)
        if match and "gate_status:" in match.group(0):
            return stripped[match.end() :].lstrip()
    return text


def ensure_review_gate(story: Path, report: Dict[str, Any]) -> List[str]:
    path = story / "review.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Critic Gauntlet Review\n"
    body = strip_existing_gate_block(existing)
    normalized = build_gate_block(report) + body.rstrip() + "\n"
    if normalized != existing:
        path.write_text(normalized, encoding="utf-8")
        return ["review_gate_yaml_synced"]
    return []


def refresh_machine_metrics(story: Path, phase: int, mode: str) -> Dict[str, Any]:
    return machine_evaluate(story, phase, mode)


def update_quality_report_metrics(story: Path, phase: int, mode: str) -> List[str]:
    path = story / "quality-report.json"
    if not path.exists():
        return []
    report = load_json(path)
    changes = normalize_failure_lists(report)
    changes.extend(normalize_report_scores(report))
    changes.extend(sync_evaluation_scores(story, report))
    metrics = refresh_machine_metrics(story, phase, mode)
    if report.get("machine_metrics") != metrics:
        report["machine_metrics"] = metrics
        changes.append("machine_metrics_refreshed")
    write_json(path, report)
    changes.extend(ensure_review_gate(story, report))
    return changes


def draft_scenes_are_valid(story: Path, mode: str) -> bool:
    result = validate_story(story, phase_for_role(mode, "scene"), mode)
    return result.get("status") == "pass"


def draft_scene_paths(story: Path) -> List[Path]:
    return sorted(path for path in (story / "draft-scenes").glob("scene-*.md") if path.is_file())


def final_chapter_paths(story: Path) -> List[Path]:
    return sorted(path for path in (story / "final-chapters").glob("ch*.md") if path.is_file())


def final_chapters_need_repack(story: Path) -> bool:
    chapters = final_chapter_paths(story)
    if not chapters:
        return False
    for path in chapters:
        length = count_nonspace(path.read_text(encoding="utf-8"))
        if length < 500 or length > 1200:
            return True
    return False


def _chapter_hook(text: str, index: int) -> str:
    for line in reversed(text.splitlines()):
        stripped = line.strip().strip("#").strip()
        if stripped and count_nonspace(stripped) >= 8:
            return stripped[:60]
    return f"第{index + 1:02d}章继续兑现反转"


def repack_from_draft_scenes(story: Path, mode: str) -> List[str]:
    if not final_chapters_need_repack(story):
        return []
    if not draft_scenes_are_valid(story, mode):
        return []
    scenes = draft_scene_paths(story)
    if not scenes:
        return []

    chapters_dir = story / "final-chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    for path in final_chapter_paths(story):
        path.unlink()

    existing_final = (story / "final.md").read_text(encoding="utf-8") if (story / "final.md").exists() else ""
    # Preserve the model's title/guide when reflowing chapters; never invent one.
    heading = re.search(r"^#{1,3}\s*第\s*\d+\s*章", existing_final, re.MULTILINE)
    prefix = existing_final[:heading.start()].strip() if heading else ""
    final_parts: List[str] = [prefix] if prefix else []
    map_lines = ["| 章 | 字数 | 本章悬念 |", "|---|---:|---|"]
    for index, scene in enumerate(scenes, start=1):
        text = scene.read_text(encoding="utf-8").strip()
        chapter_path = chapters_dir / f"ch{index:02d}.md"
        chapter_path.write_text(text + "\n", encoding="utf-8")
        final_parts.append(f"## 第 {index} 章\n\n{text}")
        map_lines.append(f"| {index:02d} | {count_nonspace(text)} | {_chapter_hook(text, index)} |")

    (story / "final.md").write_text("\n\n".join(final_parts).strip() + "\n", encoding="utf-8")
    (chapters_dir / "_chapters-map.md").write_text("\n".join(map_lines) + "\n", encoding="utf-8")
    return ["phase7_repacked_from_draft_scenes"]


def _runner_is_mock(story: Path, runner: str = "", provider: str = "") -> bool:
    if runner == "mock" or provider == "mock":
        return True
    manifest = story / "story.yaml"
    if not manifest.exists():
        return False
    text = manifest.read_text(encoding="utf-8")
    return bool(re.search(r"^\s*(runner|provider):\s*mock\s*$", text, flags=re.MULTILINE))


def set_story_status(story: Path, status: str) -> bool:
    path = story / "story.yaml"
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = [f"slug: {story.name}", "pipeline_mode: production"]
    changed = False
    for index, line in enumerate(lines):
        if line.startswith("status:"):
            if line != f"status: {status}":
                lines[index] = f"status: {status}"
                changed = True
            break
    else:
        insert_at = 1 if lines else 0
        lines.insert(insert_at, f"status: {status}")
        changed = True
    if changed:
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return changed


def normalize_phase7(story: Path, mode: str, runner: str = "", provider: str = "") -> List[str]:
    changes = repack_from_draft_scenes(story, mode)
    changes.extend(update_quality_report_metrics(story, phase_for_role(mode, "final"), mode))
    metrics = refresh_machine_metrics(story, phase_for_role(mode, "final"), mode)
    if not metrics.get("failures"):
        status = "test_fixture" if _runner_is_mock(story, runner, provider) else "final"
        if set_story_status(story, status):
            changes.append(f"story_status_{status}")
    if changes:
        changes = list(dict.fromkeys(changes))
    return changes


def normalize_story(story: Path, phase: int, mode: str, runner: str = "", provider: str = "") -> Dict[str, Any]:
    story = Path(story)
    changes: List[str] = []
    if phase == 3:
        changes.extend(normalize_phase3(story))
    elif phase == phase_for_role(mode, "beat"):
        changes.extend(normalize_phase4(story))
        from repairs.repair_fragmentation_and_soft_words import sanitize_scene_cards
        if sanitize_scene_cards(story / "scene-cards"):
            changes.append("phase4_sanitized_scene_cards")
    elif phase == phase_for_role(mode, "critic"):
        changes.extend(update_quality_report_metrics(story, phase, mode))
    elif phase == phase_for_role(mode, "final"):
        changes.extend(normalize_phase7(story, mode, runner, provider))
    return {
        "story": str(story),
        "phase": phase,
        "mode": mode,
        "changes": list(dict.fromkeys(changes)),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--story", required=True)
    parser.add_argument("--phase", required=True, type=int, choices=range(1, 9))
    parser.add_argument("--mode", default="production", choices=["production", "production_v6", "ultra_short"])
    parser.add_argument("--runner", default="")
    parser.add_argument("--provider", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = normalize_story(Path(args.story), args.phase, args.mode, runner=args.runner, provider=args.provider)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
