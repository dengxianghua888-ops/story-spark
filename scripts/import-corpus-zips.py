#!/usr/bin/env python3
"""Import batches of txt stories from ZIP archives into corpus/.

The WeChat/Windows archives in this workflow usually store filenames as GBK
without setting the ZIP UTF-8 flag. Python sees those names as mojibake unless
we recover the original bytes from CP437 first.
"""

from __future__ import annotations

import argparse
import codecs
import contextlib
import datetime as dt
import hashlib
import json
import sys
import zipfile
from pathlib import Path

from storyforge_lib import write_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "corpus"


def decode_zip_name(name: str, utf8_flag: bool) -> str:
    if utf8_flag:
        return name
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    for encoding in ("gb18030", "gbk", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return name


def text_encoding(encoding: str | None) -> str | None:
    """Validate an explicit text codec before creating any import output."""
    if encoding is None:
        return None
    try:
        codec = codecs.lookup(encoding)
        try:
            b"\x00".decode(codec.name)
        except UnicodeDecodeError:
            # Incomplete character data still proves this is a text decoder.
            pass
    except (LookupError, TypeError, ValueError) as exc:
        raise ValueError(f"Unsupported text encoding: {encoding}") from exc
    return codec.name


def decode_text(data: bytes, encoding: str | None = None) -> str:
    """Prefer BOMs and the documented UTF-8/Windows Chinese source formats.

    BOM-less UTF-16 is ambiguous with legacy encodings; callers must explicitly
    select utf-16-le or utf-16-be instead of guessing the host byte order.
    """
    encoding = text_encoding(encoding)
    if encoding is not None:
        text = data.decode(encoding)
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("gb18030")
    if any(ord(char) < 32 and char not in "\t\r\n" or ord(char) == 127 for char in text):
        raise ValueError("Non-text control characters; check the input or specify --encoding")
    return text


def canonical_body(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + len("\n---\n") :]
    return text.lstrip("\ufeff\n ")


def fingerprint(text: str) -> str:
    body = canonical_body(text).strip()
    return hashlib.sha1(body.encode("utf-8")).hexdigest()


def load_existing_fingerprints(corpus: Path) -> dict[str, str]:
    existing: dict[str, str] = {}
    if not corpus.exists():
        return existing
    for source in corpus.glob("*/source.md"):
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = source.read_text(encoding="utf-8", errors="replace")
        existing[fingerprint(text)] = source.parent.name
    return existing


def load_manifest(manifest_path: Path) -> tuple[list[str], set[str]]:
    if not manifest_path.exists():
        return ["slug\tfilename\tword_count\tstatus\n"], set()
    lines = manifest_path.read_text(encoding="utf-8").splitlines(keepends=True)
    if not lines:
        return ["slug\tfilename\tword_count\tstatus\n"], set()
    slugs = set()
    for line in lines[1:]:
        if line.strip():
            slugs.add(line.split("\t", 1)[0])
    return lines, slugs


def append_manifest_row(lines: list[str], slug: str, filename: str, word_count: int) -> None:
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.append(f"{slug}\t{filename}\t{word_count}\tpending\n")


def recover_manifest(corpus: Path, lines: list[str], slugs: set[str]) -> list[dict[str, object]]:
    """Reconcile complete importer sources left ahead of the manifest by a failure.

    Only the importer's JSON provenance is used. Existing rows, source contents,
    and sources without that provenance are left alone; a duplicate ZIP member
    may have a different filename and must not rename the original source.
    """
    recovered = []
    for source in sorted(corpus.glob("*/source.md")):
        slug = source.parent.name
        if slug in slugs:
            continue
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---\n", 4)
        if end == -1:
            continue
        metadata = {}
        try:
            for line in text[4:end].splitlines():
                key, separator, value = line.partition(": ")
                if separator:
                    metadata[key] = json.loads(value)
        except ValueError:
            continue
        if metadata.get("slug") != slug or not all(
            isinstance(metadata.get(key), str)
            for key in ("source_file", "source_archive", "source_member", "imported_at")
        ):
            continue
        filename = metadata["source_file"]
        word_count = len(canonical_body(text))
        append_manifest_row(lines, slug, filename, word_count)
        slugs.add(slug)
        recovered.append({"slug": slug, "filename": filename, "word_count": word_count})
    return recovered


def make_slug(title: str, text: str, used: set[str]) -> str:
    digest = hashlib.sha1((title + "\n" + canonical_body(text)[:1000]).encode("utf-8")).hexdigest()
    base = f"hot_{digest[:10]}"
    slug = base
    i = 2
    while slug in used:
        slug = f"{base}_{i}"
        i += 1
    used.add(slug)
    return slug


def q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_source(
    corpus: Path,
    slug: str,
    title: str,
    text: str,
    archive: Path,
    member_name: str,
    imported_at: str,
) -> None:
    target_dir = corpus / slug
    target_dir.mkdir(parents=True, exist_ok=False)
    (target_dir / "analysis").mkdir()
    body = canonical_body(text)
    frontmatter = "\n".join(
        [
            "---",
            f"source_file: {q(title + '.txt')}",
            f"slug: {q(slug)}",
            f"source_archive: {q(str(archive))}",
            f"source_member: {q(member_name)}",
            f"imported_at: {q(imported_at)}",
            "---",
            "",
        ]
    )
    try:
        write_text(target_dir / "source.md", frontmatter + body)
    except BaseException:
        # Remove only our newly created empty directories. Preserve any content
        # another writer added, and reserve leftovers on the next invocation.
        with contextlib.suppress(OSError):
            (target_dir / "analysis").rmdir()
        with contextlib.suppress(OSError):
            target_dir.rmdir()
        raise


def iter_txt_members(zip_path: Path):
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            decoded_name = decode_zip_name(info.filename, bool(info.flag_bits & 0x800))
            if info.is_dir() or decoded_name.startswith("__MACOSX/"):
                continue
            if not decoded_name.lower().endswith(".txt"):
                continue
            yield info, decoded_name, archive.read(info)


def import_archives(zip_paths: list[Path], corpus: Path, dry_run: bool,
                    encoding: str | None = None) -> dict[str, object]:
    encoding = text_encoding(encoding)
    corpus.mkdir(parents=True, exist_ok=True)
    manifest_path = corpus / "_manifest.tsv"
    manifest_lines, manifest_slugs = load_manifest(manifest_path)
    recovered = recover_manifest(corpus, manifest_lines, manifest_slugs)
    used_slugs = manifest_slugs | {path.name for path in corpus.iterdir()}
    existing_hashes = load_existing_fingerprints(corpus)
    imported_at = dt.datetime.now().isoformat(timespec="seconds")

    imported = []
    duplicates = []
    errors = []

    for zip_path in zip_paths:
        if not zip_path.exists():
            errors.append({"archive": str(zip_path), "error": "missing"})
            continue
        try:
            members = list(iter_txt_members(zip_path))
        except zipfile.BadZipFile as exc:
            errors.append({"archive": str(zip_path), "error": str(exc)})
            continue

        for _info, member_name, data in members:
            try:
                text = decode_text(data, encoding)
            except (UnicodeError, ValueError) as exc:
                errors.append({"archive": str(zip_path), "member": member_name, "error": str(exc)})
                continue
            digest = fingerprint(text)
            title = Path(member_name).stem
            if digest in existing_hashes:
                duplicates.append(
                    {
                        "archive": zip_path.name,
                        "member": member_name,
                        "existing_slug": existing_hashes[digest],
                    }
                )
                continue

            slug = make_slug(title, text, used_slugs)
            word_count = len(canonical_body(text))
            if not dry_run:
                write_source(corpus, slug, title, text, zip_path, member_name, imported_at)
                append_manifest_row(manifest_lines, slug, title + ".txt", word_count)
            existing_hashes[digest] = slug
            imported.append(
                {
                    "slug": slug,
                    "title": title,
                    "word_count": word_count,
                    "archive": zip_path.name,
                    "member": member_name,
                }
            )

    if not dry_run:
        write_text(manifest_path, "".join(manifest_lines))

    return {
        "imported": imported,
        "duplicates": duplicates,
        "errors": errors,
        "recovered": recovered,
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("zips", nargs="+", help="ZIP archives containing .txt stories")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--encoding", help="Explicit text codec, e.g. utf-16-le for BOM-less UTF-16")
    args = parser.parse_args()

    try:
        result = import_archives([Path(item).expanduser() for item in args.zips], Path(args.corpus), args.dry_run, args.encoding)
    except ValueError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Imported: {len(result['imported'])}")
        print(f"Duplicates skipped: {len(result['duplicates'])}")
        print(f"Errors: {len(result['errors'])}")
        recovery_label = "Manifest rows to recover" if args.dry_run else "Manifest rows recovered"
        print(f"{recovery_label}: {len(result['recovered'])}")
        for item in result["imported"][:20]:
            print(f"  {item['slug']}\t{item['title']}")
        if len(result["imported"]) > 20:
            print(f"  ... +{len(result['imported']) - 20} more")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
