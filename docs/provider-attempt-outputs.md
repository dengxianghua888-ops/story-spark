# Automatic responses do not become manual submissions

The composite runner used one `phaseN.model.out` for every provider and its
manual fallback. An automatic process could exit nonzero after writing a valid
bundle. If later automatic providers were unavailable, the manual runner then
accepted that failed response as `manual-existing-output`. A normal pipeline
could report completion and publish it without anyone submitting a manual
response. A fresh workspace per phase did not isolate attempts inside it.

Each automatic provider dispatch now gets a newly created directory under its
runner workspace. Its response path and, for Codex, last-message path belong to
that attempt. Failed responses remain available for diagnostics, but cannot
supply or replace the canonical manual input. Repeated providers also receive
distinct destinations. Successful results identify their own response path;
the pipeline still applies its existing parse, source, approval and quality
gates before publishing. Manual/mock runners retain their existing behavior.

A pre-existing canonical manual bundle remains usable under the pipeline's
existing input-snapshot checks. This is not authentication of who wrote a file,
a migration or audit of historical canonical bundles, or protection against a
same-user uncooperative writer. No provider access policy or literary quality
threshold is changed. Real authenticated providers have not been exercised by
this change.

`tests/test_provider_attempt_outputs.py` uses only local Python, synthetic
content and mocked provider process results. It covers failed and empty
responses, preservation of deliberate manual input, current successful output,
repeated Codex attempts, source denial, and full phase publication/recovery
through the default fallback chain. The existing manual resume tests remain
part of the full regression suite.

## Practice consulted

Python's subprocess documentation separates captured output from a successful
return code. Its `tempfile.mkdtemp` creates an actual unique directory rather
than merely suggesting a name. This patch applies that standard-library
isolation pattern; no upstream code or dependency was copied. Directories are
retained, consistent with this repository's existing diagnostic retention.

- https://docs.python.org/3.12/library/subprocess.html#subprocess.CompletedProcess
- https://docs.python.org/3.12/library/tempfile.html#tempfile.mkdtemp
