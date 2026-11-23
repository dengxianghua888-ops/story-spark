#!/usr/bin/env python3
"""Prepare final.md files for Feishu export by stripping submission metadata."""
import re
import os

STORIES = [
    'v6r2_01_ghost_wedding',
    'v6r2_02_clock_gaokao',
    'v6r2_03_ancient_disaster_star',
    'v6r2_04_urban_no_wait',
    'v6r2_05_snowstorm_twenty_wan',
]

EXPORT_DIR = 'exports/feishu_v6r2'

os.makedirs(EXPORT_DIR, exist_ok=True)

for slug in STORIES:
    src = f'stories/{slug}/final.md'
    if not os.path.exists(src):
        print(f'SKIP {slug}: final.md not found')
        continue

    with open(src, 'r') as f:
        text = f.read()

    # Remove submission info section
    parts = text.split('## 投稿信息')
    body = parts[0].strip()

    # Remove trailing --- separator if present
    body = re.sub(r'\n---\s*$', '', body)

    # Extract title
    lines = body.split('\n')
    title = lines[0].replace('# ', '').strip()

    # Write export file
    out_path = f'{EXPORT_DIR}/{slug}.md'
    with open(out_path, 'w') as f:
        f.write(body + '\n')

    char_count = len(re.sub(r'\s', '', body))
    print(f'OK {slug}: "{title}" ({char_count} chars) -> {out_path}')
