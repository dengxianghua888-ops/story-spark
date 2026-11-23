"""Repository hygiene: third-party source texts must never be tracked.

`.gitignore` keeps new copies out, but it cannot stop a renamed copy or a
force-add. This test inspects what git actually tracks.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Original inputs and any renamed copy/backup of them under corpus/ or stories/:
# source.md, Source.md, source-original.md, source_backup.md, source.md.bak,
# 原文.md, and raw *.txt imports. Matching is case-insensitive.
FORBIDDEN = re.compile(
    r"^(corpus|stories)/(.+/)?"
    r"((source|原文)([-_. ][^/]*)?\.(md|markdown|txt)([.~][^/]*)?|[^/]+\.txt)$",
    re.IGNORECASE,
)
# Tool-written notes that describe a source without containing it.
ALLOWED_NAMES = {"SOURCE_CORRUPT.md"}


def is_forbidden(path: str) -> bool:
    return bool(FORBIDDEN.match(path)) and path.rsplit("/", 1)[-1] not in ALLOWED_NAMES


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return [path for path in result.stdout.decode("utf-8").split("\0") if path]


@unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(), "requires a git checkout")
class RepositoryHygieneTest(unittest.TestCase):
    def test_no_third_party_source_text_is_tracked(self) -> None:
        offending = [path for path in tracked_files() if is_forbidden(path)]
        self.assertEqual(offending, [], "third-party source text must not be committed")

    def test_pattern_matches_known_copy_names(self) -> None:
        for path in (
            "stories/a/source.md",
            "stories/a/Source.md",
            "stories/a/SOURCE.MD",
            "stories/a/source.original-mixed-encoding.md",
            "stories/a/source-original.md",
            "stories/a/source_backup.md",
            "stories/a/source.md.bak",
            "stories/a/source.md~",
            "corpus/a/source.bak.md",
            "corpus/a/原文.md",
            "corpus/a/原文-备份.markdown",
            "corpus/a/《原文》.txt",
        ):
            self.assertTrue(is_forbidden(path), path)
        for path in (
            "corpus/a/SOURCE_CORRUPT.md",
            "stories/a/source-rhythm-rewrite-todo.json",
            "stories/a/final.md",
            "stories/a/dissection.md",
            "prompts/production/source-dissection.md",
        ):
            self.assertFalse(is_forbidden(path), path)


if __name__ == "__main__":
    unittest.main()
