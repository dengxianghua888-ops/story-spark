#!/usr/bin/env python3
"""Apply a StoryForge model artifact bundle to a story directory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from storyforge_lib import (apply_artifact_bundle, normalize_pipeline_mode, phase_count,
                            repo_root, read_text, write_json)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--story", required=True)
    parser.add_argument("--phase", required=True, type=int, choices=range(1, 10))
    parser.add_argument("--mode", default="v4")
    parser.add_argument("--bundle", required=True, help="Path to model output bundle")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    try:
        args.mode = normalize_pipeline_mode(args.mode)
        last_phase = phase_count(args.mode)
        if not 1 <= args.phase <= last_phase:
            raise ValueError(f"--phase ({args.phase}) must be within 1-{last_phase} for mode {args.mode}")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    story = Path(args.story)
    bundle = Path(args.bundle)
    run_dir = Path(args.run_dir)
    if not story.is_dir():
        print(f"story directory does not exist: {story}", file=sys.stderr)
        return 1
    if not bundle.exists():
        print(f"bundle does not exist: {bundle}", file=sys.stderr)
        return 1

    try:
        report = apply_artifact_bundle(story, args.phase, read_text(bundle), run_dir, repo_root(), args.mode)
    except ValueError as exc:
        failure = {"phase": args.phase, "status": "failed", "error": str(exc)}
        write_json(run_dir / f"phase{args.phase}.parse-report.json", failure)
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
