# Split-scene responses belong to one invocation

Reusing a split-scene run ID also reused `batchNN.codex.out` and repair output
paths. If the next provider process exited successfully without writing its
last-message file, the script read the previous file instead of the current
stdout. An old, valid scene bundle could therefore replace the current reviewed
draft while the new run reported success. A valid old repair response could
likewise rescue a failed current retry. Neither a zero exit code nor an existing
output file establishes that this invocation produced the response.

## Narrow contract

- After the existing source-access and blueprint-approval rechecks, each model
  invocation gets a newly created directory inside the owning run directory.
  Its `codex.out` destination starts absent. Initial attempts, repairs and later
  invocations with the same run ID all use distinct destinations.
- Only that destination or the current process's stdout is consumed. A current
  file retains precedence over stdout, including an empty file. Empty/invalid
  output still follows the existing parsing failure and retry policy. A nonzero
  exit or timeout does not publish any response.
- Previous fixed-name outputs and the new invocation directories are retained,
  not deleted, renamed or relabelled as new responses. Successful and failed
  parsed attempts record their actual output destination. Existing fixed-name
  prompts/logs and the latest report keep their previous replacement behavior;
  this is not a complete immutable audit-log redesign.
- Fresh identical content is valid. No timestamp or content-difference heuristic
  is used to infer freshness. Staged story publication, source policy, approval
  gates, quality thresholds and stdout compatibility are unchanged.

The unique directory prevents accidental reuse by this entry point. It is not
authentication of an external provider or protection against an uncooperative
same-user filesystem writer. The change does not certify literary quality or
authorize model access to a source. It does not change the separate composite
runner or its existing isolated-workspace behavior.

## Offline verification

`tests/test_scene_output_freshness.py` covers reused outputs, silent/invalid
responses, real successful reruns, repair retries, identical fresh content,
file/stdout precedence, nonzero exits and timeouts, preserved live artifacts and
retained previous responses. Three cases invoke the actual split-scene CLI with
a locally authored fake `codex` executable; no model service is called.

The 17 regressions yield 11 failures and 6 passes against unchanged main
`4860890bb2d61e2211c12190201cd544b596cec5`, and all pass with the fix. The original
main suite passes 539 tests with its one existing local-only copyrighted-fixture
skip. Run the complete suite, compile checks, fatal Ruff and Bash syntax checks
for a final candidate; exact results and commit identity belong in the PR.

## Practice consulted

The pipeline already isolates its main runner in a fresh temporary workspace.
The split runner now applies the same isolation principle to its output path,
using the Python standard library's `tempfile.mkdtemp`, which creates the
directory rather than merely suggesting a filename. No upstream code was
copied and no dependency was added.

- CPython 3.12.8 implementation: https://github.com/python/cpython/blob/v3.12.8/Lib/tempfile.py
- License: https://github.com/python/cpython/blob/v3.12.8/LICENSE (PSF license
  and historical notices)

The repository's absent root license and source-story rights are unchanged.
