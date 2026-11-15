# Run status lifecycle

A reused run ID preserves its historical artifacts, but not the previous execution's terminal status. Once argument, source-access and bundle preflight checks accept a run, the manifest starts `running` with terminal fields cleared. Each phase/retry starts `running` again.

- `completed`: all requested phases succeeded; `exit_code` is 0. Existing dry-run semantics are preserved: a completed dry-run means planning completed, not that a provider ran or artifacts were published.
- `paused`: the current attempt generated a manual prompt pack or explicitly requires human approval. Old awaiting-manual markers alone cannot establish this state.
- `failed`: the current accepted execution failed, including handled runner, normalization, validation, rubric, staging/publication or audit exceptions before successful completion.
- `blocked`: source-access policy stopped an accepted execution.

Existing exit codes and retry policies are unchanged. In particular, legacy beat-phase failures may return 24 even when no human pause occurred; consult the explicit status rather than treating every 24 as a pause. Manual prompt packs continue returning 23.

Completed snapshots, prior phase records and published artifacts remain historical evidence, not proof that the current execution completed. No approval, source-policy or literary-quality threshold is relaxed. Preflight rejection before run acceptance keeps its existing no-write contract, so an earlier manifest may remain untouched; the current command's exit and diagnostic are authoritative in that case.

Summary and manifest finalization are attempted independently. Audit storage failures are reported without hiding the original exit or falsely claiming a committed publication was rolled back. Unwritable manifests and abrupt process termination cannot guarantee a durable terminal status; `running` is not a success claim.

Regression coverage uses synthetic fixtures, offline mock/manual runners and injected failures. It does not certify authenticated providers or literary quality. The isolation of current execution status from previous success follows the same lifecycle principle as CPython's [Popen implementation at v3.12.8](https://github.com/python/cpython/blob/v3.12.8/Lib/subprocess.py); no source code or dependency was copied.
