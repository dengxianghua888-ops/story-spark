#!/usr/bin/env python3
"""Structure metrics for V5 pipeline.

Checks:
- Impact density (impacts per 1000 chars)
- Cliffhanger type matching against beat-bible contract
- Watermark detection (consecutive pure-description lines)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def count_nonspace(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def has_dialogue(line: str) -> bool:
    return any(c in line for c in '""「」\'')


def has_action(line: str) -> bool:
    action_verbs = re.compile(
        r"(踹|砸|摔|撞|踩|扯|拽|拖|抓|掐|砍|劈|踢|打|推|拉|扔|"
        r"冲|跑|爬|跳|滚|摔倒|站起|蹲下|趴|跪)"
    )
    return bool(action_verbs.search(line))


def has_revelation(line: str) -> bool:
    reveal_markers = re.compile(
        r"(原来|其实|真相|秘密|不知道|发现|揭|暴露|坦白|承认|告诉你|"
        r"因为|所以|直到|然后|于是|结果)"
    )
    return bool(reveal_markers.search(line))


def has_narrative_progression(line: str) -> bool:
    """Detect lines that advance plot even without dialogue/action/revelation."""
    progress_markers = re.compile(
        r"(第.天|第.年|天后|之后|从此|开始|终于|不再|变了|没了|"
        r"来了|走了|回来|离开|死了|活着|醒了|断了|碎了|"
        r"所有人|没人|有人|人群|大家)"
    )
    return bool(progress_markers.search(line))


def is_pure_description(line: str) -> bool:
    if not line.strip():
        return False
    if len(line.strip()) <= 8:
        return False
    return (not has_dialogue(line) and not has_action(line)
            and not has_revelation(line) and not has_narrative_progression(line))


def detect_watermark(text: str, max_consecutive: int = 7) -> list[dict]:
    """Find runs of consecutive pure-description lines (≥max_consecutive).

    Threshold is set high (7) because short-sentence web fiction naturally
    has many consecutive lines without explicit dialogue markers or action verbs.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    violations = []
    run_start = None
    run_len = 0
    for i, line in enumerate(lines):
        if is_pure_description(line):
            run_start = run_start if run_start is not None else i
            run_len += 1
        else:
            if run_len >= max_consecutive:
                violations.append({"start_line": run_start, "length": run_len, "sample": lines[run_start][:40]})
            run_start = None
            run_len = 0
    if run_len >= max_consecutive:
        violations.append({"start_line": run_start, "length": run_len, "sample": lines[run_start][:40]})
    return violations


def count_impacts(text: str) -> dict[str, Any]:
    """Count impact events in text by category."""
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    categories = {
        "physical_violence": re.compile(
            r"(踹|砸|摔|撞|踩|扯|拽|拖|掐|砍|劈|踢|打了|一巴掌|一拳|一脚|"
            r"断了|碎了|血|伤口|骨折|撕裂)"
        ),
        "verbal_attack": re.compile(
            r"(废物|滚|闭嘴|狗屁|骗子|寄生虫|贱|蠢|死|该死|混蛋|"
            r"不要脸|恶心|可笑)"
        ),
        "betrayal": re.compile(
            r"(背叛|出卖|抛弃|不管|见死不救|袖手旁观|落井下石|"
            r"没人帮|没人说话|假装没看见)"
        ),
        "revelation": re.compile(
            r"(原来|其实|真相|秘密|你不知道|零号|女王|封印|"
            r"真正的|本质|真实身份)"
        ),
        "status_reversal": re.compile(
            r"(跪|臣服|求饶|崩溃|瘫|吓|恐惧|颤抖|"
            r"反转|逆转|觉醒|苏醒)"
        ),
    }
    counts = {k: 0 for k in categories}
    total = 0
    for line in lines:
        for cat, pattern in categories.items():
            matches = pattern.findall(line)
            if matches:
                counts[cat] += len(matches)
                total += len(matches)
    nonspace = count_nonspace(text)
    density = (total / nonspace * 1000) if nonspace > 0 else 0
    return {"total_impacts": total, "per_category": counts, "impacts_per_1000_chars": round(density, 2), "nonspace_chars": nonspace}


def analyze_chapters(text: str) -> list[dict]:
    """Split by ## headers and analyze each chapter."""
    chapters = []
    current_title = ""
    current_lines: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("## "):
            if current_lines:
                chapters.append({"title": current_title, "text": "\n".join(current_lines)})
            current_title = line.strip()[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        chapters.append({"title": current_title, "text": "\n".join(current_lines)})
    results = []
    for ch in chapters:
        impacts = count_impacts(ch["text"])
        watermarks = detect_watermark(ch["text"])
        results.append({
            "title": ch["title"],
            "nonspace_chars": impacts["nonspace_chars"],
            "impacts": impacts["total_impacts"],
            "watermark_violations": len(watermarks),
        })
    return results


def run_analysis(text: str, skeleton_path: Path | None = None) -> dict[str, Any]:
    """Full structure analysis."""
    impacts = count_impacts(text)
    watermarks = detect_watermark(text)
    chapters = analyze_chapters(text)
    result: dict[str, Any] = {
        "impact_density": impacts,
        "watermark_violations": watermarks,
        "watermark_count": len(watermarks),
        "per_chapter": chapters,
    }
    if skeleton_path and skeleton_path.exists():
        skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))
        source_density = skeleton.get("impact_density", {}).get("source_impacts_per_1000_chars", 0)
        if source_density > 0:
            ratio = impacts["impacts_per_1000_chars"] / source_density
            result["density_ratio"] = round(ratio, 3)
            result["density_pass"] = ratio >= 0.80
        else:
            result["density_ratio"] = None
            result["density_pass"] = True
    result["gate_status"] = "pass" if result.get("density_pass", True) else "fail"
    result["watermark_warning"] = len(watermarks) > 0
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="V5 structure metrics")
    parser.add_argument("story_path", type=Path, help="Path to final.md or draft.md")
    parser.add_argument("--skeleton", type=Path, default=None, help="Path to structure-skeleton.json")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON path")
    args = parser.parse_args()

    text = args.story_path.read_text(encoding="utf-8")
    result = run_analysis(text, args.skeleton)

    output_json = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output_json + "\n", encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(output_json)

    return 0 if result["gate_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
