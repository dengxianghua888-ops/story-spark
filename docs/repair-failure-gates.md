# Repair failures must block publication

The production pipeline previously recorded repair diagnostics without using
their result. An actual final-stage run could write `manual_review_required`,
pass the separate validator, publish the candidate and mark the run completed.
For example, chapter references without the documented paywall table satisfy
the validator's existing fallback but correctly require editorial review from
the direct-submission repairer. The standalone gate already blocked this manual
review outcome, while the main pipeline did not.

Repair exceptions and explicit `fail` outcomes were also incorrectly aggregated
as `ok`. This could hide a failed repair behind a later passing validator.

## Behavior

- The orchestrator retains individual diagnostics and aggregates exceptions,
  malformed result payloads, unknown statuses and explicit failures as `fail`.
  `manual_review_required` remains distinct. Successful and skipped repairers
  remain valid; a failure takes precedence over a manual-review request.
- Production, ultra-short and production V6 runs reject a non-`ok` aggregate
  before validation, further final normalization, rubric scoring or publication.
  An exception in the repair/final-normalization block also rejects the attempt.
  The run manifest and execution summary record failure, including on a reused
  run ID that previously completed. The existing retry policy and exhausted-run
  exit code 23 are preserved.
- The live story stays unchanged and the existing staging mechanism retains the
  rejected candidate. A failed attempt does not write a completion snapshot.
  Historical successful snapshots are retained, not replaced by failed output.
- The standalone gate reports `repair_fail` for failed/unknown aggregates, using
  exit 26, also used for repair-requested manual review. Validator failures keep
  their existing precedence and exit 23.

The repair CLI remains a diagnostic producer with its historical exit behavior;
the main pipeline and standalone phase gate enforce its structured result.
V4 execution, authorization checks, literary thresholds, submission parsing,
default-branch behavior and dependencies are unchanged. This is not a new human
approval mechanism: existing editorial repair blocks can be resolved through
the configured retry workflow or by correcting the candidate.

## Verification

`tests/test_repair_failure_gates.py` uses synthetic story data and the real mock
runner. Three mode-specific subprocess cases reproduce erroneous publication on
the old implementation. It also covers failed/exceptional/malformed repair
results, a real passing validator behind a failed repair, standalone exit-code
propagation, preservation of published bytes, valid publication, and a reused
completed run ID. Fault injection is used for I/O and malformed-return cases.

Run `python -m pytest -q`, `python -m compileall -q scripts tests`, and the
repository's applicable static checks. No live model, copyrighted local fixture,
real reader or submission-platform acceptance is implied.

## Open-source practice consulted

Invoke 2.2.0 aggregates worker exceptions and raises failures before returning a
successful result. Its explicit opt-in `warn` behavior reinforces that merely
capturing an error must not silently turn it into success. Only this propagation
principle was consulted; no upstream code was copied and no dependency added.

- Source: https://github.com/pyinvoke/invoke/blob/2.2.0/invoke/runners.py#L461-L520
- License: BSD-2-Clause, https://github.com/pyinvoke/invoke/blob/2.2.0/LICENSE

The repository's existing lack of a root license is unchanged; this reference
does not grant new rights to redistribute source stories or the repository.
