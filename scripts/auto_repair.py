#!/usr/bin/env python3
"""Auto-repair orchestrator.

Runs the appropriate repairers for the given phase and writes
``repair-report.json`` to the story directory. Designed to be called by
phase_gate.py before validate-production-story.py.

Repairer mapping (production / ultra_short modes):
- phase 5: scene_length, forbidden_scan
- phase 6: quality_report_sync (only if quality-report.json exists)
- phase 7: mobile_paragraphs, quality_report_sync, metadata
- phase 8: metadata
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from storyforge_lib import phase_for_role, normalize_pipeline_mode

from repairs import (
    repair_direct_submission,
    repair_forbidden_scan,
    repair_fragmentation_and_soft_words,
    repair_metadata,
    repair_mobile_paragraphs,
    repair_quality_report_sync,
    repair_scene_length,
    repair_source_rhythm,
)


PHASE_REPAIRS: Dict[int, List[Any]] = {
    5: [repair_fragmentation_and_soft_words, repair_scene_length, repair_source_rhythm, repair_forbidden_scan],
    6: [repair_quality_report_sync],
    7: [repair_direct_submission, repair_mobile_paragraphs, repair_quality_report_sync, repair_metadata],
    8: [repair_metadata],
}


def run_repair_pass(story: Path, phase: int, mode: str = "production") -> Dict[str, Any]:
    repairers = []
    for role, legacy_phase in [("scene", 5), ("critic", 6), ("final", 7), ("feedback", 8)]:
        if role == "feedback" and normalize_pipeline_mode(mode) == "v4":
            continue
        if phase == phase_for_role(mode, role):
            repairers = PHASE_REPAIRS[legacy_phase]
            break
    results: List[Dict[str, Any]] = []
    blocking: List[str] = []
    for module in repairers:
        try:
            outcome = module.run(story, mode, phase=phase) if module is repair_quality_report_sync else module.run(story, mode)
        except Exception as exc:  # never let a repairer take down the pipeline
            outcome = {"name": getattr(module, "__name__", "unknown"), "status": "fail", "reason": str(exc)}
        results.append(outcome)
        if outcome.get("status") == "manual_review_required":
            blocking.append(outcome.get("name", "unknown"))

    report = {
        "phase": phase,
        "mode": mode,
        "status": "ok" if not blocking else "manual_review_required",
        "blocking": blocking,
        "results": results,
    }
    out_path = story / "repair-report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--story", required=True)
    parser.add_argument("--phase", required=True, type=int)
    parser.add_argument("--mode", default="production")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_repair_pass(Path(args.story), args.phase, args.mode)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"repair pass status={result['status']} blocking={result['blocking']}")
    # Repairs do not fail the run on their own - phase_gate decides.
    return 0


if __name__ == "__main__":
    sys.exit(main())
