#!/usr/bin/env python3
"""
split-to-chapters.py -- 把 stories/{slug}/final.md 切成番茄章节
(final-chapters/ch{NN}.md + _chapters-map.md)。

规则(与 finalizer.md Step 6 对齐):
  1. 每章 500-800 字(中位 650),超 1000 必切,低于 400 合并
  2. 切点优先级:
     A 级: 原文自然分隔符(--- 或 数字小节标记如 "1 " "01")
     B 级: 段落边界(空行)
     C 级: 句号边界(兜底)
  3. 每章末必有钩子(由人类审阅,本脚本只切分+生成 map 模板)

用法:
  python3 scripts/split-to-chapters.py --story stories/hermes_bag
  python3 scripts/split-to-chapters.py --story <path> --min 500 --max 800
"""

import argparse
import re
import sys
from pathlib import Path


def count_chars(s: str) -> int:
    """中文字符数(含标点, 排除空白)"""
    return sum(1 for c in s if not c.isspace())


def split_paragraphs(text: str):
    """按空行拆段,保留段间分隔符"""
    paras = re.split(r"\n\s*\n", text)
    return [p.strip() for p in paras if p.strip()]


def is_section_marker(p: str) -> bool:
    """判断一段是不是自然分隔符/小节号(A 级切点)"""
    s = p.strip()
    if s in ("---", "==="):
        return True
    # 纯数字行或 数字. 或 数字、 或 01 等
    if re.fullmatch(r"[0-9０-９]+[\.、]?", s):
        return True
    return False


def split_into_chapters(text: str, target_min: int = 500, target_max: int = 800, hard_max: int = 1000):
    """把 text 切成 [{chars, body, cut_level}, ...]"""
    # 先去掉标题行(如果存在第一行是 # 开头)
    lines = text.split("\n")
    title = ""
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        text = "\n".join(lines[1:])

    paras = split_paragraphs(text)

    chapters = []
    buf = []
    buf_chars = 0

    def flush(cut_level):
        nonlocal buf, buf_chars
        if not buf:
            return
        chapters.append({
            "chars": buf_chars,
            "body": "\n\n".join(buf).strip(),
            "cut_level": cut_level,
        })
        buf = []
        buf_chars = 0

    i = 0
    while i < len(paras):
        p = paras[i]

        # A 级: 遇到分隔符直接切(只要当前 buf 到达 min)
        if is_section_marker(p) and buf_chars >= target_min * 0.7:
            flush("A")
            # 分隔符本身不入章
            i += 1
            continue

        buf.append(p)
        buf_chars += count_chars(p)

        # B 级: 到达 target_max 上限且处于段边界
        if buf_chars >= target_max:
            flush("B")
        # C 级: 硬顶
        elif buf_chars >= hard_max:
            flush("C")
        i += 1

    # 收尾
    if buf_chars > 0:
        if chapters and buf_chars < target_min * 0.8:
            # 合并到上一章
            last = chapters.pop()
            chapters.append({
                "chars": last["chars"] + buf_chars,
                "body": last["body"] + "\n\n" + "\n\n".join(buf),
                "cut_level": last["cut_level"],
            })
        else:
            flush("B")

    return title, chapters


def last_sentence(body: str, max_chars: int = 60) -> str:
    """取最后一个句子作钩子摘要"""
    # 优先抓引号对话
    m = re.findall(r"[""][^""]+?[""]|[\"“][^\"”]+?[\"”]", body)
    if m:
        return m[-1][:max_chars]
    # 否则最后一句
    sentences = re.split(r"[。!！?？]", body.strip())
    for s in reversed(sentences):
        s = s.strip()
        if s:
            return s[:max_chars]
    return body[-max_chars:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", required=True, help="stories/xxx 路径")
    ap.add_argument("--min", type=int, default=500)
    ap.add_argument("--max", type=int, default=800)
    ap.add_argument("--hard-max", type=int, default=1000)
    args = ap.parse_args()

    story_dir = Path(args.story)
    final_md = story_dir / "final.md"
    if not final_md.exists():
        print(f"错误: {final_md} 不存在", file=sys.stderr)
        sys.exit(1)

    text = final_md.read_text(encoding="utf-8")
    # 去除结尾的元数据块(> 仿写信息 / > 仿写元数据)
    text = re.sub(r"\n---\s*\n\s*>\s*仿写.*$", "", text, flags=re.DOTALL)

    title, chapters = split_into_chapters(text, args.min, args.max, args.hard_max)

    out_dir = story_dir / "final-chapters"
    out_dir.mkdir(exist_ok=True)

    # 清掉旧章节
    for old in out_dir.glob("ch*.md"):
        old.unlink()

    map_rows = []
    for idx, ch in enumerate(chapters, 1):
        num = f"{idx:02d}"
        path = out_dir / f"ch{num}.md"
        header = f"# 第 {idx} 章\n\n" if not title else f"# 第 {idx} 章 [章标待填]\n\n"
        path.write_text(header + ch["body"] + "\n", encoding="utf-8")
        hook = last_sentence(ch["body"])
        map_rows.append((num, ch["chars"], ch["cut_level"], hook))

    # 写 _chapters-map.md
    map_md = [f"# 章节映射 — {title or story_dir.name}\n"]
    map_md.append(f"**总章数**: {len(chapters)} | **总字数**: {sum(r[1] for r in map_rows)}\n")
    map_md.append("| 章 | 字数 | 切点类型 | 本章钩子 |")
    map_md.append("|----|-----|---------|---------|")
    for num, chars, cut, hook in map_rows:
        map_md.append(f"| {num} | {chars} | {cut} | {hook} |")
    (out_dir / "_chapters-map.md").write_text("\n".join(map_md) + "\n", encoding="utf-8")

    # 摘要
    print(f"已切分: {len(chapters)} 章, 总字数 {sum(r[1] for r in map_rows)}")
    print(f"产出: {out_dir}/ch01.md ~ ch{len(chapters):02d}.md + _chapters-map.md")
    in_range = sum(1 for r in map_rows if args.min <= r[1] <= args.max)
    print(f"字数在 [{args.min}, {args.max}] 范围内的章节: {in_range}/{len(chapters)}")


if __name__ == "__main__":
    main()
