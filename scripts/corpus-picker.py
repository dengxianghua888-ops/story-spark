#!/usr/bin/env python3
"""Random corpus picker.

Selects N corpus entries (stratified by genre to avoid clustering) and
scaffolds matching story directories under stories/ for batch runs.

Each new story gets:
- source.md (copied from the picked corpus entry)
- story.yaml (slug, status=phase1, source_policy.access=denied)
- pick-card.json (records the seed, picked corpus_slug, genre, mechanisms)

Already-existing slugs in stories/ are skipped.
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as _dt
import json
import os
import random
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
CORPUS_INDEX = ROOT / "corpus" / "_index.json"
PICKER_HISTORY = ROOT / "runs" / "picker-history.jsonl"
STORIES_DIR = ROOT / "stories"


def _load_index() -> List[Dict[str, Any]]:
    data = json.loads(CORPUS_INDEX.read_text(encoding="utf-8"))
    return [e for e in data.get("entries", []) if e.get("source_path")]


def _load_recent(n: int) -> List[str]:
    if not PICKER_HISTORY.exists() or n <= 0:
        return []
    seen: List[str] = []
    for line in PICKER_HISTORY.read_text(encoding="utf-8").splitlines()[-n:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        seen.extend(row.get("corpus_slugs", []))
    return seen


def _stratified_sample(entries: List[Dict[str, Any]], count: int, rng: random.Random) -> List[Dict[str, Any]]:
    by_genre: Dict[str, List[Dict[str, Any]]] = {}
    for entry in entries:
        by_genre.setdefault(entry.get("genre") or "_unknown", []).append(entry)
    for bucket in by_genre.values():
        rng.shuffle(bucket)
    rotation = list(by_genre.keys())
    rng.shuffle(rotation)
    picks: List[Dict[str, Any]] = []
    while len(picks) < count and any(by_genre.values()):
        progressed = False
        for genre in rotation:
            if len(picks) >= count:
                break
            bucket = by_genre.get(genre) or []
            if not bucket:
                continue
            picks.append(bucket.pop())
            progressed = True
        if not progressed:
            break
    return picks


def _publish_scaffold(staged: Path, story: Path) -> None:
    """Atomically publish a new directory without replacing any existing entry."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                           ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(-100, os.fsencode(staged), -100, os.fsencode(story), 1)  # RENAME_NOREPLACE
    elif sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(staged), os.fsencode(story), 4)  # Darwin RENAME_EXCL
    else:
        raise OSError("Atomic new-story publication requires Linux renameat2 or macOS renamex_np")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(story))


def _scaffold_story(entry: Dict[str, Any], slug_prefix: str, run_id: str) -> Path:
    slug = f"{slug_prefix}_{entry['slug']}"
    story = STORIES_DIR / slug
    if story.exists() or story.is_symlink():
        return story
    story.parent.mkdir(parents=True, exist_ok=True)
    # Keep failed attempts private and separate from normal story paths. A retry
    # constructs a fresh candidate; it never treats an incomplete attempt as legacy.
    staged = Path(tempfile.mkdtemp(prefix=f".{story.name}.picker-", dir=story.parent))

    yaml = (
        f"slug: {slug}\n"
        f"status: phase1\n"
        f"current_phase: 1\n"
        f"pipeline_mode: production\n"
        f"corpus_source: {entry['slug']}\n"
        f"genre: {entry.get('genre','')}\n"
        f"\n"
        f"source_policy:\n"
        f"  access: denied\n"
        f'  notes: "auto-batch generated; explicit human source approval required before external runners"\n'
    )
    # Policy precedes source bytes even inside the private candidate directory.
    (staged / "story.yaml").write_text(yaml, encoding="utf-8")

    source_src = ROOT / entry["source_path"]
    if source_src.exists():
        shutil.copy2(source_src, staged / "source.md")
    else:
        (staged / "source.md").write_text(f"# missing source for {entry['slug']}\n", encoding="utf-8")

    pick_card = {
        "slug": slug,
        "corpus_slug": entry["slug"],
        "genre": entry.get("genre"),
        "mechanisms": entry.get("reversal_mechanisms", []),
        "hook_type": entry.get("hook_type"),
        "title_formula": entry.get("title_formula"),
        "tomato_fit_score": entry.get("tomato_fit_score"),
        "picked_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "run_id": run_id,
    }
    (staged / "pick-card.json").write_text(
        json.dumps(pick_card, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        _publish_scaffold(staged, story)
    except FileExistsError:
        # A concurrent picker or owner may have created this path meanwhile.
        # Never replace its bytes, metadata, symlink or legacy authorization.
        if not story.exists() and not story.is_symlink():
            raise
    return story


def _record_history(picks: List[Dict[str, Any]], slug_prefix: str, run_id: str, seed: int) -> None:
    PICKER_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "run_id": run_id,
        "slug_prefix": slug_prefix,
        "seed": seed,
        "corpus_slugs": [p["slug"] for p in picks],
        "ts": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    with PICKER_HISTORY.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--exclude-recent", type=int, default=20)
    parser.add_argument("--slug-prefix", default=None, help="story slug prefix; default auto_<ts>")
    parser.add_argument("--genre", action="append", default=[], help="filter genres (repeatable)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    entries = _load_index()
    if args.genre:
        entries = [e for e in entries if e.get("genre") in args.genre]
    recent = set(_load_recent(args.exclude_recent))
    pool = [e for e in entries if e.get("slug") not in recent]
    if not pool:
        pool = entries  # fallback if exclude window swallowed everything
    picks = _stratified_sample(pool, args.count, rng)
    if not picks:
        print("no corpus entries available", file=sys.stderr)
        return 11

    run_id = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    slug_prefix = args.slug_prefix or f"auto_{run_id}"

    stories: List[str] = []
    for entry in picks:
        story = _scaffold_story(entry, slug_prefix, run_id)
        stories.append(str(story))

    _record_history(picks, slug_prefix, run_id, args.seed if args.seed is not None else -1)

    payload = {
        "run_id": run_id,
        "slug_prefix": slug_prefix,
        "seed": args.seed,
        "stories": stories,
        "picks": [{"slug": p["slug"], "genre": p.get("genre"), "mechanisms": p.get("reversal_mechanisms", [])} for p in picks],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for s in stories:
            print(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
