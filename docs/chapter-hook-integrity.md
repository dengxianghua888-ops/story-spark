# Chapter hook coverage must identify actual chapters

The final-package contract requires a nonempty hook for every delivered chapter.
Previously the coverage check counted arbitrary table rows and capped the total
at the number of chapter files. Repeating chapter 01, referring only to nonexistent
chapters, or adding unrelated table rows could therefore pass with 100% coverage.
It also discarded legitimate rows if their prose contained `Hook`, `---`, or both
`章` and `钩`. All three production modes were affected.

## Behavior and compatibility

- Count a hook only for an actual `final-chapters/chNN.md` file, using its numeric
  identity rather than row order. Numeric labels (`01`, `1`), `第 1 章`, `ch01`,
  and `ch01.md` remain supported. Row order and gaps in chapter numbering do not
  change identity. The documented labels use Arabic numerals.
- A chapter must have exactly one row. Duplicate aliases or conflicting rows do
  not certify that chapter. Ambiguous filenames such as both `ch1.md` and
  `ch01.md` do not establish coverage for that identity. Unknown rows cannot
  fill a missing chapter.
- Read the chapter table identified by its first-column header (`章`, `章节`,
  `章号`, or `Chapter`), final-column hook/suspense header and Markdown delimiter
  row. Existing three- and four-column formats, aligned delimiters and escaped
  content pipes are supported. Unrelated tables and fenced examples do not
  establish coverage. This is a narrow parser for the repository's map format,
  not a general Markdown renderer.
- Only an all-separator row is a delimiter. Hook text containing control-looking
  words or hyphens is ordinary content. Empty hooks and the existing dash,
  `无`, and case-insensitive `none` placeholders do not count.
- A failed final-stage validator now marks its run manifest `failed`, including
  when a previously completed run ID is reused. The prior successful snapshot
  is retained, never replaced by rejected output. This change does not redefine
  all other failure paths or promise persistence to an unwritable run directory.
- The existing 100% threshold, stage coordinates, manuscript content and map bytes
  are unchanged. The validator rejects invalid packages before publication.

This verifies the presence of chapter-specific declarations, not whether a hook
is compelling or truthfully describes the prose. It does not invent or rewrite
hooks. Existing final/chapter text-consistency and literary checks still apply.

## Verification

`tests/test_chapter_hook_bindings.py` checks real repair/validator gates in
production, ultra-short and production V6, plus actual mock-runner CLI rejection
and valid publication in all three modes. It also covers duplicate/unknown keys,
conflicting aliases, unrelated tables, fenced examples, valid keyword-bearing
prose, map preservation, supported labels/header formats, placeholders, absent
maps/chapters, numbering gaps and ambiguous file aliases.

Run `python -m pytest -q`, `python -m compileall -q scripts tests` and fatal Ruff
checks (`E9,F63,F7,F82`). These are synthetic offline regressions. No real model,
reader, copyrighted local-only fixture or submission-platform acceptance is
claimed.

## Practice consulted

Pandas 2.3.3 validates join-key uniqueness for `one_to_one` and `many_to_one`
relationships before treating merged rows as trustworthy. This supports the
principle used here: a row count is not evidence of distinct matching identities.
The implementation uses the standard library; no pandas source was copied and
no dependency was added.

- Source: https://github.com/pandas-dev/pandas/blob/9c8bc3e55188c8aff37207a74f1dd144980b8874/pandas/core/reshape/merge.py#L1632-L1675
- License: BSD-3-Clause, https://github.com/pandas-dev/pandas/blob/9c8bc3e55188c8aff37207a74f1dd144980b8874/LICENSE

The repository's existing lack of a root license remains unchanged. This
reference grants no new redistribution rights to manuscripts or the repository.
