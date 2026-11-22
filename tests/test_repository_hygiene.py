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

# Original inputs and any renamed copy/backup of them (source.md,
# source.original-mixed-encoding.md, source.bak.md, raw *.txt imports).
FORBIDDEN = re.compile(r"^(corpus|stories)/(.+/)?(source(\.[^/]*)?\.md|[^/]+\.txt)$")


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
        offending = [path for path in tracked_files() if FORBIDDEN.match(path)]
        self.assertEqual(offending, [], "third-party source text must not be committed")

    def test_pattern_matches_known_copy_names(self) -> None:
        for path in (
            "stories/a/source.md",
            "stories/a/source.original-mixed-encoding.md",
            "corpus/a/source.bak.md",
            "corpus/a/《原文》.txt",
        ):
            self.assertRegex(path, FORBIDDEN)
        for path in (
            "stories/a/source-dissection.md",
            "corpus/a/SOURCE_CORRUPT.md",
            "stories/a/final.md",
        ):
            self.assertNotRegex(path, FORBIDDEN)


if __name__ == "__main__":
    unittest.main()
