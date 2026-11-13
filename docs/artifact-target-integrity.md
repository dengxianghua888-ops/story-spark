# Unique artifact targets in model bundles

An artifact bundle must not silently select one of several declarations for the
same output. Previously, the parser's dictionary selected the last complete
block, and the apply path could collapse another pair after stripping the
accepted `story/` prefix. The omitted content was not represented in the parse
report. A conflicting earlier manuscript could therefore disappear while a
later version passed validation and published.

## Contract

- Each recognized `<<<FILE: ...>>>` declaration must identify a unique output
  within its bundle, including declarations whose block is incomplete. A
  duplicate rejects the bundle with `duplicate artifact target`, even when
  both bodies are identical. No automatic winner or deduplicated response is
  produced, and the input response is not rewritten.
- Identity uses the existing relative-path normalization and the apply path's
  single optional `story/` prefix. For example, `./draft.md`, `draft.md` and
  `story/draft.md` collide. Repeated separators and `.` components also follow
  the existing `Path` normalization. Case and Unicode normalization are not
  changed; this does not add case-insensitive filesystem alias protection.
- Unique bundles retain their existing return labels, content handling,
  whitelist checks and standalone syntactic publication contract. The legacy
  single unclosed block remains supported. This is not a general rewrite of
  the bundle grammar or its recovery rules for otherwise distinct targets.
- The split-scene writer does not fall back after a parsing error if the response
  contains a recognized `FILE` declaration. An invalid path before duplicate
  declarations must not bypass rejection. A rejected structured bundle is not
  reinterpreted through Markdown, XML-like or unclosed-block fallbacks. Existing
  unique alternate-format responses without `FILE` declarations remain
  supported; uniqueness of those separate formats is not newly guaranteed.
- The pipeline records a writable parse-failure manifest as `failed`, including
  a reused run ID. Failed parsing does not publish candidate manuscript bytes
  or replace a prior completed snapshot. Other failure branches and unwritable
  audit destinations retain their existing behavior.

## Verification

`tests/test_artifact_target_uniqueness.py` covers exact and normalized collisions,
equal/conflicting bodies, incomplete duplicate declarations, distinct targets,
legacy unique responses, the real standalone apply CLI in all four modes, the
real mock-runner pipeline in production/ultra-short/V6, reused-run failure
metadata, preserved source/live/snapshot bytes and the split-scene fallback
boundary. These are offline synthetic tests, not live-model, real-reader or
submission-platform acceptance.

Run `python -m pytest -q`, `python -m compileall -q scripts tests`, fatal Ruff
checks and Bash syntax checks. This change is independent of PR #15's chapter
hook coverage check. Both changes can be tested together, but neither change
grants approval to merge or deploy the other.

## Practice consulted

CPython 3.12.8 `ConfigParser(strict=True)` rejects duplicate normalized option
identities within one input instead of silently choosing the last declaration.
Its dedicated `DuplicateOptionError` separates an ambiguous declaration from
unrecognized input. This patch adopts that validation principle using a small
original set-based check and a specific exception; no upstream code is copied
and no dependency is added.

- Source: https://github.com/python/cpython/blob/v3.12.8/Lib/configparser.py
- License: https://github.com/python/cpython/blob/v3.12.8/LICENSE (PSF license and
  the historical notices in that file)

Story Spark's absent root license and source-story rights are unchanged.
