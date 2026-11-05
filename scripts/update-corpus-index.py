#!/usr/bin/env python3
"""
update-corpus-index.py -- 扫描 corpus/{slug}/dissection.md 的元数据块,
把每个已完成解构的案例写入 corpus/_index.json 的 entries 列表。

dissection.md 必须包含以下块(由 prompts/dissector.md V3 产出):

    genre: <modern_reversal|ancient_BE|...>
    genre_confidence: <high|medium|low>

以及:

    ## 题材与机制(V3 新增)
    - **genre**: modern_reversal
    - **title_formula**: T1
    - **reversal_mechanisms**: [M1, M3]
    - **hook_type**: H1
    - **emotion_curve_shape**: U型

用法:
    python3 scripts/update-corpus-index.py
    python3 scripts/update-corpus-index.py --corpus /path/to/corpus
"""

import argparse
import json
import re
import sys
from pathlib import Path

from v4_quality import load_human_calibration
from storyforge_lib import write_text


def parse_dissection(text: str) -> dict:
    """从 dissection.md 抽取结构化元数据。容忍多种格式。"""
    meta = {}

    # YAML-like 顶部块 (```yaml ... ``` 或裸键值)
    m = re.search(r"genre:\s*([A-Za-z_]+)", text)
    if m:
        meta["genre"] = m.group(1)

    m = re.search(r"genre_confidence:\s*(\w+)", text)
    if m:
        meta["genre_confidence"] = m.group(1)

    # "## 题材与机制" 下的列表
    m = re.search(r"\*\*title_formula\*\*:\s*\[?([A-Za-z0-9_]+)\]?", text)
    if m:
        meta["title_formula"] = m.group(1)

    m = re.search(r"\*\*reversal_mechanisms\*\*:\s*\[([^\]]+)\]", text)
    if m:
        mechs = [x.strip().strip("'\"") for x in m.group(1).split(",")]
        meta["reversal_mechanisms"] = [x for x in mechs if x]

    m = re.search(r"\*\*hook_type\*\*:\s*\[?([A-Za-z0-9_]+)\]?", text)
    if m:
        meta["hook_type"] = m.group(1)

    m = re.search(r"\*\*emotion_curve_shape\*\*:\s*([\w\u4e00-\u9fff]+)", text)
    if m:
        meta["emotion_curve_shape"] = m.group(1)

    # Hook strength (可能在 beat-sheet.md 里,这里不抓)
    return meta


def _first(patterns, text: str):
    for pattern in patterns:
        m = re.search(pattern, text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    return None


def extract_emotional_debt(text: str):
    explicit = _first([r"\*\*情绪债\*\*[:：]\s*([^\n]+)", r"情绪债[:：]\s*([^\n]+)"], text)
    if explicit:
        return explicit
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("|") or "Beat" not in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and cells[0] in {"债务来源", "债务项", "情绪债"}:
            continue
        if len(cells) >= 2:
            return cells[0]
    return None


def parse_v4_genes(slug_dir: Path) -> dict:
    """抽取 V4 爆款基因字段。缺文件时保持兼容。"""
    out = {}
    soul = slug_dir / "analysis" / "soul-contract.md"
    reader = slug_dir / "analysis" / "reader-engine.md"
    platform = slug_dir / "analysis" / "platform-fit.md"

    if soul.exists():
        text = soul.read_text(encoding="utf-8")
        mapping = {
            "reader_promise": [
                r"\*\*一句话承诺\*\*[:：]\s*([^\n]+)",
                r"一句话承诺[:：]\s*([^\n]+)",
            ],
            "emotional_debt_type": [
                r"\*\*情绪债\*\*[:：]\s*([^\n]+)",
            ],
            "antagonist_violation": [
                r"\*\*反派必须被惩罚的理由\*\*[:：]\s*([^\n]+)",
                r"反派必须被惩罚的理由[:：]\s*([^\n]+)",
            ],
            "protagonist_stance": [
                r"\*\*核心姿态\*\*[:：]\s*([^\n]+)",
                r"核心姿态[:：]\s*([^\n]+)",
            ],
            "payoff_pattern": [
                r"\*\*最终必须兑现的体验\*\*[:：]\s*([^\n]+)",
                r"最终必须兑现的体验[:：]\s*([^\n]+)",
            ],
            "v4_calibration_status": [
                r"\*\*v4_calibration_status\*\*[:：]\s*([^\n]+)",
                r"v4_calibration_status[:：]\s*([^\n]+)",
            ],
            "v4_backfill_source": [
                r"\*\*v4_backfill_source\*\*[:：]\s*([^\n]+)",
                r"v4_backfill_source[:：]\s*([^\n]+)",
            ],
            "v4_human_reviewer": [
                r"\*\*v4_human_reviewer\*\*[:：]\s*([^\n]+)",
                r"v4_human_reviewer[:：]\s*([^\n]+)",
            ],
            "v4_human_reviewed_at": [
                r"\*\*v4_human_reviewed_at\*\*[:：]\s*([^\n]+)",
                r"v4_human_reviewed_at[:：]\s*([^\n]+)",
            ],
        }
        for key, patterns in mapping.items():
            value = extract_emotional_debt(text) if key == "emotional_debt_type" else _first(patterns, text)
            if value:
                out[key] = value

    if reader.exists():
        text = reader.read_text(encoding="utf-8")
        value = _first([r"\*\*主要爽点\*\*[:：]\s*([^\n]+)", r"主要爽点[:：]\s*([^\n]+)"], text)
        if value:
            out["dominant_s爽点"] = value

    if platform.exists():
        text = platform.read_text(encoding="utf-8")
        value = _first([r"\*\*总分\*\*[:：]\s*([0-9.]+)", r"总分[:：]\s*([0-9.]+)"], text)
        if value:
            try:
                out["tomato_fit_score"] = float(value)
            except ValueError:
                out["tomato_fit_score"] = value

    human = parse_human_calibration(slug_dir)
    if human:
        out.update(human)

    return out


def parse_human_calibration(slug_dir: Path) -> dict:
    calibration = load_human_calibration(slug_dir)
    if not calibration:
        return {}
    return {
        key: value
        for key, value in calibration.items()
        if key in {
            "reader_promise",
            "emotional_debt_type",
            "dominant_s爽点",
            "antagonist_violation",
            "protagonist_stance",
            "payoff_pattern",
            "tomato_fit_score",
        }
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(Path(__file__).resolve().parent.parent / "corpus"))
    args = ap.parse_args()

    corpus = Path(args.corpus)
    if not corpus.is_dir():
        print(f"错误: corpus 目录不存在: {corpus}", file=sys.stderr)
        sys.exit(1)

    index_path = corpus / "_index.json"
    manifest_path = corpus / "_manifest.tsv"

    # 载入或初始化 index
    if index_path.exists():
        with index_path.open("r", encoding="utf-8") as f:
            idx = json.load(f)
    else:
        idx = {"_meta": {"description": "跨篇章检索索引"}, "entries": []}

    # 载入 manifest
    manifest = {}
    if manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8") as f:
            header = f.readline()
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 3:
                    manifest[parts[0]] = {
                        "filename": parts[1],
                        "word_count": int(parts[2]) if parts[2].isdigit() else 0,
                        "status": parts[3] if len(parts) > 3 else "pending",
                    }

    # 扫描每个 slug
    entries = []
    updated = 0
    for slug_dir in sorted(corpus.iterdir()):
        if not slug_dir.is_dir() or slug_dir.name.startswith("_"):
            continue
        slug = slug_dir.name
        entry = {
            "slug": slug,
            "source_path": f"corpus/{slug}/source.md",
            "status": "pending",
        }
        if slug in manifest:
            entry["filename"] = manifest[slug]["filename"]
            entry["word_count"] = manifest[slug]["word_count"]

        dissection = slug_dir / "dissection.md"
        if dissection.exists():
            meta = parse_dissection(dissection.read_text(encoding="utf-8"))
            entry.update(meta)
            try:
                entry.update(parse_v4_genes(slug_dir))
            except ValueError as exc:
                print(f"错误: {slug} human calibration invalid: {exc}", file=sys.stderr)
                sys.exit(1)
            entry["status"] = "dissected" if "genre" in meta else "pending"
            updated += 1

        entries.append(entry)

    idx["entries"] = entries
    idx["_meta"]["total"] = len(entries)
    idx["_meta"]["dissected"] = updated
    idx["_meta"]["schema_version"] = "1.1"
    idx["_meta"]["v4_gene_fields"] = [
        "reader_promise",
        "emotional_debt_type",
        "dominant_s爽点",
        "antagonist_violation",
        "protagonist_stance",
        "payoff_pattern",
        "tomato_fit_score",
    ]
    idx["_meta"]["v4_calibration_fields"] = [
        "v4_calibration_status",
        "v4_backfill_source",
        "v4_human_reviewer",
        "v4_human_reviewed_at",
    ]

    write_text(index_path, json.dumps(idx, ensure_ascii=False, indent=2))

    print(f"索引已更新: {index_path}")
    print(f"  总条目: {len(entries)}")
    print(f"  已解构(dissected): {updated}")
    print(f"  待解构(pending): {len(entries) - updated}")


if __name__ == "__main__":
    main()
