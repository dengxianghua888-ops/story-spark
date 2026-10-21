"""Failure/replay contracts using real ZIP files and synthetic source text."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
lib = importlib.import_module("storyforge_lib")

SPEC = importlib.util.spec_from_file_location("recoverable_corpus_importer", ROOT / "scripts/import-corpus-zips.py")
importer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(importer)


class CorpusRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="corpus-recovery-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.corpus = self.root / "corpus"
        self.archive = self.root / "two.zip"
        self.texts = {"第一篇.txt": "第一篇合成正文。", "第二篇.txt": "第二篇合成正文。"}
        with zipfile.ZipFile(self.archive, "w") as handle:
            for filename, text in self.texts.items():
                handle.writestr(filename, text.encode("utf-8"))

    def run_import(self, paths=None, dry_run=False):
        return importer.import_archives(paths if paths is not None else [self.archive], self.corpus, dry_run)

    def manifest(self):
        rows = (self.corpus / "_manifest.tsv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(rows[0], "slug\tfilename\tword_count\tstatus")
        return [row.split("\t") for row in rows[1:]]

    def test_second_source_failure_replays_with_both_metadata_rows_and_no_source_changes(self):
        real_write = importer.write_source
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected second source failure")
            return real_write(*args, **kwargs)

        with (
            patch.object(importer, "write_source", fail_second),
            self.assertRaisesRegex(OSError, "second source failure"),
        ):
            self.run_import()
        first = next(self.corpus.glob("*/source.md"))
        saved = first.read_bytes()
        self.assertFalse((self.corpus / "_manifest.tsv").exists())
        report = self.run_import()
        self.assertEqual(len(report["imported"]), 1)
        self.assertEqual(len(report["duplicates"]), 1)
        self.assertEqual(len(report["recovered"]), 1)
        self.assertEqual(first.read_bytes(), saved)
        rows = self.manifest()
        self.assertEqual(len(rows), 2)
        self.assertEqual({row[1]: int(row[2]) for row in rows},
                         {name: len(text) for name, text in self.texts.items()})
        before = (self.corpus / "_manifest.tsv").read_bytes()
        again = self.run_import()
        self.assertEqual(again["imported"], [])
        self.assertEqual(again["recovered"], [])
        self.assertEqual((self.corpus / "_manifest.tsv").read_bytes(), before)

    def test_abrupt_process_exit_after_source_commit_recovers_on_next_process(self):
        script = """
import os
from pathlib import Path
import runpy
import sys
sys.path.insert(0, sys.argv[1])
namespace = runpy.run_path(str(Path(sys.argv[1]) / 'import-corpus-zips.py'))
original = namespace['write_source']
def commit_then_exit(*args, **kwargs):
    original(*args, **kwargs)
    os._exit(73)
namespace['import_archives'].__globals__['write_source'] = commit_then_exit
namespace['import_archives']([Path(sys.argv[2])], Path(sys.argv[3]), False)
"""
        result = subprocess.run([sys.executable, "-c", script, str(ROOT / "scripts"),
                                 str(self.archive), str(self.corpus)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(len(list(self.corpus.glob("*/source.md"))), 1)
        self.assertFalse((self.corpus / "_manifest.tsv").exists())
        report = self.run_import()
        self.assertEqual(len(report["recovered"]), 1)
        self.assertEqual(len(self.manifest()), 2)

    def test_partial_manifest_temporary_write_preserves_old_manifest_and_recovers_sources(self):
        self.corpus.mkdir()
        original = b"slug\tfilename\tword_count\tstatus\nold\told.txt\t14\tdissected\n"
        path = self.corpus / "_manifest.tsv"
        path.write_bytes(original)
        real_fdopen = lib.os.fdopen

        class PartialWrite:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.handle.close()

            def write(self, value):
                self.handle.write(value[:5])
                self.handle.flush()
                raise OSError("injected partial temporary manifest write")

        def fail_manifest_write(target, text):
            if target != path:
                return lib.write_text(target, text)
            with patch.object(lib.os, "fdopen", lambda *a, **kw: PartialWrite(real_fdopen(*a, **kw))):
                return lib.write_text(target, text)

        with (
            patch.object(importer, "write_text", fail_manifest_write),
            self.assertRaisesRegex(OSError, "partial temporary manifest"),
        ):
            self.run_import()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.corpus.glob(".*.tmp")), [])
        self.assertEqual(len(list(self.corpus.glob("*/source.md"))), 2)
        report = self.run_import()
        self.assertEqual(len(report["recovered"]), 2)
        self.assertEqual(report["imported"], [])
        self.assertEqual(self.manifest()[0], ["old", "old.txt", "14", "dissected"])
        self.assertEqual(len(self.manifest()), 3)

    def test_manifest_replace_failure_preserves_old_bytes_and_mode(self):
        self.corpus.mkdir()
        path = self.corpus / "_manifest.tsv"
        original = b"slug\tfilename\tword_count\tstatus\nold\told.txt\t14\tcustom\n"
        path.write_bytes(original)
        path.chmod(0o640)
        real_replace = lib.os.replace

        def fail_replace(source, target):
            if target == path:
                raise OSError("injected manifest replace failure")
            return real_replace(source, target)

        with (
            patch.object(lib.os, "replace", fail_replace),
            self.assertRaisesRegex(OSError, "manifest replace"),
        ):
            self.run_import()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(list(self.corpus.glob(".*.tmp")), [])
        self.assertEqual(len(self.run_import()["recovered"]), 2)
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)

    def test_source_replace_failure_never_publishes_partial_body_and_can_retry(self):
        real_replace = lib.os.replace

        def fail_replace(source, target):
            if target.name == "source.md":
                raise OSError("injected source replace failure")
            return real_replace(source, target)

        with (
            patch.object(lib.os, "replace", fail_replace),
            self.assertRaisesRegex(OSError, "source replace"),
        ):
            self.run_import()
        self.assertEqual(list(self.corpus.glob("*/source.md")), [])
        self.assertEqual(list(self.corpus.glob("*/.*.tmp")), [])
        self.assertEqual(len(self.run_import()["imported"]), 2)
        self.assertEqual(len(self.manifest()), 2)

    def test_recovery_uses_original_filename_when_zip_duplicate_is_renamed(self):
        importer.write_source(self.corpus, "original", "原始标题", "第一篇合成正文。",
                              self.archive, "原始标题.txt", "synthetic-time")
        original = (self.corpus / "original" / "source.md").read_bytes()
        alias = self.root / "renamed.zip"
        with zipfile.ZipFile(alias, "w") as handle:
            handle.writestr("另一个名字.txt", "第一篇合成正文。".encode())
        report = self.run_import(paths=[alias])
        self.assertEqual(report["imported"], [])
        self.assertEqual(report["recovered"], [{"slug": "original", "filename": "原始标题.txt", "word_count": 8}])
        self.assertEqual(self.manifest(), [["original", "原始标题.txt", "8", "pending"]])
        self.assertEqual((self.corpus / "original" / "source.md").read_bytes(), original)

    def test_dry_run_reports_recovery_without_writing_manifest_or_sources(self):
        importer.write_source(self.corpus, "original", "原始标题", "第一篇合成正文。",
                              self.archive, "原始标题.txt", "synthetic-time")
        before = {path.relative_to(self.corpus): path.read_bytes() for path in self.corpus.rglob("*") if path.is_file()}
        report = self.run_import(dry_run=True)
        self.assertEqual(len(report["recovered"]), 1)
        self.assertEqual(len(report["imported"]), 1)
        after = {path.relative_to(self.corpus): path.read_bytes() for path in self.corpus.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        self.assertFalse((self.corpus / "_manifest.tsv").exists())

    def test_existing_row_and_status_are_not_recalculated(self):
        self.run_import()
        path = self.corpus / "_manifest.tsv"
        modified = path.read_text().replace("\tpending\n", "\thuman-approved\n").replace("\t8\t", "\t99\t")
        path.write_text(modified)
        report = self.run_import()
        self.assertEqual(report["recovered"], [])
        self.assertEqual(path.read_text(), modified)

    def test_incomplete_existing_directory_is_reserved_and_preserved(self):
        used = set()
        slug = importer.make_slug("第一篇", self.texts["第一篇.txt"], used)
        stale = self.corpus / slug
        stale.mkdir(parents=True)
        (stale / "owner-note").write_text("retain this user work")
        report = self.run_import()
        self.assertEqual(report["imported"][0]["slug"], slug + "_2")
        self.assertEqual((stale / "owner-note").read_text(), "retain this user work")
        self.assertFalse((stale / "source.md").exists())

    def test_legacy_or_malformed_source_does_not_get_invented_metadata(self):
        cases = [b"legacy plain body", b"---\nsource_file: not-json\n---\nbody",
                 b"---\nslug: \"wrong\"\nsource_file: \"name.txt\"\n---\nbody", b"\xff"]
        for index, data in enumerate(cases):
            source = self.corpus / f"legacy{index}" / "source.md"
            source.parent.mkdir(parents=True)
            source.write_bytes(data)
        report = self.run_import(paths=[])
        self.assertEqual(report["recovered"], [])
        self.assertEqual(self.manifest(), [])

    def test_empty_manifest_and_missing_final_newline_are_recoverable(self):
        self.corpus.mkdir()
        path = self.corpus / "_manifest.tsv"
        for initial in (b"", b"slug\tfilename\tword_count\tstatus\nold\told.txt\t14\tdissected"):
            with self.subTest(initial=initial):
                path.write_bytes(initial)
                self.run_import()
                rows = self.manifest()
                self.assertEqual(len(rows), 2 + bool(initial))
                self.assertEqual({row[1] for row in rows if row[0] != "old"}, set(self.texts))

    def test_real_index_rebuild_receives_recovered_filename_and_word_count(self):
        self.run_import()
        path = self.corpus / "_manifest.tsv"
        path.write_text("slug\tfilename\tword_count\tstatus\n")
        recovered = self.run_import()
        self.assertEqual(len(recovered["recovered"]), 2)
        command = [sys.executable, str(ROOT / "scripts/update-corpus-index.py"), "--corpus", str(self.corpus)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        entries = json.loads((self.corpus / "_index.json").read_text())["entries"]
        self.assertEqual(len(entries), 2)
        self.assertEqual({entry["filename"]: entry["word_count"] for entry in entries},
                         {name: len(text) for name, text in self.texts.items()})


if __name__ == "__main__":
    unittest.main()
