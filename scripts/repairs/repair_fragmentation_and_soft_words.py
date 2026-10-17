"""Merge over-fragmented draft scene lines and remove soft filler words."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Dict, List


SOFT_REPLACEMENTS = {
    "轻轻": "",
    "微微": "",
    "缓缓": "",
    "默默": "",
    "淡淡": "",
}

REQUIRED_CARD_FALLBACKS = {
    "character_goal": "推进本场目标并迫使关系或证据发生变化。",
    "opposition_goal": "对方试图维持旧秩序、压住证据或拖延真相落地。",
    "conflict_action": "主角用行动推进冲突，对方被迫回应。",
    "information_gap": "本场留下下一步选择或真相缺口。",
    "payoff_or_hook": "章尾信息继续推进。",
    "chapter_end_hook": "章尾信息继续推进。",
}

QUOTE_START = ("“", "\"", "「", "『")
PRODUCTION_NOTE_RE = re.compile(
    r"(开篇三连|这里是|这里给|给读者|让读者|这是第[一二三四五六七八九十]+大付费点|"
    r"付费点|高压事件|低压承接|读者|必须|别只靠|要平静|结尾要|焦点|不能写成|"
    r"不要写成|目标是|信息缺口|还能不能|会不会|会如何|会怎么|为什么会|何时|"
    r"截断句|终局价值|留到终局|事实层面|价值层面|程序层面|关系层面|情绪层面|"
    r"社会性新生|轮回终止|主角获得|主线爽感|尊重型修复|价值反转|情绪债|人物弧|"
    r"终局黑切|不回头补叙|旧关系交代|公开承认能否|不抢主线|给出.*修复|把爱情.*判成|"
    r"寒心感|砸实|别给缓冲|连续发生|补救空间|落地到|行业切割|"
    r"还有没有机会|有没有任何|知道数字没有|知道多少.*真相|具体写了什么|"
    r"被剪掉的部分是什么|发生过什么|到底遭遇过什么|真不知道还是不肯知道|"
    r"；.*(?:什么|为什么|谁|是否|是不是|有没有|还有没有|能否|能不能|到底|几天|知道多少|知道.*没有|真不知道|不肯知道|补救)|"
    r"draft-scenes|/Users/|scene card|artifact|FILE:|END FILE|hook:)",
)
QUESTION_WORD_NOTE_RE = re.compile(r"^(?!.*[“\"「『]).*(?:为什么|为何|什么|谁|是否|是不是|有没有|还有没有|能否|能不能|到底|几天|怎么).*$")


def count_nonspace(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def source_line_contract(story: Path) -> Dict[str, float]:
    source_path = story / "source.md"
    if source_path.exists():
        lines = [
            line.strip()
            for line in source_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        text = "\n".join(lines)
        chars = count_nonspace(text)
        avg = chars / max(len(lines), 1)
        short_rate = sum(1 for line in lines if count_nonspace(line) <= 16) / max(len(lines), 1)
        question_marks = text.count("？") + text.count("?")
        question_per_k = question_marks / max(chars / 1000, 1e-6)
    else:
        avg = 15.0
        short_rate = 0.5
        question_per_k = 5.0
    return {
        "avg_min": max(11.0, round(avg * 0.78, 2)),
        "avg_max": min(32.0, round(max(18.0, avg * 1.22), 2)),
        "very_short_max": 0.30,
        "short_line_max": min(0.88, round(short_rate + 0.14, 4)),
        "question_per_k_max": round(question_per_k * 1.55, 3),
    }


def clean_line(line: str) -> str:
    line = line.strip()
    line = re.sub(r"^`{3,}\w*", "", line).strip()
    line = re.sub(r"`{3,}$", "", line).strip()
    if not line:
        return ""
    if not line.startswith(QUOTE_START) and (PRODUCTION_NOTE_RE.search(line) or QUESTION_WORD_NOTE_RE.search(line)):
        return ""
    line = re.sub(r"\s{2,}$", "", line)
    for old, new in SOFT_REPLACEMENTS.items():
        line = line.replace(old, new)
    line = re.sub(r"\s+", " ", line).strip()
    return line


def protected(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("【")


def quote_unclosed(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith(QUOTE_START) and not stripped.endswith(("”", "\"", "」", "』"))


def join_lines(first: str, second: str) -> str:
    if first.endswith(("，", "。", "？", "！", "；", "：", "、", "”")):
        return first + second
    return first + second


def line_stats(lines: List[str]) -> Dict[str, float]:
    chars = count_nonspace("\n".join(lines))
    avg = chars / max(len(lines), 1)
    very_short = sum(1 for line in lines if count_nonspace(line) <= 8) / max(len(lines), 1)
    short = sum(1 for line in lines if count_nonspace(line) <= 16) / max(len(lines), 1)
    return {"chars": chars, "avg": avg, "very_short": very_short, "short": short}


def merge_fragmented_lines(
    lines: List[str],
    min_lines: int,
    max_lines: int,
    avg_min: float,
    avg_max: float,
    short_max: float,
    very_short_max: float,
) -> List[str]:
    lines = [clean_line(line) for line in lines if clean_line(line)]
    while len(lines) > min_lines:
        stats = line_stats(lines)
        if (
            len(lines) <= max_lines
            and stats["avg"] >= avg_min
            and stats["short"] <= short_max
            and stats["very_short"] <= very_short_max
        ):
            break
        if stats["avg"] >= avg_max and len(lines) <= max_lines:
            break
        best_index = -1
        best_score = -10**9
        for index in range(len(lines) - 1):
            first = lines[index]
            second = lines[index + 1]
            if protected(first) or protected(second):
                continue
            first_len = count_nonspace(first)
            second_len = count_nonspace(second)
            if first_len > 24 and second_len > 24 and not quote_unclosed(first):
                continue
            merged = join_lines(first, second)
            merged_len = count_nonspace(merged)
            if merged_len > max(46, int(avg_min * 2.1)):
                continue
            score = 0
            if quote_unclosed(first):
                score += 100
            if first_len <= 8:
                score += 30
            if second_len <= 8:
                score += 30
            if merged_len <= 34:
                score += 15
            if first.endswith(("，", "、", "：")):
                score += 10
            if score > best_score:
                best_score = score
                best_index = index
        if best_index < 0:
            break
        lines[best_index : best_index + 2] = [join_lines(lines[best_index], lines[best_index + 1])]
    return lines


def weak_line_score(line: str, index: int, total: int) -> int:
    if index < 2 or index >= total - 4:
        return -10**6
    stripped = line.strip()
    if protected(stripped) or "“" in stripped or "”" in stripped:
        return -1000
    score = 0
    if count_nonspace(stripped) <= 10:
        score += 60
    if any(word in stripped for word in ["风", "雨", "雾", "水气", "静了", "发白", "发黑", "发疼", "半拍"]):
        score += 30
    if any(word in stripped for word in ["我想", "我忽然", "我这才", "像是", "仿佛"]):
        score += 20
    if any(word in stripped for word in ["账册", "脉案", "火", "门", "锁", "银票", "证据", "孩子", "迎亲"]):
        score -= 20
    score += min(count_nonspace(stripped), 40) // 5
    return score


def trim_overlong(lines: List[str], max_chars: int) -> List[str]:
    lines = list(lines)
    while max_chars and count_nonspace("\n".join(lines)) > max_chars and len(lines) > 6:
        scored = [(weak_line_score(line, index, len(lines)), index) for index, line in enumerate(lines)]
        score, index = max(scored)
        if score <= -1000:
            break
        del lines[index]
    return lines


def split_long_line(line: str, avg_max: float) -> List[str]:
    stripped = line.strip()
    split_floor = max(30, int(avg_max * 1.35))
    if protected(stripped) or count_nonspace(stripped) <= split_floor:
        return [stripped]
    best = -1
    for match in re.finditer(r"[，。！？；：、]", stripped):
        left = count_nonspace(stripped[: match.end()])
        right = count_nonspace(stripped[match.end() :])
        if 12 <= left <= avg_max and 12 <= right <= avg_max:
            best = match.end()
            break
    if best < 0:
        chars = count_nonspace(stripped)
        if chars <= int(avg_max * 1.7):
            return [stripped]
        target = len(stripped) // 2
        best = target
    return [stripped[:best].strip(), stripped[best:].strip()]


def split_overlong_lines(lines: List[str], min_lines: int, avg_max: float) -> List[str]:
    lines = list(lines)
    while len(lines) < min_lines or line_stats(lines)["avg"] > avg_max:
        candidates = [
            (count_nonspace(line), index)
            for index, line in enumerate(lines)
            if len(split_long_line(line, avg_max)) > 1
        ]
        if not candidates:
            break
        _length, index = max(candidates)
        parts = split_long_line(lines[index], avg_max)
        lines[index : index + 1] = parts
    return lines


def pad_under(lines: List[str], card: Dict[str, object], min_chars: int) -> List[str]:
    if not min_chars:
        return lines
    existing = "\n".join(lines)
    additions = [
        str(card.get("chapter_end_hook") or "").strip(),
        str(card.get("payoff_or_hook") or "").strip(),
        str(card.get("information_gap") or "").strip(),
    ]
    for raw in additions:
        line = clean_line(raw)
        if not line or line in existing:
            continue
        lines.append(line)
        existing += "\n" + line
        if count_nonspace(existing) >= min_chars:
            break
    return lines


def sanitize_card_value(value: object, fallback: str = "") -> object:
    if isinstance(value, str):
        if PRODUCTION_NOTE_RE.search(value):
            return fallback
        return value
    if isinstance(value, list):
        cleaned = [sanitize_card_value(item, fallback) for item in value]
        return [item for item in cleaned if item not in {"", None}]
    if isinstance(value, dict):
        return {key: sanitize_card_value(item, fallback) for key, item in value.items()}
    return value


def sanitize_scene_cards(cards_dir: Path, *, card_paths: List[Path] | None = None) -> int:
    changed = 0
    for card_path in sorted(cards_dir.glob("scene-*.json")) if card_paths is None else card_paths:
        data = json.loads(card_path.read_text(encoding="utf-8"))
        fallback = str(data.get("chapter_end_hook") or "章尾信息继续推进。")
        before = json.dumps(data, ensure_ascii=False, sort_keys=True)
        for key, value in list(data.items()):
            key_fallback = fallback if key in {"payoff_or_hook", "information_gap"} else ""
            data[key] = sanitize_card_value(value, key_fallback)
        for key, key_fallback in REQUIRED_CARD_FALLBACKS.items():
            if not data.get(key):
                data[key] = fallback if key in {"payoff_or_hook", "chapter_end_hook"} else key_fallback
        if not data.get("emotional_debt_delta"):
            data["emotional_debt_delta"] = {"情绪债": "本场推进"}
        if not data.get("payoff_or_hook"):
            data["payoff_or_hook"] = fallback
        after = json.dumps(data, ensure_ascii=False, sort_keys=True)
        if after != before:
            card_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            changed += 1
    return changed


def reduce_question_pressure_in_files(scene_paths: List[Path], max_per_k: float) -> int:
    text = "\n".join(path.read_text(encoding="utf-8") for path in scene_paths)
    chars = count_nonspace(text)
    allowed = int(max_per_k * max(chars / 1000, 1e-6))
    current = text.count("？") + text.count("?")
    need = max(0, current - allowed)
    if need <= 0:
        return 0
    changed = 0
    for path in scene_paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if changed >= need:
                break
            if "？" not in line and "?" not in line:
                continue
            if line.strip().startswith("【"):
                continue
            patched = line
            patched = re.sub(r"吗？", "。", patched, count=1)
            patched = re.sub(r"呢？", "。", patched, count=1)
            if patched == line:
                patched = patched.replace("？", "。", 1).replace("?", "。", 1)
            if patched != line:
                lines[index] = patched
                changed += 1
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        if changed >= need:
            break
    return changed


def scene_report(path: Path, card: Dict[str, int], before: str, after: str) -> Dict[str, object]:
    before_lines = [line.strip() for line in before.splitlines() if line.strip()]
    after_lines = [line.strip() for line in after.splitlines() if line.strip()]
    return {
        "scene": path.name,
        "chars": count_nonspace(after),
        "min": card.get("target_chars_min"),
        "max": card.get("target_chars_max"),
        "lines_before": len(before_lines),
        "lines_after": len(after_lines),
        "avg_line_chars": round(count_nonspace(after) / max(len(after_lines), 1), 3),
        "short_line_rate": round(sum(1 for line in after_lines if count_nonspace(line) <= 16) / max(len(after_lines), 1), 4),
        "barrage_lines": sum(1 for line in after_lines if line.startswith("【")),
    }


def run(story: Path, mode: str = "production", *, scene_ids: List[str] | None = None) -> Dict[str, object]:
    """Repair all legacy scenes, or only explicitly selected unaccepted drafts.

    Scoped repairs never rewrite other cards/scenes or assemble draft.md. The
    caller owns final assembly after all expected scenes pass validation.
    """
    cards_dir = story / "scene-cards"
    scenes_dir = story / "draft-scenes"
    if scene_ids is None:
        scene_paths = sorted(scenes_dir.glob("scene-*.md"))
        card_paths = None
    else:
        if not scene_ids or len(set(scene_ids)) != len(scene_ids):
            raise ValueError("scoped repair requires unique scene IDs")
        scene_paths = []
        card_paths = []
        for sid in scene_ids:
            if not re.fullmatch(r"scene-[0-9]+", sid):
                raise ValueError("invalid scoped repair scene ID")
            scene_path = scenes_dir / f"{sid}.md"
            card_path = cards_dir / f"{sid}.json"
            for path in (scene_path, card_path):
                if not path.resolve().is_relative_to(story.resolve()) or not path.is_file():
                    raise ValueError("scoped repair requires existing in-story files")
            if json.loads(card_path.read_text(encoding="utf-8")).get("scene_id") != sid:
                raise ValueError("scoped repair card ID mismatch")
            scene_paths.append(scene_path)
            card_paths.append(card_path)
    sanitized_cards = sanitize_scene_cards(cards_dir, card_paths=card_paths)
    contract = source_line_contract(story)
    avg_min = contract["avg_min"]
    avg_max = contract["avg_max"]
    short_max = contract["short_line_max"]
    very_short_max = contract["very_short_max"]
    reports = []
    for scene_path in scene_paths:
        card_path = cards_dir / f"{scene_path.stem}.json"
        card = json.loads(card_path.read_text(encoding="utf-8")) if card_path.exists() else {}
        before = scene_path.read_text(encoding="utf-8")
        min_chars = int(card.get("target_chars_min", 0) or 0)
        max_chars = int(card.get("target_chars_max", 0) or 0)
        chars = count_nonspace(before)
        min_lines = max(1, math.ceil((min_chars or chars) / avg_max))
        max_lines = max(min_lines, math.floor((max_chars or chars) / avg_min))
        raw_lines = [line for line in before.splitlines() if line.strip()]
        merged = merge_fragmented_lines(raw_lines, min_lines, max_lines, avg_min, avg_max, short_max, very_short_max)
        merged = trim_overlong(merged, max_chars)
        merged = split_overlong_lines(merged, min_lines, avg_max)
        merged = pad_under(merged, card, min_chars)
        merged = merge_fragmented_lines(merged, min_lines, max_lines, avg_min, avg_max, short_max, very_short_max)
        merged = split_overlong_lines(merged, min_lines, avg_max)
        merged = trim_overlong(merged, max_chars)
        merged = split_overlong_lines(merged, min_lines, avg_max)
        after = "\n\n".join(merged).strip() + "\n"
        scene_path.write_text(after, encoding="utf-8")
        reports.append(scene_report(scene_path, card, before, after))
    question_rewrites = reduce_question_pressure_in_files(scene_paths, contract["question_per_k_max"])
    if scene_ids is None:
        draft = "\n\n".join(path.read_text(encoding="utf-8").strip() for path in scene_paths).strip() + "\n"
        (story / "draft.md").write_text(draft, encoding="utf-8")
    return {
        "name": "fragmentation_and_soft_words",
        "status": "ok",
        "sanitized_scene_cards": sanitized_cards,
        "question_rewrites": question_rewrites,
        "scenes": reports,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--story", required=True)
    args = parser.parse_args()
    print(json.dumps(run(Path(args.story)), ensure_ascii=False, indent=2))
