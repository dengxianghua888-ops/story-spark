# ZIP corpus import and interrupted runs

`python scripts/import-corpus-zips.py archive.zip --corpus /path/to/corpus --json`
imports text members and skips content already present in `*/source.md`. The
default text formats are UTF-8, BOM-tagged UTF-16 and GB18030. For ambiguous
BOM-less UTF-16, pass `--encoding utf-16-le` or `--encoding utf-16-be` explicitly.

Each source and `_manifest.tsv` use the existing shared same-directory temporary
file and atomic replacement helper. A source write or manifest write failure
leaves the previous destination intact. New sources are committed before the
manifest: after an interrupted run, rerun the import to reconcile missing rows
from complete sources with the importer's JSON provenance. The result's
`recovered` list identifies those rows. The original `source_file` filename and
the canonical body's character count are retained, even if a retried ZIP uses a
different filename for the same text. Existing manifest rows and their status
values are preserved, and existing source bodies are never rewritten.

`--dry-run` reports candidate imports and rows to recover without writing source
or manifest files, creating directories, or acquiring the import write lock.
Existing directories, including leftovers from a terminated
write, reserve their slug names; new imports receive a suffix rather than
overwriting their contents. Legacy sources without the importer's provenance
and malformed provenance do not receive guessed metadata. Recovery cannot
authenticate or reconstruct a body that was already truncated by an older
version or later modified by another writer.

The manifest is a plain four-column TSV, consumed with tab splitting and
`splitlines()`, not CSV quoting. A source filename containing a tab or any
`splitlines()` line separator cannot be represented safely. Such ZIP members
are reported in `errors` before a source is created; other valid members still
import. Rename the affected member and retry. A complete legacy source with
such a filename in its JSON provenance stops recovery with a clear error,
preserving source and manifest bytes. Existing malformed TSV rows are not
automatically repaired because their intended field boundaries are unknown.
The real importer may still create its stable lock file before this error.

Run `python -m pytest tests/test_corpus_manifest_boundaries.py -q` for synthetic
filename and non-mutating-preview regressions. No source text, model, account,
or paid service is used in these tests.

The defect affected missing `filename` and `word_count` metadata. The index
builder still scans corpus directories, so this is not a claim that an omitted
manifest row deleted or hid the source body. The regression suite imports two
synthetic texts from a real ZIP, interrupts after the first committed source,
then rebuilds the real index after replay. It also injects partial temporary
manifest writes and failed replacements while checking previous manifest bytes,
file mode, existing status and source bytes.

Reproduce with `python -m pytest tests/test_corpus_import_encoding.py
tests/test_corpus_import_recovery.py -q`, or run the new failure/replay tests with
`python tests/test_corpus_import_recovery.py -v` using only the standard library.
Run the repository checks with `python -m pytest -q` and
`python -m compileall -q scripts tests`. There is no separate packaging target.
These are synthetic offline checks, with no model calls or third-party source
text. Recovery addresses process interruption for a single importer; it does
not establish a concurrent-writer transaction or filesystem power-loss
durability.

The implementation reuses `storyforge_lib.write_text`; it adds no dependency or
copied third-party implementation. Boltons
[AtomicSaver](https://boltons.readthedocs.io/en/latest/fileutils.html#boltons.fileutils.AtomicSaver)
uses a related temporary-file replacement mechanism under
[BSD-3-Clause](https://github.com/mahmoud/boltons/blob/master/LICENSE). It was a
mechanism reference only.
