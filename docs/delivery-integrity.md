# Delivery integrity (2026-11-03)

This change repairs three concrete consistency bugs; it does not add a new editorial score or human-acceptance gate.

- The direct-submission repair may normalize chapter heading levels. It must not invent story events to fill a missing paywall map. Missing/short maps return `manual_review_required`, actual/required row counts and a request for story-grounded editorial input. Existing submission bytes are preserved; a missing file is not created. The existing final-phase validator still enforces the required map.
- The existing final-package check now compares each H2 `第N章` chapter body in `final.md` with the ordered `final-chapters/ch*.md` files. Title/guide text, a chapter file's optional leading Markdown heading and whitespace are packaging, not story content. Missing, extra, reordered, duplicated or edited bodies fail `chapter_text_consistency`. This is a deterministic text check, not a claim of literary equivalence. Chapter boundaries follow `prompts/production/final-packager.md`: H2 `第N章` headings (spaces and Chinese numerals accepted). Other H2 subheadings remain story content. No drift is silently overwritten by this check.
- Numeric scores must be finite. NaN and either infinity are invalid in critic, evaluation and other numeric-score paths using the shared numeric predicate; merely testing ranges is insufficient for NaN. JSON parsing has not been globally changed.

## Acceptance

`tests/test_delivery_integrity.py` covers a different-genre story without a paywall map, partial and complete maps, no submission file, five chapter drift variants, allowed packaging differences real repair-orchestrator/quality-gate propagation, internal H2 subheadings, and all three non-finite float values in critic/evaluation inputs. Existing end-to-end fixture tests remain applicable: the repack test supplies its own actual paywall map instead of relying on fabricated rows, and the V6 rubric test changes both representations so it continues testing the rubric rather than stopping at the earlier consistency check.

Run `python -m compileall -q scripts tests` and `python -m pytest -q`. These offline tests exercise deterministic validation and mock-runner publication; they are not a live-model run, platform submission or real-reader acceptance.

## Practice consulted

Pydantic v2.12.3 uses `FiniteFloat = Annotated[float, AllowInfNan(False)]` to separate finite-domain validation from ordinary float acceptance. It is a maintained, established validation library (29,275 GitHub stars when checked on 2026-11-03) under MIT. We adopt the finite-domain principle using the existing standard-library `math.isfinite`, without copying source or adding Pydantic as a dependency.

- Implementation: https://github.com/pydantic/pydantic/blob/v2.12.3/pydantic/types.py
- License: https://github.com/pydantic/pydantic/blob/v2.12.3/LICENSE

The chapter comparison and non-invention behavior follow this repository's existing delivery format and repair conventions. No external service receives manuscripts or private material.

## Mode-aware paywall requirements (2026-11-05)

The direct-submission repair and machine evaluator share the node-count calculation and resolve the same `target_range(story, mode)`. Requirements are `max(1, ceil(max(final_chars, target_min) / 3500))`, not a fixed 10,000-character floor. This preserves production's floor and configured target minima, uses the ultra-short minimum, and follows V6's source-derived minimum. Missing or insufficient maps still require editorial review, without changing submission content.

`tests/test_submission_mode_thresholds.py` covers all three modes through the real repair/validator gate, including complete, insufficient and missing maps, configured minima, source-derived V6 minima, empty text and exact 3,500-character boundaries. The gate tests disable the optional rubric; these are deterministic packaging regressions, not literary-quality or live-model acceptance.

Both paths also share Markdown table-row counting. A row is a delimiter only when every cell is a separator such as `---`, `:---`, or `:---:`; `---` inside a story-content cell does not discard the node. Six full-gate regressions cover plain/aligned separators, sufficient and insufficient maps, preserved submission bytes, and the next section's exclusion from node counting. The evaluator's pre-existing chapter-reference fallback is unchanged; the repair still requires the documented table rows.

## Corpus index write safety (2026-11-05)

`update-corpus-index.py` serializes the rebuilt index before using the existing same-directory atomic writer. A write or replacement failure leaves the previous index in place; temporary files are cleaned up existing file mode is retained, and an index symlink continues to point to its target. Files with extended attributes or ownership that cannot be preserved are rejected rather than silently changed. This does not serialize concurrent index builders or guarantee persistence across power loss. The index is still derived from the corpus, not a backup of the source stories. `tests/test_corpus_index_atomic.py` covers replacement failure, cleanup, normal rebuild and file mode.
