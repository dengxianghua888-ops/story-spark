"""Repair deterministic direct-submission packaging issues."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from production_quality import count_paywall_rows, required_paywall_nodes, target_range


def _count_nonspace(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _fix_final_headings(path: Path) -> bool:
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    changed = False
    for index, line in enumerate(lines):
        if index == 0:
            continue
        if re.match(r"^#\s*第\s*\d+\s*章\s*$", line):
            lines[index] = "#" + line
            changed = True
    if changed:
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return changed


def _paywall_section_bounds(text: str) -> tuple[int, int] | None:
    match = re.search(r"^##+\s*付费节点地图.*$", text, flags=re.MULTILINE)
    if not match:
        return None
    start = match.end()
    next_heading = re.search(r"\n##+\s+", text[start:])
    end = start + next_heading.start() if next_heading else len(text)
    return start, end


def _paywall_review(path: Path, final_chars: int, target_min: int) -> Dict[str, Any]:
    """Missing creative content needs editorial evidence, not fabricated rows."""
    required = required_paywall_nodes(final_chars, target_min)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    bounds = _paywall_section_bounds(text)
    actual = count_paywall_rows(text[bounds[0]:bounds[1]]) if bounds else 0
    return {"required": required, "actual": actual}


def run(story: Path, mode: str = "production") -> Dict[str, Any]:
    final_path = story / "final.md"
    submission_path = story / "tomato-submission.md"
    changes = []
    if _fix_final_headings(final_path):
        changes.append("chapter_headings_h1_to_h2")
    final_chars = _count_nonspace(final_path.read_text(encoding="utf-8")) if final_path.exists() else 0
    target = target_range(story, mode)
    paywall = _paywall_review(submission_path, final_chars, target["target_min"])
    needs_review = paywall["actual"] < paywall["required"]
    return {
        "name": "direct_submission",
        "status": "manual_review_required" if needs_review else "ok",
        "paywall_map": paywall,
        "manual_review": ["Add natural paywall nodes grounded in this story; submission text was left unchanged."] if needs_review else [],
        "changes": changes,
    }
