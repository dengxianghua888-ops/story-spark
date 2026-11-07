#!/usr/bin/env python3
"""Machine-enforced quality gates for StoryForge production mode."""

from __future__ import annotations

from storyforge_lib import phase_for_role

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

from v4_quality import (
    count_hits,
    count_nonspace,
    load_story_manifest,
    load_workspace_policy,
    parse_simple_yaml_block,
    style_metrics,
)
from rhythm_metrics import rhythm_fit

ROOT = Path(__file__).resolve().parents[1]


PRODUCTION_ARTIFACTS = {
    1: ["source.md", "market-brief.json"],
    2: [
        "story-brief.json",
        "dissection.md",
        "analysis/beat-sheet.md",
        "analysis/style-dna.md",
        "analysis/soul-contract.md",
        "analysis/reader-engine.md",
        "analysis/tension-ledger.md",
    ],
    3: ["adaptation.md", "adaptation-room.json"],
    4: ["beat-bible.json", "scene-cards/*.json"],
    5: ["draft-scenes/*.md", "draft.md"],
    6: [
        "review.md",
        "quality-report.json",
        "diff.md",
        "evaluation/platform.json",
        "evaluation/emotion.json",
        "evaluation/style.json",
        "evaluation/logic.json",
    ],
    7: [
        "final.md",
        "craft-notes.md",
        "tomato-submission.md",
        "final-chapters/_chapters-map.md",
        "final-chapters/*.md",
        "story.yaml",
    ],
    8: ["feedback-learning.json"],
}

PRODUCTION_V6_ARTIFACTS = {
    1: ["source.md", "market-brief.json"],
    2: [
        "story-brief.json",
        "dissection.md",
        "analysis/beat-sheet.md",
        "analysis/style-dna.md",
        "analysis/soul-contract.md",
        "analysis/reader-engine.md",
        "analysis/tension-ledger.md",
        "analysis/chapter-soul-map.json",
    ],
    3: ["adaptation.md", "adaptation-room.json"],
    4: ["hook/opening-hook.md", "hook/hook-meta.json"],
    5: ["beat-bible.json", "scene-cards/*.json"],
    6: ["draft-scenes/*.md", "draft.md"],
    7: [
        "review.md",
        "quality-report.json",
    ],
    8: [
        "final.md",
        "craft-notes.md",
        "tomato-submission.md",
        "final-chapters/_chapters-map.md",
        "final-chapters/*.md",
        "story.yaml",
    ],
    9: ["feedback-learning.json"],
}

PRODUCTION_DEFAULTS = {
    "production": {"target_min": 10000, "target_max": 18000},
    "production_v6": {"target_min": 3000, "target_max": 25000},
    "ultra_short": {"target_min": 6000, "target_max": 9000},
}

ACTION_MARKERS = [
    "走",
    "拿",
    "推",
    "砸",
    "摔",
    "递",
    "抓",
    "按",
    "签",
    "打开",
    "冲",
    "站",
    "坐",
    "看",
    "问",
    "说",
    "哭",
    "笑",
    "跪",
    "跑",
    "抬",
    "低",
    "挡",
    "拦",
    "扔",
    "摁",
]

PLACEHOLDER_EVIDENCE_TERMS = [
    "platform evidence",
    "emotion evidence",
    "style evidence",
    "logic evidence",
    "mock evidence",
    "placeholder",
    "todo",
    "待补",
    "示例证据",
]

REQUIRED_MACHINE_METRIC_SECTIONS = {
    "target_length",
    "chapters",
    "paywall_cards",
    "direct_submission",
    "source_overlap",
    "source_rhythm_fit",
    "repeated_ngram",
    "style_metrics",
    "forbidden_words",
    "soft_forbidden_words",
}
REQUIRED_CRITIC_SCORES = {"platform", "emotion", "style", "logic"}
EVALUATION_FILES = {
    "platform": "evaluation/platform.json",
    "emotion": "evaluation/emotion.json",
    "style": "evaluation/style.json",
    "logic": "evaluation/logic.json",
}

SENTENCE_END_RE = re.compile(r"[。！？!?；;]")
PAYWALL_LABEL_RE = re.compile(r"【\s*付费|付费节点|付费卡点|paywall", re.IGNORECASE)
PLANNING_BARRAGE_RE = re.compile(r"弹幕|评论|吐槽")
PLANNING_BREATHING_RE = re.compile(r"弹幕|评论|吐槽|慢半拍|低压|生活动作|证据动作|反应|留白|呼吸|动作")
PLANNING_PRESSURE_RE = re.compile(r"逼问|质问|追问|诘问|反问|短问短答")
PLANNING_INTENSITY_RE = re.compile(r"黑屏|崩溃|宣告|吐血|威胁|压迫|打脸|全场死寂")
PLANNING_OVERDRIVE_RE = re.compile(r"全程|持续|不断|拉满|每行|每句|爆炸|全场死寂")
NARRATION_CRUTCH_RE = re.compile(r"(她|他)(知道|明白|意识到|清楚|心想|暗忖|终于明白|这才知道)")


def load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"missing file: {path}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}")


def required_artifacts_for_phase(phase: int, mode: str = "production") -> List[str]:
    artifacts: List[str] = []
    artifact_map = PRODUCTION_V6_ARTIFACTS if mode == "production_v6" else PRODUCTION_ARTIFACTS
    for current in range(1, phase + 1):
        artifacts.extend(artifact_map.get(current, []))
    return artifacts


def _has_artifact(story: Path, rel: str) -> bool:
    if "*" in rel:
        return any(story.glob(rel))
    return (story / rel).exists()


def missing_artifacts(story: Path, phase: int, mode: str = "production") -> List[str]:
    return [rel for rel in required_artifacts_for_phase(phase, mode) if not _has_artifact(story, rel)]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _has_common_substring(a: str, b: str, size: int) -> bool:
    if size <= 0:
        return True
    if len(a) > len(b):
        a, b = b, a
    if len(a) < size:
        return False
    chunks = {a[index : index + size] for index in range(0, len(a) - size + 1)}
    return any(b[index : index + size] in chunks for index in range(0, len(b) - size + 1))


def max_common_substring_len(a: str, b: str, cap: int = 500) -> int:
    a = normalize_text(a)
    b = normalize_text(b)
    high = min(len(a), len(b), cap)
    low = 0
    while low < high:
        mid = (low + high + 1) // 2
        if _has_common_substring(a, b, mid):
            low = mid
        else:
            high = mid - 1
    return low


def max_repeated_substring_len(text: str, cap: int = 320) -> int:
    normalized = normalize_text(text)
    high = min(len(normalized) // 2, cap)
    low = 0
    while low < high:
        mid = (low + high + 1) // 2
        seen = set()
        duplicate = False
        for index in range(0, len(normalized) - mid + 1):
            chunk = normalized[index : index + mid]
            if chunk in seen:
                duplicate = True
                break
            seen.add(chunk)
        if duplicate:
            low = mid
        else:
            high = mid - 1
    return low


def action_density(text: str) -> float:
    chars = count_nonspace(text)
    if not chars:
        return 0.0
    hits = sum(text.count(marker) for marker in ACTION_MARKERS)
    return round(hits / (chars / 1000), 3)


def chapter_files(story: Path) -> List[Path]:
    return sorted(path for path in (story / "final-chapters").glob("ch*.md") if path.is_file())


def chapter_text_consistency(text: str, chapters: List[Path]) -> Dict[str, Any]:
    """Bind delivered chapter bodies to final.md, ignoring packaging whitespace.

    The final-packager contract uses H2 第N章 headings after the title/guide.
    Chapter files may carry their own leading Markdown heading.
    """
    bodies = re.split(r"^##[ \t]*第[ \t]*[一二三四五六七八九十百千\d]+[ \t]*章[^\n]*$", text, flags=re.MULTILINE)[1:]
    mismatches = []
    for index, (body, path) in enumerate(zip(bodies, chapters), start=1):
        chapter = path.read_text(encoding="utf-8").strip()
        without_heading = re.sub(r"^#{1,3}[ \t]+[^\n]*(?:\n|$)", "", chapter, count=1)
        candidates = {normalize_text(chapter), normalize_text(without_heading)}
        if normalize_text(body) not in candidates:
            mismatches.append(index)
    matches = bool(chapters) and len(bodies) == len(chapters) and not mismatches
    return {"status": "pass" if matches else "fail", "final_count": len(bodies),
            "file_count": len(chapters), "mismatched_chapters": mismatches}


def _map_cells(line: str) -> List[str]:
    """Read a pipe-delimited map row without splitting escaped content pipes."""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    cells = []
    cell = []
    escaped = False
    for char in stripped[1:]:
        if char == "|" and not escaped:
            cells.append("".join(cell).strip())
            cell = []
        else:
            cell.append(char)
        escaped = char == "\\" and not escaped
    if cell or not stripped.endswith("|"):
        cells.append("".join(cell).strip())
    return cells


def _chapter_map_number(label: str) -> int | None:
    label = label.strip()
    match = re.fullmatch(r"(?:ch)?([0-9]+)(?:\.md)?|第\s*([0-9]+)\s*章", label, re.IGNORECASE)
    if not match:
        return None
    # Avoid int's oversized-input limit on malformed model output.
    digits = (match.group(1) or match.group(2)).lstrip("0")
    return int(digits) if digits and len(digits) <= 9 else None


def chapter_hook_coverage(story: Path) -> Tuple[int, int, float]:
    chapters = chapter_files(story)
    if not chapters:
        return 0, 0, 0.0
    identities = Counter(_chapter_map_number(path.name) for path in chapters)
    hooks_by_chapter: Dict[int, List[str]] = {}
    map_path = story / "final-chapters" / "_chapters-map.md"
    pending_columns = 0
    active_columns = 0
    fence = ""
    fence_length = 0
    if map_path.exists():
        for raw in map_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            marker = re.match(r"^(`{3,}|~{3,})", line)
            if fence:
                if marker and marker.group(1)[0] == fence and len(marker.group(1)) >= fence_length and not line[len(marker.group(1)):].strip():
                    fence = ""
                continue
            if marker:
                fence, fence_length = marker.group(1)[0], len(marker.group(1))
                pending_columns = active_columns = 0
                continue
            cells = _map_cells(line)
            if not cells:
                pending_columns = active_columns = 0
                continue
            # Only the documented chapter/hook table can establish coverage.
            if (len(cells) >= 3 and cells[0].casefold() in {"章", "章节", "章号", "chapter"}
                    and re.search(r"钩|悬念|hook", cells[-1], re.IGNORECASE)):
                pending_columns = len(cells)
                active_columns = 0
                continue
            if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                active_columns = pending_columns if len(cells) == pending_columns else 0
                pending_columns = 0
                continue
            pending_columns = 0
            if not active_columns or len(cells) != active_columns:
                active_columns = 0
                continue
            number = _chapter_map_number(cells[0])
            if number is not None and identities.get(number) == 1:
                hooks_by_chapter.setdefault(number, []).append(cells[-1])
    # Duplicate aliases, including conflicting empty rows, cannot certify a
    # chapter. Unknown chapter numbers never fill a missing delivered chapter.
    hooks = sum(len(values) == 1 and values[0].casefold() not in {"", "-", "—", "无", "none"}
                for values in hooks_by_chapter.values())
    return hooks, len(chapters), round(hooks / len(chapters), 4)


def text_paragraphs(text: str) -> List[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]


def is_heading(paragraph: str) -> bool:
    return paragraph.lstrip().startswith("#")


def opening_guide_metrics(text: str) -> Dict[str, Any]:
    paragraphs = text_paragraphs(text)
    if not paragraphs or not paragraphs[0].startswith("# "):
        return {"present": False, "paragraphs": 0, "chars": 0, "status": "fail"}

    guide = []
    for paragraph in paragraphs[1:]:
        if paragraph.startswith("## "):
            break
        if paragraph.startswith("#"):
            continue
        guide.append(paragraph)

    chars = count_nonspace("\n".join(guide))
    present = (
        2 <= len(guide) <= 5
        and chars >= 60
        and guide[0].startswith("导语：")
    )
    return {
        "present": present,
        "paragraphs": len(guide),
        "chars": chars,
        "status": "pass" if present else "fail",
    }


def mobile_paragraph_metrics(text: str) -> Dict[str, Any]:
    offending = []
    max_sentence_endings = 0
    for paragraph in text_paragraphs(text):
        if is_heading(paragraph):
            continue
        endings = len(SENTENCE_END_RE.findall(paragraph))
        max_sentence_endings = max(max_sentence_endings, endings)
        compact_len = count_nonspace(paragraph)
        is_barrage = paragraph.startswith("【") and paragraph.endswith("】")
        is_dialogue = bool(re.fullmatch(r"[“\"「『].+[”\"」』]", paragraph.strip()))
        # Keep source-like mobile lines intact. The old one-punctuation rule
        # made the packager split barrage comments and comic two-beat lines into
        # ugly fragments, which damaged rhythm more than it helped readability.
        allowed = 1
        if is_barrage:
            allowed = 6
        elif is_dialogue:
            allowed = 6
        elif compact_len <= 60:
            allowed = 5
        elif compact_len <= 80:
            allowed = 5
        elif compact_len <= 90:
            allowed = 2
        if endings > allowed:
            offending.append(paragraph[:80])
    return {
        "offending_paragraphs": len(offending),
        "max_sentence_endings": max_sentence_endings,
        "examples": offending[:3],
        "status": "pass" if not offending else "fail",
    }


def count_paywall_rows(section: str) -> int:
    """Count data rows; only all-separator cells form a table delimiter row."""
    rows = 0
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        if cells[0] in {"节点", "序号"}:
            continue
        rows += 1
    return rows


def submission_paywall_map_metrics(story: Path, required: int) -> Dict[str, Any]:
    path = story / "tomato-submission.md"
    if not path.exists():
        return {"required": required, "actual": 0, "present": False, "status": "fail"}
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^##+\s*付费节点地图.*$", text, flags=re.MULTILINE)
    if not match:
        return {"required": required, "actual": 0, "present": False, "status": "fail"}
    section = text[match.end() :]
    next_heading = re.search(r"\n##+\s+", section)
    if next_heading:
        section = section[: next_heading.start()]
    chapter_refs = re.findall(r"第\s*\d+\s*章", section)
    actual = max(count_paywall_rows(section), len(chapter_refs))
    return {
        "required": required,
        "actual": actual,
        "present": True,
        "status": "pass" if actual >= required else "fail",
    }


def visible_paywall_label_metrics(text: str) -> Dict[str, Any]:
    hits = PAYWALL_LABEL_RE.findall(text)
    return {"hits": hits[:5], "count": len(hits), "status": "pass" if not hits else "fail"}


def direct_submission_metrics(story: Path, text: str, paywall_required: int) -> Dict[str, Any]:
    opening = opening_guide_metrics(text)
    mobile = mobile_paragraph_metrics(text)
    paywall_map = submission_paywall_map_metrics(story, paywall_required)
    labels = visible_paywall_label_metrics(text)
    status = "pass" if all(
        section.get("status") == "pass"
        for section in [opening, mobile, paywall_map, labels]
    ) else "fail"
    return {
        "status": status,
        "opening_guide": opening,
        "mobile_paragraphs": mobile,
        "submission_paywall_map": paywall_map,
        "visible_paywall_labels": labels,
    }


def load_beat_bible(story: Path) -> Dict[str, Any]:
    path = story / "beat-bible.json"
    return load_json(path) if path.exists() else {}


def target_range(story: Path, mode: str) -> Dict[str, int]:
    if mode == "ultra_short":
        defaults = PRODUCTION_DEFAULTS["ultra_short"].copy()
    elif mode == "production_v6":
        defaults = PRODUCTION_DEFAULTS["production_v6"].copy()
        source_path = story / "source.md"
        if source_path.exists():
            source_chars = count_nonspace(source_path.read_text(encoding="utf-8"))
            defaults["target_min"] = max(3000, int(source_chars * 0.6))
            defaults["target_max"] = max(defaults["target_min"] + 3000, int(source_chars * 1.8))
        return defaults
    else:
        defaults = PRODUCTION_DEFAULTS["production"].copy()
    for path in [story / "market-brief.json", story / "beat-bible.json"]:
        if not path.exists():
            continue
        data = load_json(path)
        target = data.get("target_length")
        if isinstance(target, dict):
            raw_min = target.get("min")
            raw_max = target.get("max")
            if isinstance(raw_min, int):
                defaults["target_min"] = max(defaults["target_min"], raw_min)
            if isinstance(raw_max, int):
                defaults["target_max"] = max(defaults["target_min"], raw_max)
    return defaults


def required_paywall_nodes(chars: int, target_min: int) -> int:
    """Use the same length floor for validation and editorial repair checks."""
    return max(1, math.ceil(max(chars, target_min) / 3500))


def count_paywall_cards(story: Path) -> int:
    count = 0
    beat_bible = load_beat_bible(story)
    for item in beat_bible.get("beats", []):
        if isinstance(item, dict) and item.get("paywall_card") is True:
            count += 1
    for path in sorted((story / "scene-cards").glob("*.json")):
        try:
            card = load_json(path)
        except ValueError:
            continue
        if card.get("paywall_card") is True:
            count += 1
    return count


def validate_json_artifacts(story: Path, phase: int, mode: str = "production") -> List[str]:
    failures = []
    for rel in required_artifacts_for_phase(phase, mode):
        paths = sorted(story.glob(rel)) if "*" in rel else [story / rel]
        for path in paths:
            if path.suffix == ".json":
                try:
                    load_json(path)
                except ValueError as exc:
                    failures.append(str(exc))
    return failures


def _validate_beat_bible_v6(story: Path, bible: dict) -> List[str]:
    """Validate V6 beat-bible structure (chapters + soul_anchor)."""
    failures = []
    chapters = bible.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        failures.append("beat-bible.json chapters must be a non-empty list")
        return failures
    for idx, ch in enumerate(chapters, 1):
        if not isinstance(ch, dict):
            failures.append(f"beat-bible.json chapters[{idx}] must be an object")
            continue
        if "chapter_id" not in ch:
            failures.append(f"beat-bible.json chapters[{idx}] missing chapter_id")
        scenes = ch.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            failures.append(f"beat-bible.json chapters[{idx}] must have non-empty scenes list")
        target = ch.get("target_char_count")
        if not isinstance(target, list) or len(target) < 2:
            failures.append(f"beat-bible.json chapters[{idx}] target_char_count must be [min, max]")
    scene_cards = sorted((story / "scene-cards").glob("*.json"))
    if not scene_cards:
        failures.append("scene-cards/*.json must contain at least one scene card")
    required_v6_keys = {"scene_id", "target_chars_min", "target_chars_max"}
    for path in scene_cards:
        card = load_json(path)
        if not card:
            failures.append(f"{path.relative_to(story)} is not valid JSON")
            continue
        missing = sorted(k for k in required_v6_keys if k not in card)
        if missing:
            failures.append(f"{path.relative_to(story)} missing required keys: {', '.join(missing)}")
    return failures


def validate_beat_bible_shape(story: Path, mode: str = "production") -> List[str]:
    failures = []
    bible = load_beat_bible(story)
    if not bible:
        return ["missing beat-bible.json"]

    if mode == "production_v6":
        return _validate_beat_bible_v6(story, bible)

    if not isinstance(bible.get("target_length"), dict):
        failures.append("beat-bible.json target_length must be an object")
    beats = bible.get("beats")
    if not isinstance(beats, list) or not beats:
        failures.append("beat-bible.json beats must be a non-empty list")
    else:
        required_beat_keys = {
            "beat_id",
            "scene_location",
            "character_goal",
            "conflict_action",
            "information_gap",
            "emotion_debt_balance",
            "chapter_end_hook",
            "paywall_card",
            "forbidden_summary",
        }
        for index, beat in enumerate(beats, start=1):
            if not isinstance(beat, dict):
                failures.append(f"beat-bible.json beats[{index}] must be an object")
                continue
            missing = sorted(key for key in required_beat_keys if key not in beat or beat[key] in ("", [], None))
            if missing:
                failures.append(f"beat-bible.json beats[{index}] missing required keys: {', '.join(missing)}")
            target_chars = beat.get("target_chars")
            min_chars = beat.get("target_chars_min")
            max_chars = beat.get("target_chars_max")
            has_target = _is_number(target_chars) or (_is_number(min_chars) and _is_number(max_chars))
            if not has_target:
                failures.append(f"beat-bible.json beats[{index}] must define target_chars or target_chars_min/target_chars_max")
            if not isinstance(beat.get("forbidden_summary"), list) or not beat.get("forbidden_summary"):
                failures.append(f"beat-bible.json beats[{index}].forbidden_summary must be a non-empty list")
    scene_cards = sorted((story / "scene-cards").glob("*.json"))
    if not scene_cards:
        failures.append("scene-cards/*.json must contain at least one scene card")
    rhythm_contract = bible.get("rhythm_contract")
    barrage_floor = 0.0
    if not isinstance(rhythm_contract, dict) or not rhythm_contract:
        failures.append("beat-bible.json rhythm_contract must be a non-empty object")
    else:
        required_rhythm_keys = {
            "avg visual line chars": ["allowed_avg_visual_line_chars", "avg_visual_line_chars_range"],
            "short line min": ["short_line_rate_lte_16_min"],
            "short line max": ["short_line_rate_lte_16_max"],
            "dialogue min": ["direct_dialogue_line_rate_min"],
            "dialogue max": ["direct_dialogue_line_rate_max"],
            "barrage min": ["barrage_line_rate_min"],
            "barrage max": ["barrage_line_rate_max"],
            "question density min": ["question_mark_density_per_1000_chars_min"],
            "question density max": ["question_mark_density_per_1000_chars_max"],
        }
        missing_rhythm = [
            label for label, aliases in required_rhythm_keys.items()
            if not any(alias in rhythm_contract for alias in aliases)
        ]
        if missing_rhythm:
            failures.append("beat-bible.json rhythm_contract missing keys: " + ", ".join(missing_rhythm))
        barrage_floor_raw = rhythm_contract.get("barrage_line_rate_min")
        if _is_number(barrage_floor_raw):
            barrage_floor = float(barrage_floor_raw)
    required_card_keys = {
        "scene_id",
        "beat_id",
        "target_chars_min",
        "target_chars_max",
        "location",
        "time",
        "pov",
        "characters",
        "character_goal",
        "opposition_goal",
        "conflict_action",
        "information_gap",
        "emotional_debt_delta",
        "payoff_or_hook",
        "chapter_end_hook",
        "paywall_card",
        "must_include",
        "must_not_write_as_exposition",
    }
    barrage_scene_count = 0
    breathing_scene_count = 0
    for path in scene_cards:
        card = load_json(path)
        missing = sorted(key for key in required_card_keys if key not in card or card[key] in ("", [], None))
        if missing:
            failures.append(f"{path.relative_to(story)} missing required keys: {', '.join(missing)}")
        min_chars = card.get("target_chars_min")
        max_chars = card.get("target_chars_max")
        if not _is_number(min_chars) or not _is_number(max_chars) or min_chars <= 0 or max_chars < min_chars:
            failures.append(f"{path.relative_to(story)} target_chars_min/target_chars_max must be positive numbers with max >= min")
        for key in ["characters", "must_include", "must_not_write_as_exposition"]:
            if key in card and (not isinstance(card[key], list) or not card[key]):
                failures.append(f"{path.relative_to(story)} {key} must be a non-empty list")
        rhythm_job = card.get("rhythm_job")
        if isinstance(rhythm_job, dict):
            rhythm_text = json.dumps(rhythm_job, ensure_ascii=False)
            for key in ["shape", "breathing_lines_min", "barrage_lines_min", "max_question_marks", "max_pressure_terms"]:
                if key not in rhythm_job:
                    failures.append(f"{path.relative_to(story)} rhythm_job missing {key}")
        else:
            rhythm_text = str(rhythm_job or "")
        full_planning_text = rhythm_text + " " + " ".join(str(item) for item in card.get("must_include", []) if isinstance(item, str))
        if PLANNING_BARRAGE_RE.search(full_planning_text):
            barrage_scene_count += 1
        if PLANNING_BREATHING_RE.search(full_planning_text):
            breathing_scene_count += 1
        pressure_hits = len(PLANNING_PRESSURE_RE.findall(rhythm_text))
        intensity_hits = len(PLANNING_INTENSITY_RE.findall(rhythm_text))
        if PLANNING_OVERDRIVE_RE.search(rhythm_text):
            failures.append(f"{path.relative_to(story)} rhythm_job contains overdrive wording: {rhythm_text[:80]}")
        if pressure_hits + intensity_hits > 2:
            failures.append(
                f"{path.relative_to(story)} rhythm_job overcranks pressure/intensity "
                f"({pressure_hits + intensity_hits} hits): {rhythm_text[:80]}"
            )
        if (pressure_hits or intensity_hits) and not PLANNING_BREATHING_RE.search(rhythm_text):
            failures.append(f"{path.relative_to(story)} rhythm_job plans pressure without a breathing/action counterweight")
    if scene_cards:
        if barrage_floor >= 0.10:
            required_barrage_scenes = max(1, math.ceil(len(scene_cards) * 0.50))
            if barrage_scene_count < required_barrage_scenes:
                failures.append(
                    f"scene_cards barrage/comment planning too low: {barrage_scene_count}/{len(scene_cards)} "
                    f"below required {required_barrage_scenes}"
                )
        required_breathing_scenes = max(1, math.ceil(len(scene_cards) * 0.75))
        if breathing_scene_count < required_breathing_scenes:
            failures.append(
                f"scene_cards breathing/action counterweights too low: {breathing_scene_count}/{len(scene_cards)} "
                f"below required {required_breathing_scenes}"
            )
    return failures


def validate_market_brief_shape(story: Path, mode: str) -> List[str]:
    path = story / "market-brief.json"
    if not path.exists():
        return []
    failures = []
    data = load_json(path)
    if str(data.get("pipeline_mode", "")) not in {"production", "production_v6", "ultra_short"}:
        failures.append("market-brief.json pipeline_mode must be production, production_v6, or ultra_short")
    if data.get("target_platform") != "tomato":
        failures.append("market-brief.json target_platform must be tomato")
    target = data.get("target_length")
    if not isinstance(target, dict):
        failures.append("market-brief.json target_length must be an object")
    else:
        raw_min = target.get("min")
        raw_max = target.get("max")
        if not _is_number(raw_min) or not _is_number(raw_max) or raw_min <= 0 or raw_max < raw_min:
            failures.append("market-brief.json target_length min/max must be positive numbers with max >= min")
    return failures


def validate_story_brief_shape(story: Path) -> List[str]:
    path = story / "story-brief.json"
    if not path.exists():
        return []
    failures = []
    data = load_json(path)
    required_string_keys = ["genre", "hook_type", "title_formula", "reader_promise", "payoff_pattern"]
    for key in required_string_keys:
        if not isinstance(data.get(key), str) or not data.get(key, "").strip():
            failures.append(f"story-brief.json {key} must be a non-empty string")
    for key in ["reversal_mechanisms", "emotional_debts", "forbidden_to_change", "replaceable_assets"]:
        if not isinstance(data.get(key), list) or not data.get(key):
            failures.append(f"story-brief.json {key} must be a non-empty list")
    source_length = data.get("source_length_chars")
    if not _is_number(source_length) or source_length <= 0:
        failures.append("story-brief.json source_length_chars must be a positive number")
    return failures


def _candidate_id(candidate: Dict[str, Any], fallback: str) -> str:
    return str(candidate.get("id") or candidate.get("name") or candidate.get("candidate_id") or fallback)


def validate_adaptation_room_shape(story: Path) -> List[str]:
    path = story / "adaptation-room.json"
    if not path.exists():
        return []
    failures = []
    data = load_json(path)
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 3:
        failures.append("adaptation-room.json candidates must contain exactly 3 candidates")
        candidates = candidates if isinstance(candidates, list) else []
    selected = str(data.get("selected_candidate", "")).strip()
    if not selected:
        failures.append("adaptation-room.json selected_candidate must be non-empty")
    candidate_ids = set()
    selected_candidate: Dict[str, Any] | None = None
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            failures.append(f"adaptation-room.json candidates[{index}] must be an object")
            continue
        cid = _candidate_id(candidate, f"candidate-{index}")
        candidate_ids.add(cid)
        if cid == selected:
            selected_candidate = candidate
        if not isinstance(candidate.get("premise"), str) or not candidate.get("premise", "").strip():
            failures.append(f"adaptation-room.json candidates[{index}].premise must be a non-empty string")
        for key in ["freshness_score", "fidelity_score", "tomato_score", "logic_score"]:
            value = candidate.get(key)
            if not _is_number(value) or value < 0 or value > 10:
                failures.append(f"adaptation-room.json candidates[{index}].{key} must be a number from 0 to 10")
        if "risks" not in candidate or not isinstance(candidate.get("risks"), list):
            failures.append(f"adaptation-room.json candidates[{index}].risks must be a list")
    if selected and selected not in candidate_ids:
        failures.append("adaptation-room.json selected_candidate must match a candidate id")
    if selected_candidate:
        for key in ["fidelity_score", "logic_score"]:
            value = selected_candidate.get(key)
            if _is_number(value) and value < 8.5:
                failures.append(f"adaptation-room.json selected_candidate {key} must be >= 8.5")
    for key in ["replacement_map", "mechanism_preservation"]:
        if not isinstance(data.get(key), dict) or not data.get(key):
            failures.append(f"adaptation-room.json {key} must be a non-empty object")
    if not isinstance(data.get("sensitive_topic_policy"), (str, dict)) or data.get("sensitive_topic_policy") in ("", None):
        failures.append("adaptation-room.json sensitive_topic_policy must be present")
    return failures


def load_scene_cards(story: Path) -> List[Tuple[Path, Dict[str, Any]]]:
    cards = []
    for path in sorted((story / "scene-cards").glob("*.json")):
        cards.append((path, load_json(path)))
    return cards


def _joined_scene_text(texts: List[str]) -> str:
    return "\n\n".join(text.strip() for text in texts if text.strip()).strip()


def validate_scene_draft_consistency(story: Path, mode: str = "production") -> List[str]:
    failures = []
    draft_path = story / "draft.md"
    draft_dir = story / "draft-scenes"
    if not draft_path.exists() or not draft_dir.exists():
        return failures
    scene_cards = load_scene_cards(story)
    if not scene_cards:
        return failures
    expected_scene_ids = []
    scene_texts = []
    for card_path, card in scene_cards:
        scene_id = str(card.get("scene_id", "")).strip()
        if not scene_id:
            continue
        expected_scene_ids.append(scene_id)
        scene_path = draft_dir / f"{scene_id}.md"
        if not scene_path.exists():
            failures.append(f"missing draft scene for {card_path.relative_to(story)}: draft-scenes/{scene_id}.md")
            continue
        text = scene_path.read_text(encoding="utf-8")
        scene_texts.append(text)
        length = count_nonspace(text)
        min_chars = card.get("target_chars_min")
        max_chars = card.get("target_chars_max")
        if _is_number(min_chars) and _is_number(max_chars) and (length < min_chars or length > max_chars):
            # V6: skip length hard-block — soul_anchor quality is the priority
            if mode != "production_v6":
                failures.append(f"draft-scenes/{scene_id}.md length {length} outside scene card range {min_chars}-{max_chars}")
    expected_names = {f"{scene_id}.md" for scene_id in expected_scene_ids}
    for path in sorted(draft_dir.glob("*.md")):
        if path.name not in expected_names:
            failures.append(f"draft-scenes/{path.name} has no matching scene card")
    if scene_texts and mode != "production_v6":
        draft_text = draft_path.read_text(encoding="utf-8").strip()
        joined_with_blanks = _joined_scene_text(scene_texts)
        joined_direct = "".join(scene_texts).strip()
        if draft_text not in {joined_with_blanks, joined_direct}:
            failures.append("draft.md must equal draft-scenes joined in scene_id order")
    return failures


def _skeleton(value: str) -> str:
    value = re.sub(r"\d+", "#", value)
    value = re.sub(r"[０-９]+", "#", value)
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[，。！？!?；;：:、“”\"'（）()《》【】\[\]{}<>#\-—_.,]", "", value)
    return value


def semantic_repetition_metrics(text: str) -> Dict[str, Any]:
    sentences = []
    for part in re.split(r"[。！？!?]\s*|\n+", text):
        stripped = part.strip()
        if not stripped or stripped.startswith("#") or count_nonspace(stripped) < 10:
            continue
        skeleton = _skeleton(stripped)
        if len(skeleton) >= 8:
            sentences.append(skeleton)
    if not sentences:
        return {"sentence_count": 0, "max_sentence_repeats": 0, "max_sentence_repeat_ratio": 0.0}
    counts = Counter(sentences)
    _item, max_repeats = counts.most_common(1)[0]
    return {
        "sentence_count": len(sentences),
        "unique_sentence_skeletons": len(counts),
        "max_sentence_repeats": max_repeats,
        "max_sentence_repeat_ratio": round(max_repeats / len(sentences), 4),
    }


def semantic_repetition_failures(text: str) -> List[str]:
    metrics = semantic_repetition_metrics(text)
    if metrics["sentence_count"] >= 30 and metrics["max_sentence_repeats"] >= 8 and metrics["max_sentence_repeat_ratio"] >= 0.18:
        return [
            "semantic_repetition: repeated sentence skeleton "
            f"{metrics['max_sentence_repeats']} times "
            f"({metrics['max_sentence_repeat_ratio']})"
        ]
    return []


META_LEAK_RE = re.compile(
    r"(```|截断句|draft-scenes|/Users/|artifact|<<<FILE|<<<END FILE|END FILE|hook:|终局价值|留到终局|"
    r"事实层面|价值层面|程序层面|关系层面|情绪层面|社会性新生|轮回终止|主角获得|"
    r"主线爽感|尊重型修复|价值反转|情绪债|人物弧|给读者|让读者|付费点|付费卡点|"
    r"终局黑切|不回头补叙|旧关系交代|公开承认能否|不抢主线|给出.*修复|把爱情.*判成|"
    r"寒心感|砸实|别给缓冲|连续发生|补救空间|落地到|行业切割|"
    r"还有没有机会|有没有任何|知道数字没有|知道多少.*真相|具体写了什么|"
    r"被剪掉的部分是什么|发生过什么|到底遭遇过什么|真不知道还是不肯知道|"
    r"；.*(?:什么|为什么|谁|是否|是不是|有没有|还有没有|能否|能不能|到底|几天|知道多少|知道.*没有|真不知道|不肯知道|补救))",
    re.IGNORECASE,
)
QUESTION_WORD_META_RE = re.compile(r"^(?!.*[“\"「『]).*(?:为什么|为何|什么|谁|是否|是不是|有没有|还有没有|能否|能不能|到底|几天|怎么).*$")


def meta_leak_metrics(text: str) -> Dict[str, Any]:
    hits = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        has_quote = any(mark in stripped for mark in "“\"「『")
        if META_LEAK_RE.search(line) or (stripped and not has_quote and QUESTION_WORD_META_RE.search(stripped)):
            hits.append({"line": line_no, "text": line.strip()[:120]})
    return {
        "count": len(hits),
        "examples": hits[:8],
        "status": "pass" if not hits else "fail",
    }


def validate_narration_crutches(text: str) -> Dict[str, Any]:
    hits = NARRATION_CRUTCH_RE.findall(text)
    count = len(hits)
    if count <= 5:
        status = "pass"
    elif count <= 8:
        status = "warning"
    else:
        status = "fail"
    return {"count": count, "status": status, "examples": ["".join(h) for h in hits[:5]]}


def machine_evaluate(story: Path, phase: int, mode: str) -> Dict[str, Any]:
    text_path = story / "final.md" if phase >= phase_for_role(mode, "final") and (story / "final.md").exists() else story / "draft.md"
    text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
    chars = count_nonspace(text)
    target = target_range(story, mode)
    metrics = style_metrics(text)
    metrics["action_density_per_k"] = action_density(text)
    repetition_metrics = semantic_repetition_metrics(text)
    meta_leaks = meta_leak_metrics(text)

    policy = load_workspace_policy(story)
    genre = ""
    if (story / "story.yaml").exists():
        try:
            genre = str(load_story_manifest(story).get("genre", ""))
        except ValueError:
            genre = ""
    hard_terms = list(policy.get("forbidden_words", []))
    hard_terms.extend(policy.get("genre_extra_forbidden", {}).get(genre, []))
    hard_hits = count_hits(text, hard_terms)
    soft_hits = count_hits(text, policy.get("soft_forbidden", []))

    paywall_actual = count_paywall_cards(story)
    paywall_required = required_paywall_nodes(chars, target["target_min"])
    direct_submission = direct_submission_metrics(story, text, paywall_required) if phase >= phase_for_role(mode, "final") else {
        "status": "pass",
        "opening_guide": {"status": "pass"},
        "mobile_paragraphs": {"status": "pass"},
        "submission_paywall_map": {"status": "pass", "required": paywall_required, "actual": paywall_required},
        "visible_paywall_labels": {"status": "pass", "count": 0, "hits": []},
    }
    if phase >= phase_for_role(mode, "final"):
        hook_hits, chapter_count, hook_coverage = chapter_hook_coverage(story)
        chapters = chapter_files(story)
        chapter_lengths = [count_nonspace(path.read_text(encoding="utf-8")) for path in chapters]
        chapter_consistency = chapter_text_consistency(text, chapters)
    else:
        hook_hits, chapter_count, hook_coverage = 0, 0, 0.0
        chapters = []
        chapter_lengths = []
        chapter_consistency = {"status": "pass", "applicable": False}
    source_text = (story / "source.md").read_text(encoding="utf-8") if (story / "source.md").exists() else ""
    overlap = max_common_substring_len(source_text, text) if source_text and text else 0
    repeated = max_repeated_substring_len(text) if text else 0
    source_rhythm = rhythm_fit(source_text, text) if source_text and text else {
        "status": "pass",
        "applicable": False,
        "source": {},
        "candidate": {},
        "failures": [],
    }

    failures = []
    if phase >= 5 and chars < target["target_min"] and mode != "production_v6":
        failures.append(f"target_length: actual {chars} below min {target['target_min']}")
    if phase >= 5 and chars > target["target_max"] * 1.25 and mode != "production_v6":
        failures.append(f"target_length: actual {chars} exceeds max tolerance {int(target['target_max'] * 1.25)}")
    if phase >= 5 and paywall_actual < paywall_required and mode != "production_v6":
        failures.append(f"paywall_cards: actual {paywall_actual} below required {paywall_required}")
    final_phase = phase_for_role(mode, "final")
    if phase >= final_phase:
        if direct_submission["opening_guide"]["status"] != "pass":
            failures.append(
                "opening_guide: final.md must include 2-5 guide paragraphs after the title before the first chapter, "
                "with the first paragraph starting with 导语："
            )
        if direct_submission["mobile_paragraphs"]["status"] != "pass":
            failures.append(
                "mobile_paragraphs: "
                f"{direct_submission['mobile_paragraphs']['offending_paragraphs']} paragraphs contain multiple sentences; "
                "use one sentence per paragraph"
            )
        if direct_submission["submission_paywall_map"]["status"] != "pass":
            failures.append(
                "submission_paywall_map: tomato-submission.md must include 付费节点地图 with at least "
                f"{paywall_required} natural paywall nodes"
            )
        if direct_submission["visible_paywall_labels"]["status"] != "pass":
            failures.append("visible_paywall_labels: final.md must not expose internal 付费节点/付费卡点 labels")
        if not chapters:
            failures.append("chapters: final-chapters/ch*.md missing")
        if chapter_consistency["status"] != "pass":
            failures.append("chapter_text_consistency: final-chapters bodies must match final.md chapters in order")
        if hook_coverage < 1.0:
            failures.append(f"chapter_hooks: coverage {hook_coverage} below 1.0")
        for index, length in enumerate(chapter_lengths, start=1):
            if length < 500 or length > 1200:
                failures.append(f"chapter_length: ch{index:02d} has {length} chars, expected 500-1200")
    if hard_hits and (mode != "production_v6" or sum(hard_hits.values()) > 2):
        failures.append(f"forbidden_words: {hard_hits}")
    soft_max = int(policy.get("soft_forbidden_max", 2)) if mode != "production_v6" else 12
    if sum(soft_hits.values()) > soft_max:
        failures.append(f"soft_forbidden_words: {soft_hits}")
    if overlap > 120:
        failures.append(f"source_overlap: max continuous overlap {overlap} exceeds 120")
    if repeated > 260:
        failures.append(f"repeated_ngram: repeated substring {repeated} exceeds 260")
    if phase >= 5 and metrics["action_density_per_k"] < 8:
        failures.append(f"scene_action_density: {metrics['action_density_per_k']} below 8 per 1k chars")
    if phase >= 5:
        failures.extend(semantic_repetition_failures(text))
    if phase >= 5 and meta_leaks["status"] != "pass" and mode != "production_v6":
        failures.append(f"production_meta_leak: {meta_leaks['count']} leaked construction/protocol lines")
    if phase >= 5 and source_rhythm.get("status") == "fail" and mode != "production_v6":
        failures.extend(f"source_rhythm_fit: {item}" for item in source_rhythm.get("failures", []))

    narration_crutches = validate_narration_crutches(text) if phase >= 5 else {"count": 0, "status": "pass", "examples": []}
    if phase >= 5 and narration_crutches["status"] == "fail":
        failures.append(f"narration_crutches: {narration_crutches['count']} instances (hard limit 8)")

    return {
        "text_path": str(text_path),
        "target_length": {
            "min": target["target_min"],
            "max": target["target_max"],
            "actual": chars,
            "status": "pass" if target["target_min"] <= chars <= int(target["target_max"] * 1.25) else "fail",
        },
        "chapters": {
            "count": chapter_count,
            "hook_hits": hook_hits,
            "hook_coverage": hook_coverage,
            "lengths": chapter_lengths,
            "text_consistency": chapter_consistency,
            "status": "pass" if phase < phase_for_role(mode, "final") or (chapter_count > 0 and hook_coverage >= 1.0 and chapter_consistency["status"] == "pass") else "fail",
        },
        "paywall_cards": {
            "required": paywall_required,
            "actual": paywall_actual,
            "status": "pass" if paywall_actual >= paywall_required else "fail",
        },
        "direct_submission": direct_submission,
        "source_overlap": {
            "max_continuous_overlap_chars": overlap,
            "status": "pass" if overlap <= 120 else "fail",
        },
        "repeated_ngram": {
            "max_repeated_substring_chars": repeated,
            "status": "pass" if repeated <= 260 else "fail",
        },
        "style_metrics": metrics,
        "source_rhythm_fit": source_rhythm,
        "semantic_repetition": repetition_metrics,
        "production_meta_leak": meta_leaks,
        "narration_crutches": narration_crutches,
        "forbidden_words": {"hits": hard_hits, "status": "pass" if not hard_hits else "fail"},
        "soft_forbidden_words": {
            "hits": soft_hits,
            "status": "pass" if sum(soft_hits.values()) <= int(policy.get("soft_forbidden_max", 2)) else "fail",
        },
        "failures": failures,
    }


def _has_placeholder_evidence(values: Any) -> bool:
    if not isinstance(values, list):
        return False
    for value in values:
        text = str(value).strip().lower()
        if any(term in text for term in PLACEHOLDER_EVIDENCE_TERMS):
            return True
    return False


def _metric_value(section: Any, key: str) -> Any:
    return section.get(key) if isinstance(section, dict) else None


def validate_quality_report_metric_sync(report: Dict[str, Any], metrics: Dict[str, Any], phase: int, mode: str = "production") -> List[str]:
    failures = []
    machine = report.get("machine_metrics")
    if not isinstance(machine, dict):
        return failures

    target = machine.get("target_length")
    actual = _metric_value(target, "actual")
    recomputed_actual = metrics.get("target_length", {}).get("actual")
    if phase >= phase_for_role(mode, "final") and _is_number(actual) and _is_number(recomputed_actual) and int(actual) != int(recomputed_actual):
        failures.append(
            f"quality-report.json machine_metrics.target_length.actual does not match machine recompute: {actual} != {recomputed_actual}"
        )

    paywall = machine.get("paywall_cards")
    if phase >= phase_for_role(mode, "final"):
        for key in ["required", "actual"]:
            reported = _metric_value(paywall, key)
            recomputed = metrics.get("paywall_cards", {}).get(key)
            if _is_number(reported) and _is_number(recomputed) and int(reported) != int(recomputed):
                failures.append(
                    f"quality-report.json machine_metrics.paywall_cards.{key} does not match machine recompute: {reported} != {recomputed}"
                )

    if phase >= phase_for_role(mode, "final"):
        chapters = machine.get("chapters")
        reported_count = _metric_value(chapters, "count")
        recomputed_count = metrics.get("chapters", {}).get("count")
        if _is_number(reported_count) and _is_number(recomputed_count) and int(reported_count) != int(recomputed_count):
            failures.append(
                f"quality-report.json machine_metrics.chapters.count does not match machine recompute: {reported_count} != {recomputed_count}"
            )
        reported_coverage = _metric_value(chapters, "hook_coverage")
        recomputed_coverage = metrics.get("chapters", {}).get("hook_coverage")
        if _is_number(reported_coverage) and _is_number(recomputed_coverage) and abs(float(reported_coverage) - float(recomputed_coverage)) > 0.0001:
            failures.append(
                "quality-report.json machine_metrics.chapters.hook_coverage does not match machine recompute: "
                f"{reported_coverage} != {recomputed_coverage}"
            )
    return failures


def validate_quality_report_against_machine(story: Path, metrics: Dict[str, Any], phase: int, mode: str = "production") -> List[str]:
    failures = []
    report_path = story / "quality-report.json"
    if not report_path.exists():
        return failures
    report = load_json(report_path)
    failures.extend(validate_quality_report_shape(report, metrics, phase, mode=mode))
    failures.extend(validate_quality_report_metric_sync(report, metrics, phase, mode))
    gate = str(report.get("gate_status", "")).lower()
    if gate == "pass" and metrics["failures"] and mode != "production_v6":
        failures.append("quality-report.json self-reports pass but machine metrics fail: " + "; ".join(metrics["failures"]))
    if (story / "review.md").exists():
        try:
            review_gate = parse_simple_yaml_block((story / "review.md").read_text(encoding="utf-8"))
        except ValueError as exc:
            failures.append(str(exc))
        else:
            if str(review_gate.get("gate_status", "")).lower() != gate:
                failures.append("review.md gate_status does not match quality-report.json")
            if review_gate.get("critical_failures", []) != report.get("critical_failures", []):
                failures.append("review.md critical_failures does not match quality-report.json")
    if mode != "production_v6":
        failures.extend(validate_evaluation_files(story, report))
    return failures


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and (not isinstance(value, float) or math.isfinite(value))


def _status(value: Any) -> str:
    return str(value).strip().lower()


def validate_quality_report_shape(report: Dict[str, Any], metrics: Dict[str, Any], phase: int, mode: str = "production") -> List[str]:
    failures = []
    if report.get("schema_version") != 2:
        failures.append("quality-report.json schema_version must be 2")
    if str(report.get("pipeline_mode", "")) not in {"production", "production_v6", "ultra_short"}:
        failures.append("quality-report.json pipeline_mode must be production, production_v6, or ultra_short")
    gate = _status(report.get("gate_status", ""))
    if gate not in {"pass", "fail"}:
        failures.append("quality-report.json gate_status must be pass or fail")

    for key in ["critical_failures", "important_failures", "evidence"]:
        if not isinstance(report.get(key), list):
            failures.append(f"quality-report.json {key} must be a list")
    if gate == "pass" and not report.get("evidence"):
        failures.append("quality-report.json pass gate requires non-empty evidence")
    if gate == "pass" and _has_placeholder_evidence(report.get("evidence")):
        failures.append("quality-report.json pass gate contains placeholder evidence")

    machine = report.get("machine_metrics")
    if not isinstance(machine, dict):
        failures.append("quality-report.json machine_metrics must be an object")
    else:
        missing = sorted(REQUIRED_MACHINE_METRIC_SECTIONS - set(machine))
        if missing:
            failures.append("quality-report.json machine_metrics missing sections: " + ", ".join(missing))
        for key in REQUIRED_MACHINE_METRIC_SECTIONS - {"style_metrics"}:
            section = machine.get(key)
            if isinstance(section, dict):
                status = _status(section.get("status", ""))
                if status not in {"pass", "fail"}:
                    failures.append(f"quality-report.json machine_metrics.{key}.status must be pass or fail")
                if gate == "pass" and status == "fail" and mode != "production_v6":
                    failures.append(f"quality-report.json pass gate cannot include failing machine_metrics.{key}")
            elif key in machine:
                failures.append(f"quality-report.json machine_metrics.{key} must be an object")
        style = machine.get("style_metrics") if isinstance(machine, dict) else None
        if isinstance(style, dict):
            if "action_density_per_k" not in style:
                failures.append("quality-report.json machine_metrics.style_metrics.action_density_per_k is required")
        elif isinstance(machine, dict) and "style_metrics" in machine:
            failures.append("quality-report.json machine_metrics.style_metrics must be an object")

    scores = report.get("critic_scores")
    if not isinstance(scores, dict):
        failures.append("quality-report.json critic_scores must be an object")
    else:
        missing = sorted(REQUIRED_CRITIC_SCORES - set(scores))
        if missing:
            failures.append("quality-report.json critic_scores missing: " + ", ".join(missing))
        for key in sorted(REQUIRED_CRITIC_SCORES & set(scores)):
            value = scores[key]
            if not _is_number(value) or value < 0 or value > 10:
                failures.append(f"quality-report.json critic_scores.{key} must be a number from 0 to 10")
            elif gate == "pass" and value < 7:
                failures.append(f"quality-report.json pass gate requires critic_scores.{key} >= 7")

    if gate == "fail" and metrics.get("failures") and not report.get("critical_failures") and not report.get("important_failures"):
        failures.append("quality-report.json fail gate must list critical_failures or important_failures")
    return failures


def validate_evaluation_files(story: Path, report: Dict[str, Any]) -> List[str]:
    failures = []
    gate = _status(report.get("gate_status", ""))
    report_scores = report.get("critic_scores") if isinstance(report.get("critic_scores"), dict) else {}
    for key, rel in EVALUATION_FILES.items():
        path = story / rel
        if not path.exists():
            continue
        data = load_json(path)
        status = _status(data.get("status", ""))
        if status not in {"pass", "fail"}:
            failures.append(f"{rel} status must be pass or fail")
        score = data.get("score")
        if not _is_number(score) or score < 0 or score > 10:
            failures.append(f"{rel} score must be a number from 0 to 10")
        elif gate == "pass" and score < 7:
            failures.append(f"{rel} pass gate requires score >= 7")
        evidence = data.get("evidence")
        if status == "pass" and not (isinstance(evidence, list) and evidence):
            failures.append(f"{rel} pass status requires non-empty evidence list")
        if status == "pass" and _has_placeholder_evidence(evidence):
            failures.append(f"{rel} pass status contains placeholder evidence")
        if gate == "pass" and status == "fail":
            failures.append(f"quality-report.json pass gate conflicts with {rel} status=fail")
        report_score = report_scores.get(key) if isinstance(report_scores, dict) else None
        if _is_number(report_score) and _is_number(score) and abs(float(report_score) - float(score)) > 0.01:
            failures.append(f"quality-report.json critic_scores.{key} does not match {rel} score")
    return failures


def validate_feedback_learning_shape(story: Path) -> List[str]:
    failures = []
    path = story / "feedback-learning.json"
    if not path.exists():
        return failures
    data = load_json(path)
    if not isinstance(data.get("story_slug"), str) or not data.get("story_slug", "").strip():
        failures.append("feedback-learning.json story_slug must be a non-empty string")
    if str(data.get("pipeline_mode", "")) not in {"production", "production_v6", "ultra_short"}:
        failures.append("feedback-learning.json pipeline_mode must be production, production_v6, or ultra_short")
    for key in ["failure_types", "successful_hooks", "manual_revision_delta"]:
        if not isinstance(data.get(key), list):
            failures.append(f"feedback-learning.json {key} must be a list")
    scores = data.get("quality_scores")
    if not isinstance(scores, dict):
        failures.append("feedback-learning.json quality_scores must be an object")
        return failures
    missing = sorted(REQUIRED_CRITIC_SCORES - set(scores))
    if missing:
        failures.append("feedback-learning.json quality_scores missing: " + ", ".join(missing))
    for key in sorted(REQUIRED_CRITIC_SCORES & set(scores)):
        value = scores[key]
        if not _is_number(value) or value < 0 or value > 10:
            failures.append(f"feedback-learning.json quality_scores.{key} must be a number from 0 to 10")
    report_path = story / "quality-report.json"
    if report_path.exists():
        report = load_json(report_path)
        critic_scores = report.get("critic_scores") if isinstance(report.get("critic_scores"), dict) else {}
        for key in sorted(REQUIRED_CRITIC_SCORES & set(scores) & set(critic_scores)):
            if _is_number(scores[key]) and _is_number(critic_scores[key]) and abs(float(scores[key]) - float(critic_scores[key])) > 0.01:
                failures.append(f"feedback-learning.json quality_scores.{key} does not match quality-report.json critic_scores.{key}")
    return failures


def validate_story(story: Path, phase: int, mode: str, require_pass: bool = False) -> Dict[str, Any]:
    failures = []
    failures.extend(f"missing artifact: {rel}" for rel in missing_artifacts(story, phase, mode))
    failures.extend(validate_json_artifacts(story, phase, mode))
    if phase >= 1:
        failures.extend(validate_market_brief_shape(story, mode))
    if phase >= 2:
        failures.extend(validate_story_brief_shape(story))
    if phase >= 3:
        failures.extend(validate_adaptation_room_shape(story))
    beat_bible_phase = phase_for_role(mode, "beat")
    scene_draft_phase = phase_for_role(mode, "scene")
    machine_eval_phase = scene_draft_phase
    quality_report_phase = phase_for_role(mode, "critic")
    final_phase = phase_for_role(mode, "final")
    if phase >= beat_bible_phase:
        failures.extend(validate_beat_bible_shape(story, mode=mode))
    if phase >= scene_draft_phase:
        failures.extend(validate_scene_draft_consistency(story, mode=mode))
    metrics = machine_evaluate(story, phase, mode) if phase >= machine_eval_phase else {"failures": []}
    failures.extend(metrics.get("failures", []))
    if phase >= quality_report_phase:
        failures.extend(validate_quality_report_against_machine(story, metrics, phase, mode=mode))
        if require_pass and (story / "quality-report.json").exists():
            report = load_json(story / "quality-report.json")
            if str(report.get("gate_status", "")).lower() != "pass":
                failures.append("quality gate failed: gate_status=fail")
    if phase >= final_phase:
        try:
            manifest = load_story_manifest(story)
        except ValueError as exc:
            failures.append(str(exc))
        else:
            if manifest.get("status") not in {"final", "submitted", "test_fixture"}:
                failures.append("story.yaml status must be final, submitted, or test_fixture")
            pipeline_mode = str(manifest.get("pipeline_mode", mode))
            if pipeline_mode not in {"production", "production_v6", "ultra_short"}:
                failures.append("story.yaml pipeline_mode must be production, production_v6, or ultra_short")
            automation = manifest.get("automation") if isinstance(manifest.get("automation"), dict) else {}
            runner = str(automation.get("runner", ""))
            provider = str(automation.get("provider", ""))
            if (runner == "mock" or provider == "mock") and manifest.get("status") != "test_fixture":
                failures.append("mock runner output cannot be marked as production final; use status: test_fixture")
    if phase >= phase_for_role(mode, "feedback"):
        failures.extend(validate_feedback_learning_shape(story))

    return {
        "story": str(story),
        "phase": phase,
        "mode": mode,
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "machine_metrics": metrics,
    }
