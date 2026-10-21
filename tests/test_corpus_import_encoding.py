"""Import synthetic multilingual ZIP fixtures without corrupting source text."""
import importlib.util
from pathlib import Path
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

SPEC = importlib.util.spec_from_file_location(
    "corpus_zip_importer", Path(__file__).resolve().parents[1] / "scripts/import-corpus-zips.py")
importer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(importer)


@pytest.mark.parametrize("text,encoding", [
    ("你好世界", "gbk"),
    ("这是一个中文故事。", "gbk"),
    ("第一章 回家", "gbk"),
    ("你好𠀀世界", "gb18030"),
    ("你好世界", "utf-8"),
    ("你好世界", "utf-8-sig"),
    ("hello world", "ascii"),
    ("", "utf-8"),
])
def test_source_text_decodes_without_bomless_utf16_guess(text, encoding):
    assert importer.decode_text(text.encode(encoding)) == text


@pytest.mark.parametrize("encoding,bom", [("utf-16-le", b"\xff\xfe"),
                                         ("utf-16-be", b"\xfe\xff")])
def test_utf16_with_bom_remains_supported(encoding, bom):
    text = "第一章：你好世界。"
    assert importer.decode_text(bom + text.encode(encoding)) == text


def test_real_zip_roundtrip_and_cross_encoding_deduplication(tmp_path):
    archive = tmp_path / "stories.zip"
    text = "这是一个中文故事。"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("GBK故事.txt", text.encode("gbk"))
        handle.writestr("UTF8故事.txt", text.encode("utf-8"))
        handle.writestr("UTF16故事.txt", text.encode("utf-16"))
    before = archive.read_bytes()
    corpus = tmp_path / "corpus"
    report = importer.import_archives([archive], corpus, dry_run=False)
    assert report["errors"] == []
    assert len(report["imported"]) == 1
    assert len(report["duplicates"]) == 2
    source = corpus / report["imported"][0]["slug"] / "source.md"
    assert importer.canonical_body(source.read_text(encoding="utf-8")) == text
    assert report["imported"][0]["word_count"] == len(text)
    again = importer.import_archives([archive], corpus, dry_run=False)
    assert again["imported"] == []
    assert len(again["duplicates"]) == 3
    assert archive.read_bytes() == before


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_explicit_bomless_utf16(encoding):
    text = "你好世界 ASCII"
    assert importer.decode_text(text.encode(encoding), encoding) == text


@pytest.mark.parametrize("encoding", ["not-a-codec", "base64_codec", "rot_13", "hex_codec", "zlib_codec"])
def test_invalid_or_nontext_codec_fails_before_writes(tmp_path, encoding):
    corpus = tmp_path / "new-corpus"
    with pytest.raises(ValueError, match="Unsupported text encoding"):
        importer.import_archives([], corpus, dry_run=False, encoding=encoding)
    assert not corpus.exists()


def test_bad_text_members_are_reported_without_source_artifacts(tmp_path):
    archive = tmp_path / "inputs.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("nul.txt", b"binary\x00payload")
        handle.writestr("control.txt", b"binary\x01payload")
        handle.writestr("undecodable.txt", b"\x81")
        handle.writestr("broken-utf16.txt", b"\xff\xfe\x00")
        handle.writestr("image.png", b"\x89PNG\x00")
        handle.writestr("good.txt", "你好世界".encode("gbk"))
    report = importer.import_archives([archive], tmp_path / "corpus", dry_run=False)
    assert len(report["errors"]) == 4
    assert len(report["imported"]) == 1
    assert report["imported"][0]["title"] == "good"
    assert len(list((tmp_path / "corpus").glob("*/source.md"))) == 1


def test_cli_explicit_encoding_and_invalid_option(tmp_path):
    import subprocess
    import sys
    archive = tmp_path / "utf16.zip"
    text = "你好世界"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("story.txt", text.encode("utf-16-be"))
    corpus = tmp_path / "corpus"
    command = [sys.executable, str(SPEC.origin), str(archive), "--corpus", str(corpus)]
    bad = subprocess.run(command + ["--encoding", "rot13"], capture_output=True, text=True)
    assert bad.returncode == 2
    assert "Unsupported text encoding" in bad.stderr
    assert not corpus.exists()
    good = subprocess.run(command + ["--encoding", "utf-16-be", "--json"], capture_output=True, text=True)
    assert good.returncode == 0, good.stderr
    source = next(corpus.glob("*/source.md"))
    assert importer.canonical_body(source.read_text()) == text
