#!/usr/bin/env python3
"""Run StoryForge V4 Phase 1 for pending corpus entries with bounded parallelism."""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import datetime as dt
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "corpus"


def load_manifest(corpus: Path) -> list[dict[str, Any]]:
    manifest = corpus / "_manifest.tsv"
    if not manifest.exists():
        raise FileNotFoundError(f"manifest not found: {manifest}")
    rows: list[dict[str, Any]] = []
    for line in manifest.read_text(encoding="utf-8").splitlines()[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        slug, filename, word_count = parts[:3]
        rows.append(
            {
                "slug": slug,
                "filename": filename,
                "word_count": int(word_count) if word_count.isdigit() else 0,
                "story": corpus / slug,
            }
        )
    return rows


def pending_entries(
    corpus: Path,
    limit: int | None,
    min_word_count: int,
    max_word_count: int | None,
    only_slugs: set[str],
    skip_corrupt_sources: bool,
) -> list[dict[str, Any]]:
    rows = []
    for row in load_manifest(corpus):
        story = Path(row["story"])
        if only_slugs and row["slug"] not in only_slugs:
            continue
        if (story / "dissection.md").exists():
            continue
        wc = int(row["word_count"])
        if wc < min_word_count:
            continue
        if max_word_count is not None and wc > max_word_count:
            continue
        if skip_corrupt_sources and looks_corrupt(story / "source.md"):
            continue
        rows.append(row)
    rows.sort(key=lambda item: (int(item["word_count"]), str(item["slug"])))
    if limit is not None:
        rows = rows[:limit]
    return rows


def looks_corrupt(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    body = text.split("\n---\n", 1)[-1]
    return body.count("\ufffd") > 20 or "\x00" in body[:1000]


def run_one(row: dict[str, Any], runner: str, model: str, timeout: int, heartbeat: int) -> dict[str, Any]:
    started = time.time()
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "storyforge.py"),
        "run",
        "--story",
        str(row["story"]),
        "--from-phase",
        "1",
        "--to-phase",
        "1",
        "--runner",
        runner,
        "--heartbeat-seconds",
        str(heartbeat),
    ]
    if model:
        cmd.extend(["--model", model])
    with subprocess.Popen(
            cmd,
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # This dispatcher is threaded: do not use preexec_fn=os.setsid.
            start_new_session=os.name == "posix",
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout if timeout > 0 else None)
            exit_code = process.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            # Kill only this invocation's session group, including its runner.
            # Killing the pipeline parent alone leaves descendants running.
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            # communicate() reaps the parent and returns decoded full streams.
            # TimeoutExpired.output itself is bytes even when text=True.
            stdout, stderr = process.communicate()
            exit_code = 124
            timed_out = True

    ok = exit_code == 0 and (Path(row["story"]) / "dissection.md").exists()
    return {
        "slug": row["slug"],
        "filename": row["filename"],
        "word_count": row["word_count"],
        "story": str(row["story"]),
        "ok": ok,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_s": round(time.time() - started, 3),
        "stdout_tail": stdout[-2000:],
        "stderr_tail": stderr[-2000:],
        "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


def append_jsonl(path: Path, payload: dict[str, Any], lock: threading.Lock) -> None:
    with lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--runner", default="agent")
    parser.add_argument("--model", default="")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-word-count", type=int, default=0)
    parser.add_argument("--max-word-count", type=int, default=None)
    parser.add_argument("--slug", action="append", default=[], help="run only this slug; repeatable")
    parser.add_argument("--skip-corrupt-sources", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--heartbeat-seconds", type=int, default=60)
    parser.add_argument("--log", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    corpus = Path(args.corpus)
    rows = pending_entries(
        corpus,
        args.limit,
        args.min_word_count,
        args.max_word_count,
        set(args.slug),
        args.skip_corrupt_sources,
    )
    log_path = Path(args.log) if args.log else ROOT / "runs" / f"corpus-phase1-parallel-{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    print(
        json.dumps(
            {
                "event": "planned",
                "count": len(rows),
                "jobs": args.jobs,
                "runner": args.runner,
                "log": str(log_path),
            },
            ensure_ascii=False,
        )
    )
    if args.dry_run:
        for row in rows[:50]:
            print(f"{row['slug']}\t{row['word_count']}\t{row['filename']}")
        if len(rows) > 50:
            print(f"... +{len(rows) - 50} more")
        return 0

    ok_count = 0
    fail_count = 0
    lock = threading.Lock()
    started = time.time()
    with futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as executor:
        future_map = {
            executor.submit(run_one, row, args.runner, args.model, args.timeout_seconds, args.heartbeat_seconds): row
            for row in rows
        }
        for index, future in enumerate(futures.as_completed(future_map), start=1):
            row = future_map[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 - record and continue batch
                result = {
                    "slug": row["slug"],
                    "filename": row["filename"],
                    "word_count": row["word_count"],
                    "story": str(row["story"]),
                    "ok": False,
                    "exit_code": -1,
                    "timed_out": False,
                    "duration_s": 0,
                    "error": repr(exc),
                    "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
                }
            append_jsonl(log_path, result, lock)
            if result.get("ok"):
                ok_count += 1
                status = "ok"
            else:
                fail_count += 1
                status = "fail"
            elapsed = round(time.time() - started, 1)
            print(
                f"[{index}/{len(rows)}] {status} {result['slug']} "
                f"{result.get('duration_s', 0)}s elapsed={elapsed}s",
                flush=True,
            )

    update = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "update-corpus-index.py"), "--corpus", str(corpus)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    print(update.stdout, end="")
    if update.returncode != 0:
        print(update.stderr, file=sys.stderr, end="")
    print(json.dumps({"event": "done", "ok": ok_count, "fail": fail_count, "log": str(log_path)}, ensure_ascii=False))
    return 0 if fail_count == 0 and update.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
