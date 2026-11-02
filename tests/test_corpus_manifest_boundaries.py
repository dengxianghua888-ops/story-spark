"""Synthetic ZIP and filesystem cases for preview and TSV field boundaries."""
import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "manifest_boundary_importer", ROOT / "scripts/import-corpus-zips.py")
importer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(importer)


@pytest.mark.parametrize("separator", ["\t", "\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_unrepresentable_filename_is_reported_before_source_write(tmp_path, separator, dry_run):
    archive = tmp_path / "inputs.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(f"bad{separator}name.txt", "坏名称的合成正文")
        handle.writestr("正常标题.txt", "可正常导入的合成正文")
    before = archive.read_bytes()
    corpus = tmp_path / "corpus"
    result = importer.import_archives([archive], corpus, dry_run)
    assert len(result["errors"]) == 1
    assert result["errors"][0]["member"] == f"bad{separator}name.txt"
    assert len(result["imported"]) == 1
    assert result["imported"][0]["title"] == "正常标题"
    assert archive.read_bytes() == before
    if dry_run:
        assert not corpus.exists()
    else:
        rows = (corpus / "_manifest.tsv").read_text().splitlines()
        assert len(rows) == 2
        assert all(len(row.split("\t")) == 4 for row in rows)
        assert len(list(corpus.glob("*/source.md"))) == 1


def test_preview_does_not_create_missing_parent_or_lock(tmp_path):
    corpus = tmp_path / "absent-parent" / "corpus"
    result = importer.import_archives([], corpus, True)
    assert result["dry_run"]
    assert not corpus.parent.exists()


@pytest.mark.parametrize("separator", ["\t", "\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
def test_recovery_rejects_unrepresentable_provenance_without_mutation(tmp_path, separator):
    corpus = tmp_path / "corpus"
    importer.write_source(corpus, "legacy", f"bad{separator}name", "合成正文", tmp_path / "old.zip",
                          f"bad{separator}name.txt", "2026-10-31")
    original = "slug\tfilename\tword_count\tstatus\n"
    manifest = corpus / "_manifest.tsv"
    manifest.write_text(original)
    source = corpus / "legacy" / "source.md"
    saved = source.read_bytes()
    with pytest.raises(ValueError, match="filename"):
        importer.import_archives([], corpus, False)
    assert manifest.read_text() == original
    assert source.read_bytes() == saved
