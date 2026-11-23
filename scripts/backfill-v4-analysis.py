#!/usr/bin/env python3
"""Backfill StoryForge V4 corpus gene artifacts from existing V3 dissections.

This script intentionally emits machine_draft artifacts. They make retrieval
possible, but do not replace human calibration.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict


MECHANISM_S爽点 = {
    "M1": "死环反杀",
    "M2": "身份反差爆发",
    "M3": "因果回旋反讽",
    "M4": "灵魂线视角",
    "M5": "温度反转清算",
    "M6": "多层递进反转",
    "M7": "降维打击",
    "M8": "道德模糊余味",
}

GENRE_DEFAULTS = {
    "modern_reversal": {
        "reader_promise": "看普通人被荒谬规则压迫后，用对方亲手确认的规则完成反杀。",
        "emotional_debt_type": "规则压迫债",
        "antagonist_violation": "反派滥用制度、系统或公章，把弱者逼进无法申辩的位置。",
        "protagonist_stance": "隐忍、冷静、证据型反击",
        "payoff_pattern": "同一规则回旋，反派在公开场合被逻辑死环钉死。",
    },
    "family_ethics": {
        "reader_promise": "看亲密关系中的背叛被证据、同态报应和公开清算彻底偿还。",
        "emotional_debt_type": "亲情/婚姻背叛债",
        "antagonist_violation": "反派利用亲情、婚姻或孝道绑架主角，并伤害无辜者。",
        "protagonist_stance": "受伤后冷硬、拒绝和稀泥",
        "payoff_pattern": "让施害者承受自己制造的规则、舆论或后果。",
    },
    "ancient_BE": {
        "reader_promise": "看主角在极致错付后抽身或死亡，迫使施害者迟来的悔悟变成惩罚。",
        "emotional_debt_type": "错付虐恋债",
        "antagonist_violation": "反派长期冷待、误解或牺牲主角，把爱当作理所当然。",
        "protagonist_stance": "克制、决绝、哀而不求",
        "payoff_pattern": "主角离场后，反派在不可逆失去中偿还情绪债。",
    },
    "ancient_sweet": {
        "reader_promise": "看被轻视的女主通过身份、能力或人脉反差完成轻快反击和情感补偿。",
        "emotional_debt_type": "轻辱反差债",
        "antagonist_violation": "反派以身份、家世或偏见贬低主角。",
        "protagonist_stance": "松弛、聪明、藏锋",
        "payoff_pattern": "身份/能力揭开后，羞辱者被反差打脸，正缘站到主角一边。",
    },
    "apocalypse_heroine": {
        "reader_promise": "看被放逐的大女主用更高规则降维打击，让抛弃她的旧秩序崩塌。",
        "emotional_debt_type": "放逐背叛债",
        "antagonist_violation": "反派在危机中驱逐、剥夺或背叛真正的强者。",
        "protagonist_stance": "冷静、强硬、末世生存者",
        "payoff_pattern": "主角建立新规则，旧阵营因当初选择自食其果。",
    },
    "urban_sweet_ceo": {
        "reader_promise": "看被低估的主角揭开身份反差，夺回情感和权力主动权。",
        "emotional_debt_type": "身份轻视债",
        "antagonist_violation": "反派误判主角身份、能力或感情位置，并公开羞辱。",
        "protagonist_stance": "体面、锋利、掌控全局",
        "payoff_pattern": "身份揭露后，反派社交性崩塌，主角获得权力和情感补偿。",
    },
}


def load_index(corpus: Path) -> Dict[str, Any]:
    path = corpus / "_index.json"
    if not path.exists():
        raise ValueError(f"missing corpus index: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def choose_dominant(entry: Dict[str, Any]) -> str:
    mechanisms = entry.get("reversal_mechanisms", [])
    genre = entry.get("genre")
    genre_priority = {
        "modern_reversal": ["M1", "M3", "M6"],
        "family_ethics": ["M3", "M5", "M1", "M4"],
        "ancient_BE": ["M4", "M5", "M8", "M1"],
        "ancient_sweet": ["M2", "M6", "M3"],
        "apocalypse_heroine": ["M7", "M6", "M8", "M2"],
        "urban_sweet_ceo": ["M2", "M5", "M3"],
    }
    priority = genre_priority.get(genre, ["M1", "M7", "M4", "M2", "M5", "M6", "M3", "M8"])
    for mech in priority:
        if mech in mechanisms and mech in MECHANISM_S爽点:
            return MECHANISM_S爽点[mech]
    for mech in mechanisms:
        if mech in MECHANISM_S爽点:
            return MECHANISM_S爽点[mech]
    return "情绪债清算"


def platform_score(entry: Dict[str, Any]) -> float:
    score = 7.6
    hook_type = entry.get("hook_type")
    mechanisms = entry.get("reversal_mechanisms", [])
    if hook_type == "H1":
        score += 0.5
    elif hook_type in {"H2", "H3", "H4"}:
        score += 0.25
    if "M1" in mechanisms:
        score += 0.35
    if "M3" in mechanisms:
        score += 0.25
    if "M6" in mechanisms:
        score += 0.15
    return round(min(score, 9.0), 1)


def defaults_for(entry: Dict[str, Any]) -> Dict[str, str]:
    genre = entry.get("genre", "")
    base = GENRE_DEFAULTS.get(genre, GENRE_DEFAULTS["modern_reversal"]).copy()
    dominant = choose_dominant(entry)
    base["dominant_s爽点"] = dominant
    if entry.get("reversal_mechanisms"):
        base["payoff_pattern"] = f"{base['payoff_pattern']} 主导爽点为{dominant}。"
    return base


def write_if_allowed(path: Path, text: str, overwrite: bool) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def render_soul(entry: Dict[str, Any], values: Dict[str, str]) -> str:
    mechanisms = ", ".join(entry.get("reversal_mechanisms", [])) or "待补"
    return f"""# 爆款神髓合约(V4 machine draft)

**v4_calibration_status**: machine_draft
**v4_backfill_source**: scripts/backfill-v4-analysis.py

## 基本信息

- **slug**: {entry.get('slug', '')}
- **source_title**: {entry.get('filename', '')}
- **genre**: {entry.get('genre', '')}
- **locked_mechanisms**: [{mechanisms}]

## 读者承诺

**一句话承诺**: {values['reader_promise']}
**最终必须兑现的体验**: {values['payoff_pattern']}

## 情绪债

**情绪债**: {values['emotional_debt_type']}

| 债务项 | 累积方式 | 必须偿还方式 |
|--------|----------|--------------|
| 压迫债 | 反派借助题材核心规则持续压低主角 | 主角必须用同一规则完成反击 |
| 羞辱债 | 主角被公开误解、轻视或剥夺选择权 | 反派必须公开失控或被迫承认漏洞 |
| 补偿债 | 主角付出金钱、尊严、机会或生命代价 | 结尾必须给出价值回甘或不可逆惩罚 |

## 爽点因果链

1. 反派种因: {values['antagonist_violation']}
2. 主角蓄力: {values['protagonist_stance']}。
3. 规则回旋: 保留 {values['dominant_s爽点']} 的结构位置。
4. 爽感释放: {values['payoff_pattern']}

## 道德坐标

- **反派必须被惩罚的理由**: {values['antagonist_violation']}
- **读者站位**: 主角只是在对方规则内追回应得的公平。

## 主角姿态

**核心姿态**: {values['protagonist_stance']}

## 神髓禁改项

- 保留题材核心压迫规则。
- 保留主角从承压到取证再到清算的姿态转变。
- 保留 {mechanisms} 对应的机制承载点。
- 保留结尾的补偿或反噬闭环。

## 可替换项

- 世界观、职业、道具、地点、身份标签可以替换。
- 读者承诺、情绪债类型、主角姿态和机制因果链不可替换。
"""


def render_reader(entry: Dict[str, Any], values: Dict[str, str]) -> str:
    return f"""# 读者心理引擎(V4 machine draft)

**v4_calibration_status**: machine_draft
**主要爽点**: {values['dominant_s爽点']}

| 阶段 | 读者此刻知道什么 | 读者不知道什么 | 恨谁 | 期待谁 | 想看什么报应 |
|------|------------------|----------------|------|--------|--------------|
| 开局 Hook | 主角被不公平规则击中 | 反杀凭证如何出现 | 压迫者 | 主角 | 规则反噬 |
| 持续打压 | 反派掌握场面权力 | 主角是否已开始取证 | 反派和旁观误解 | 主角 | 公开打脸 |
| 蓄力转折 | 主角开始接受对方规则 | 证据会怎样回旋 | 反派 | 主角 | 死环扣死 |
| 清算高潮 | 反派规则出现自相矛盾 | 牵连范围有多大 | 整条压迫链 | 主角/正义执行者 | 连根拔起 |
| 余波回甘 | 主角获得清白或补偿 | 是否还有价值闭环 | 已被惩罚的反派 | 主角 | 努力被看见 |

## 空 Beat 风险

machine_draft 仅从 V3 dissection 反推读者心理,需人工逐 Beat 校准。
"""


def render_tension(entry: Dict[str, Any], values: Dict[str, str]) -> str:
    return f"""# 情绪债账本(V4 machine draft)

**v4_calibration_status**: machine_draft

## 债务总览

| 债务类型 | 累积段 | 偿还段 | 备注 |
|----------|--------|--------|------|
| {values['emotional_debt_type']} | 前 40%-60% | 后 40% | 需人工按 Beat 校准 |
| 公开羞辱债 | 压迫与误解段 | 公开反击段 | 需保留旁观者倒戈 |
| 价值补偿债 | 主角付出代价段 | 结尾回甘段 | 需避免爽点无根 |

## 偿还原则

- 每一次爽点必须偿还前文明确压下的债。
- {values['dominant_s爽点']} 必须连接“反派种因”和“主角清算”。
- 若后文出现单纯剧情推进但读者情绪没有变化,应标为空 Beat。
"""


def render_platform(entry: Dict[str, Any], values: Dict[str, str]) -> str:
    score = platform_score(entry)
    return f"""# 番茄平台适配报告(V4 machine draft)

**v4_calibration_status**: machine_draft
**总分**: {score}

| 维度 | 机器初评 | 依据 |
|------|----------|------|
| 标题点击欲 | 待人工校准 | title_formula={entry.get('title_formula', '')} |
| 首章留存 | 待人工校准 | hook_type={entry.get('hook_type', '')} |
| 每 3000 字卡点 | 待人工校准 | emotion_curve_shape={entry.get('emotion_curve_shape', '')} |
| 章节钩子 | 待人工校准 | 需 Phase 5 章节切分后确认 |
| 标签命中 | 待人工校准 | genre={entry.get('genre', '')}, dominant={values['dominant_s爽点']} |

## 机器判断

本报告只用于 few-shot 检索初筛,不可替代人工平台适配评审。
"""


def backfill_entry(corpus: Path, entry: Dict[str, Any], overwrite: bool) -> int:
    slug = entry.get("slug")
    if not slug:
        return 0
    slug_dir = corpus / slug
    if not (slug_dir / "dissection.md").exists():
        return 0
    values = defaults_for(entry)
    files = {
        "analysis/soul-contract.md": render_soul(entry, values),
        "analysis/reader-engine.md": render_reader(entry, values),
        "analysis/tension-ledger.md": render_tension(entry, values),
        "analysis/platform-fit.md": render_platform(entry, values),
    }
    written = 0
    for rel, text in files.items():
        if write_if_allowed(slug_dir / rel, text, overwrite):
            written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default=str(Path(__file__).resolve().parent.parent / "corpus"))
    parser.add_argument("--slug", help="Only backfill one corpus slug")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing V4 artifacts")
    args = parser.parse_args()

    corpus = Path(args.corpus)
    try:
        index = load_index(corpus)
    except (ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    entries = [entry for entry in index.get("entries", []) if entry.get("status") == "dissected"]
    if args.slug:
        entries = [entry for entry in entries if entry.get("slug") == args.slug]
    if args.slug and not entries:
        print(f"no dissected entry found for slug: {args.slug}", file=sys.stderr)
        return 1

    total_files = 0
    total_entries = 0
    for entry in entries:
        written = backfill_entry(corpus, entry, overwrite=args.overwrite)
        if written:
            total_entries += 1
            total_files += written

    print(f"backfilled entries={total_entries} files={total_files} status=machine_draft")
    return 0


if __name__ == "__main__":
    sys.exit(main())
