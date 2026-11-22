#!/usr/bin/env python3
"""Build few-shot sample set from corpus for scene-writer style reference.

Scans all dissected sources for a given genre, computes rhythm_profile,
filters by quality criteria, selects top N, and extracts opening + climax
excerpts into corpus/samples/{genre}/.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

# Import from sibling module
import sys
sys.path.insert(0, str(Path(__file__).parent))
from rhythm_metrics import rhythm_profile


CORPUS_ROOT = Path(__file__).resolve().parent.parent / "corpus"
SAMPLES_ROOT = CORPUS_ROOT / "samples"


def load_index() -> List[Dict[str, Any]]:
    index_path = CORPUS_ROOT / "_index.json"
    with open(index_path, encoding="utf-8") as f:
        return json.load(f)["entries"]


def read_source(slug: str) -> str:
    path = CORPUS_ROOT / slug / "source.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter (--- ... ---) from source text."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end < 0:
        return text
    return "\n".join(lines[end + 1:])


def extract_opening(text: str, n_lines: int = 30) -> str:
    """Extract first n non-empty, non-heading lines from body."""
    text = strip_frontmatter(text)
    lines = text.splitlines()
    result = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        result.append(line)
        if len(result) >= n_lines:
            break
    return "\n".join(result)


def find_climax_region(text: str) -> str:
    """Heuristic: find the densest question-mark region (~30 lines) as climax proxy."""
    text = strip_frontmatter(text)
    lines = text.splitlines()
    content_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            content_lines.append("")
        else:
            content_lines.append(stripped)

    if len(content_lines) < 60:
        mid = len(content_lines) // 2
        start = max(0, mid - 15)
        return "\n".join(l for l in content_lines[start:start+30] if l)

    window = 30
    best_score = -1
    best_start = len(content_lines) // 2

    for i in range(len(content_lines) - window):
        chunk = "\n".join(content_lines[i:i+window])
        qmarks = chunk.count("？") + chunk.count("?")
        excl = chunk.count("！") + chunk.count("!")
        score = qmarks * 2 + excl
        if i > len(content_lines) * 0.4:
            score *= 1.3
        if score > best_score:
            best_score = score
            best_start = i

    region = content_lines[best_start:best_start+window]
    return "\n".join(l for l in region if l)


def score_candidate(profile: Dict[str, Any], entry: Dict[str, Any]) -> float:
    """Score a source for sample quality. Higher = better fit for reference."""
    avg = profile["avg_line_chars"]
    long_rate = profile["long_line_rate"]
    q_per_k = profile["question_marks_per_k"]
    chars = profile["chars"]

    score = 0.0
    if 17 <= avg <= 23:
        score += 30
    elif 15 <= avg <= 25:
        score += 15

    if long_rate <= 0.08:
        score += 25
    elif long_rate <= 0.12:
        score += 15

    if q_per_k >= 5.0:
        score += 25
    elif q_per_k >= 4.0:
        score += 15

    if 8000 <= chars <= 15000:
        score += 10
    elif 6000 <= chars <= 18000:
        score += 5

    if profile["quote_line_rate"] >= 0.25 and profile["quote_line_rate"] <= 0.45:
        score += 10

    return score


def select_samples(
    genre: str,
    n: int = 5,
    min_avg: float = 17.0,
    max_avg: float = 23.0,
    max_long_rate: float = 0.10,
    min_question: float = 4.5,
) -> List[Dict[str, Any]]:
    """Select top N sources as style samples."""
    entries = load_index()
    genre_entries = [e for e in entries if e.get("genre") == genre and e.get("status") == "dissected"]

    candidates = []
    for entry in genre_entries:
        slug = entry["slug"]
        text = read_source(slug)
        if not text:
            continue

        profile = rhythm_profile(text)
        if profile["line_count"] < 50:
            continue

        avg = profile["avg_line_chars"]
        if not (min_avg <= avg <= max_avg):
            continue
        if profile["long_line_rate"] > max_long_rate:
            continue
        if profile["question_marks_per_k"] < min_question:
            continue

        chars = profile["chars"]
        if chars < 6000 or chars > 18000:
            continue

        score = score_candidate(profile, entry)
        candidates.append({
            "slug": slug,
            "filename": entry.get("filename", ""),
            "profile": profile,
            "score": score,
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:n]


def build_sample_set(genre: str, n: int = 5, opening_lines: int = 30, climax_lines: int = 30):
    """Build full sample set: select, extract, write to disk."""
    print(f"Scanning corpus for genre={genre}...")
    samples = select_samples(genre, n=n)

    if not samples:
        print("No samples found matching criteria. Try relaxing filters.")
        return

    print(f"Selected {len(samples)} samples:")
    for i, s in enumerate(samples):
        print(f"  {i+1}. {s['slug']} (score={s['score']:.1f}, avg={s['profile']['avg_line_chars']:.1f}, "
              f"long={s['profile']['long_line_rate']:.3f}, q/k={s['profile']['question_marks_per_k']:.1f})")

    out_dir = SAMPLES_ROOT / genre
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "genre": genre,
        "selection_criteria": {
            "avg_line_chars": "17-23 (P25-P75)",
            "long_line_rate": "≤10%",
            "question_marks_per_k": "≥4.5",
            "chars": "6000-18000",
        },
        "samples": [],
    }

    for i, sample in enumerate(samples, 1):
        slug = sample["slug"]
        text = read_source(slug)

        opening = extract_opening(text, opening_lines)
        climax = find_climax_region(text)

        excerpt = f"## 开篇（前 {opening_lines} 行）\n\n{opening}\n\n## 高潮段\n\n{climax}\n"

        excerpt_path = out_dir / f"sample_{i:02d}_excerpt.md"
        excerpt_path.write_text(excerpt, encoding="utf-8")

        manifest["samples"].append({
            "index": i,
            "slug": slug,
            "filename": sample["filename"],
            "excerpt_file": excerpt_path.name,
            "score": sample["score"],
            "rhythm": {
                "avg_line_chars": sample["profile"]["avg_line_chars"],
                "long_line_rate": sample["profile"]["long_line_rate"],
                "quote_line_rate": sample["profile"]["quote_line_rate"],
                "question_marks_per_k": sample["profile"]["question_marks_per_k"],
                "chars": sample["profile"]["chars"],
            },
        })

    manifest_path = out_dir / "_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\nSample set written to: {out_dir}")
    print(f"Manifest: {manifest_path}")


def main():
    parser = argparse.ArgumentParser(description="Build few-shot sample set from corpus")
    parser.add_argument("--genre", default="modern_reversal", help="Genre to build samples for")
    parser.add_argument("--n", type=int, default=5, help="Number of samples to select")
    parser.add_argument("--opening-lines", type=int, default=30, help="Lines to extract from opening")
    parser.add_argument("--scan-only", action="store_true", help="Only scan and print candidates, don't write")
    parser.add_argument("--relax", action="store_true", help="Use relaxed filters if strict yields too few")
    args = parser.parse_args()

    if args.scan_only:
        samples = select_samples(args.genre, n=20)
        if not samples:
            if args.relax:
                print("Strict filters: 0 results. Trying relaxed (avg 15-25, long ≤15%, q ≥3.5)...")
                samples = select_samples(args.genre, n=20, min_avg=15, max_avg=25, max_long_rate=0.15, min_question=3.5)
            if not samples:
                print("No candidates found.")
                return
        print(f"Top {len(samples)} candidates for genre={args.genre}:")
        print(f"{'#':<3} {'slug':<30} {'score':<6} {'avg':<6} {'long%':<6} {'q/k':<5} {'chars':<6}")
        print("-" * 70)
        for i, s in enumerate(samples, 1):
            p = s["profile"]
            print(f"{i:<3} {s['slug']:<30} {s['score']:<6.0f} {p['avg_line_chars']:<6.1f} "
                  f"{p['long_line_rate']*100:<6.1f} {p['question_marks_per_k']:<5.1f} {p['chars']:<6}")
    else:
        if args.relax:
            samples = select_samples(args.genre, n=args.n)
            if len(samples) < args.n:
                print(f"Strict: only {len(samples)}. Trying relaxed...")
                build_sample_set(args.genre, n=args.n, opening_lines=args.opening_lines)
            else:
                build_sample_set(args.genre, n=args.n, opening_lines=args.opening_lines)
        else:
            build_sample_set(args.genre, n=args.n, opening_lines=args.opening_lines)


if __name__ == "__main__":
    main()
