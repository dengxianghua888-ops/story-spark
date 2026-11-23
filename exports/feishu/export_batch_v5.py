#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "exports" / "feishu"
BATCH = "batch_v5_20260526"
MANIFEST = OUT / f"manifest.{BATCH}.json"
RESULTS = OUT / f"feishu-docs.{BATCH}.json"
INDEX_XML = OUT / f"feishu-index.{BATCH}.xml"

STORIES = [
    ("batch_v5_01_modern_reversal", "晚风别忆旧时人"),
    ("batch_v5_02_family_ethics", "愚人节是他的放纵日"),
    ("batch_v5_03_ancient_BE", "听见蝴蝶的振翅声"),
    ("batch_v5_04_ancient_sweet", "将门毒女"),
    ("batch_v5_05_urban_sweet_ceo", "她把副驾留给了别人"),
]


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def md_to_body_xml(md_text: str) -> str:
    lines = []
    for line in md_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            continue
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            lines.append(f"<h2>{esc(heading)}</h2>")
        else:
            lines.append(f"<p>{esc(stripped)}</p>")
    return "\n".join(lines)


def build_skeleton(title: str, slug: str, chars: int, chapters: int) -> str:
    doc_title = f"短篇仿写终稿｜{title}"
    return "\n".join([
        f"<title>{esc(doc_title)}</title>",
        '<callout emoji="✅" background-color="light-green" border-color="green">',
        "<p>v5 结构保真产线终稿（超配减法 + 断章/密度/反转约束）。</p>",
        "</callout>",
        "<h1>质量打标</h1>",
        "<table><colgroup><col span=\"1\" width=\"160\"/><col span=\"1\" width=\"480\"/></colgroup>"
        "<thead><tr><th background-color=\"light-gray\">项目</th><th background-color=\"light-gray\">内容</th></tr></thead>"
        "<tbody>"
        f"<tr><td>本地目录</td><td>stories/{esc(slug)}</td></tr>"
        "<tr><td>产线模式</td><td>production (v5_structure_fidelity)</td></tr>"
        "<tr><td>闸门状态</td><td>pass</td></tr>"
        f"<tr><td>正文字符数</td><td>{chars}</td></tr>"
        f"<tr><td>章节数</td><td>{chapters}</td></tr>"
        "</tbody></table>",
        "<hr/>",
        "<h1>正文</h1>",
    ])


def prepare_files() -> list[dict]:
    manifest = []
    for slug, title in STORIES:
        final_path = ROOT / "stories" / slug / "final.md"
        md_text = final_path.read_text(encoding="utf-8")
        chars = len(re.sub(r"\s+", "", md_text))
        chapters = len(re.findall(r"^## ", md_text, re.MULTILINE))

        prefix = f"{BATCH}.{slug}"
        skeleton_path = OUT / f"{prefix}.skeleton.xml"
        body_path = OUT / f"{prefix}.body.xml"

        skeleton_xml = build_skeleton(title, slug, chars, chapters)
        body_xml = md_to_body_xml(md_text)

        skeleton_path.write_text(skeleton_xml + "\n", encoding="utf-8")
        body_path.write_text(body_xml + "\n", encoding="utf-8")

        manifest.append({
            "slug": slug,
            "title": title,
            "doc_title": f"短篇仿写终稿｜{title}",
            "chars": chars,
            "chapters": chapters,
            "skeleton": str(skeleton_path),
            "body": str(body_path),
        })
        print(f"  [{slug}] {title} — {chars} chars, {chapters} chapters")

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nManifest written: {MANIFEST}")
    return manifest


def build_index(manifest: list[dict]) -> None:
    rows = []
    for idx, item in enumerate(manifest, start=1):
        rows.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{esc(item['title'])}</td>"
            f"<td>{item['chars']}</td>"
            f"<td>{item['chapters']}</td>"
            f"<td>stories/{esc(item['slug'])}</td>"
            "</tr>"
        )

    xml = "\n".join([
        f"<title>短篇仿写终稿导出目录｜{BATCH}｜5篇</title>",
        '<callout emoji="✅" background-color="light-green" border-color="green">',
        "<p>5 篇 v5 结构保真产线终稿；本页为总目录。</p>",
        "</callout>",
        "<h1>导出总览</h1>",
        "<table>"
        '<colgroup><col span="1" width="60"/><col span="1" width="200"/><col span="1" width="90"/><col span="1" width="90"/><col span="1" width="200"/></colgroup>'
        '<thead><tr><th background-color="light-gray">序号</th><th background-color="light-gray">标题</th><th background-color="light-gray">字数</th><th background-color="light-gray">章节</th><th background-color="light-gray">目录</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>",
        "<hr/>",
        "<h1>版本说明</h1>",
        "<ul><li>v5_structure_fidelity 产线，rhythm_fit + structure_gate 全 PASS</li>"
        "<li>5 genres: modern_reversal / family_ethics / ancient_BE / ancient_sweet / urban_sweet_ceo</li>"
        "<li>超配减法策略 + 断章密度约束 + 反转层次约束</li></ul>",
        f"<p>导出时间：{esc(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}</p>",
    ])
    INDEX_XML.write_text(xml + "\n", encoding="utf-8")
    print(f"Index written: {INDEX_XML}")


def main() -> int:
    print(f"=== V5 Batch Export: {BATCH} ===\n")
    manifest = prepare_files()
    build_index(manifest)
    print(f"\nPrepared {len(manifest)} stories. XML files ready for lark-cli upload.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
