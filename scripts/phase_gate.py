#!/usr/bin/env python3
"""Unified phase gate: auto-repair -> validate -> tomato rubric.

Runs the three checks in order and emits a single JSON payload. Designed to be
invoked by storyforge.py and batch-run scripts.

Exit codes mirror existing storyforge runner conventions:
- 0: pass (all stages green)
- 23: validator failed
- 25: rubric failed
- 26: repair flagged manual review
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from storyforge_lib import phase_for_role

ROOT = Path(__file__).resolve().parents[1]


def _run_repairs(story: Path, phase: int, mode: str) -> Dict[str, Any]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from auto_repair import run_repair_pass  # noqa: E402

    return run_repair_pass(story, phase, mode)


def _checked_payload(proc: subprocess.CompletedProcess[str], label: str) -> Dict[str, Any]:
    """A JSON pass is valid only when its producing process also succeeded."""
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"status": "fail", "failures": [f"{label} output not JSON"], "raw": proc.stdout}
    if not isinstance(payload, dict):
        payload = {"status": "fail", "failures": [f"{label} output must be an object"], "raw": proc.stdout}
    failures = payload.get("failures", [])
    if not isinstance(failures, list):
        failures = [str(failures)]
    if proc.returncode != 0:
        failures.append(f"{label} exited with code {proc.returncode}")
        payload["status"] = "fail"
    elif payload.get("status") not in ("pass", "fail"):
        failures.append(f"{label} output has invalid status")
        payload["status"] = "fail"
    payload["failures"] = failures
    payload["exit_code"] = proc.returncode
    if proc.stderr:
        payload["stderr"] = proc.stderr
    return payload


def _run_validator(story: Path, phase: int, mode: str) -> Dict[str, Any]:
    args = [
        sys.executable,
        str(ROOT / "scripts" / "validate-production-story.py"),
        "--story",
        str(story),
        "--phase",
        str(phase),
        "--mode",
        mode,
        "--json",
    ]
    if phase >= phase_for_role(mode, "critic"):
        args.append("--require-pass")
    proc = subprocess.run(args, capture_output=True, text=True)
    return _checked_payload(proc, "validator")


def _run_rubric(story: Path, threshold: float) -> Dict[str, Any]:
    benchmark = ROOT / "context" / "tomato-benchmark.json"
    if not benchmark.exists():
        return {"status": "skipped", "reason": "no benchmark", "overall_score": 0.0}
    args = [
        sys.executable,
        str(ROOT / "scripts" / "tomato-rubric-score.py"),
        "--story",
        str(story),
        "--threshold",
        str(threshold),
        "--write-report",
        "--json",
    ]
    proc = subprocess.run(args, capture_output=True, text=True)
    return _checked_payload(proc, "rubric")


def run_gate(story: Path, phase: int, mode: str, rubric_threshold: float, run_rubric: bool) -> Dict[str, Any]:
    repairs = _run_repairs(story, phase, mode)
    validator = _run_validator(story, phase, mode)

    rubric: Dict[str, Any] = {"status": "skipped"}
    if run_rubric and validator.get("status") == "pass" and phase >= phase_for_role(mode, "final"):
        rubric = _run_rubric(story, rubric_threshold)

    overall_status = "pass"
    failures: List[str] = []
    if repairs.get("status") == "manual_review_required":
        overall_status = "manual_review"
        failures.append(f"repair manual review: {repairs.get('blocking')}")
    if validator.get("status") != "pass":
        overall_status = "validator_fail"
        failures.extend(validator.get("failures", []) or [])
    if run_rubric and rubric.get("status") == "fail":
        overall_status = "rubric_fail" if overall_status == "pass" else overall_status
        failures.append(f"rubric below threshold: {rubric.get('overall_score')}")

    payload = {
        "story": str(story),
        "phase": phase,
        "mode": mode,
        "status": overall_status,
        "failures": failures,
        "repairs": repairs,
        "validator": validator,
        "rubric": rubric,
    }
    out_path = story / "phase-gate-report.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--story", required=True)
    parser.add_argument("--phase", required=True, type=int)
    parser.add_argument("--mode", default="production")
    parser.add_argument("--rubric-threshold", type=float, default=float(os.environ.get("STORYFORGE_RUBRIC_THRESHOLD", "8.0")))
    parser.add_argument("--no-rubric", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run_gate(
        Path(args.story),
        args.phase,
        args.mode,
        args.rubric_threshold,
        run_rubric=not args.no_rubric,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"phase-gate status={result['status']} phase={args.phase}")

    if result["status"] == "pass":
        return 0
    if result["status"] == "validator_fail":
        return 23
    if result["status"] == "rubric_fail":
        return 25
    if result["status"] == "manual_review":
        return 26
    return 1


if __name__ == "__main__":
    sys.exit(main())
