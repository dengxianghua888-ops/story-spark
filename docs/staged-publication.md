# Stage-safe StoryForge execution

## Contracts

- Blueprint approval patches only its human-gate value under the same stable writer lock. Metadata writes use same-directory temporary files and atomic replacement, retaining the prior denial on write errors. Automation updates preserve the entire source policy. Even an allowed final-packager story.yaml cannot grant or replace source access. Quoted YAML denial is respected.
- `phase_for_role` is shared by preflight, validation, normalization, retries, repairs and rubric gates. V6 Critic is phase 7 and Final Packager is phase 8; phase 9 is feedback. Critic reads this attempt's draft even if a previous final exists. Both Critic and all later phases require a passing quality gate.
- V6 phase 8 explicitly lists chapter files, map, craft notes and submission package, matching the existing final-packager prompt and validator. Unknown model outputs are rejected in every mode.
- All model files, deterministic normalization/repair and validation/rubric checks run against an isolated sibling tree. Publication uses a single filesystem directory-exchange syscall. Partial candidate writes and failed checks do not change published artifacts. The standalone bundle-apply command stages and atomically applies its syntactic contract; semantic validation remains the pipeline's responsibility.
- Failed candidate quality/review/diff/todo and validator/rubric diagnostics are supplied explicitly to retry prompts without publishing them. Feedback is retained through the scene rewrite and marked resolved only after the corresponding gate succeeds.
- A wildcard output replaces its previous set. Old scenes/chapters are retained in the previous-tree backup, not mixed into the new candidate. Each attempt has its own UUID-like directory and backup location. Existing generated metadata cannot change source approval.

## Platform and operational boundaries

Install test/runtime tooling with `python -m pip install -r requirements-dev.txt`.
Run `python -m pytest -q` and `python -m compileall -q scripts tests`.

Publication requires Linux `renameat2(RENAME_EXCHANGE)` or macOS `renamex_np(RENAME_SWAP)` on a filesystem supporting atomic directory exchange. Linux was exercised in the cloud regression suite. The macOS syscall dispatch, RENAME_SWAP flag/path arguments and ENOTSUP failure mapping are covered by a Linux-hosted mock, but no macOS hardware/filesystem test is claimed. This is a platform behavior change: Windows runs that previously reached in-place writes now fail closed. Unsupported platforms/filesystems fail closed; there is deliberately no non-atomic delete/rename fallback. Never interpret a failed platform check as permission to overwrite files manually.

Cooperating pipeline and standalone-apply writers take a sibling advisory flock, which survives the directory-name exchange and is released after process death. External editors do not participate in that lock: stop editing while a run is publishing. A fingerprint check rejects edits detected during validation, but cannot eliminate the last-instant race with a non-cooperating external writer.

Attempts are retained beside the story as `.STORY.attempt-*/STORY`. Before exchange this is a candidate; after successful exchange it is the previous complete story. `attempt.json` records both original and candidate file fingerprints before exchange so an interrupted process can distinguish the trees without guessing from the directory name. `run-manifest.json` records attempt locations. All snapshots are ignored by Git and are not automatically deleted. These complete-tree backups include source material and run history, require additional disk space, and should be retained/reviewed under the same privacy rules as the story. Clean them up only after the owner verifies they are no longer needed.

The operation guarantees atomic namespace publication, not database-style power-loss durability. No filesystem fsync/power-loss guarantee or concurrent multi-open-reader snapshot isolation is claimed. If a process stops after exchange but before its final log update, inspect the fingerprints and actual files before resuming. The prior version is retained, and repeated attempts never overwrite it.

## Regression evidence (2026-10-15)

The unmodified baseline `fecccd16772ae7356182330b2b27f64a104ca106` had 58 passing, 5 failing, 1 skipped tests on Python 3.12:

1. `test_production_validator_rejects_multi_sentence_paragraphs`: the fixture added a short two-sentence paragraph, now deliberately permitted by mobile rhythm rules. It now creates a genuinely overlong multi-sentence paragraph.
2. `test_production_mock_runner_completes_8_phase_pipeline`: missing rhythm-contract/scene breathing planning in its fixture. Updated explicit fields; also found feedback metadata overwrote mock fixture status and now preserves it.
3. `test_render_phase_prompt_expands_story_glob_inputs`: asserted no missing inputs although optional rewrite inputs were added. It now verifies the requested scene globs are present while acknowledging retry-only inputs.
4. `test_storyforge_normalizes_phase3_and_phase4_fixture_drift`: common fixture lacked current rhythm-contract/scene fields. Updated to current requirements.
5. `test_storyforge_phase7_fallback_repacks_overlong_chapters_from_scenes`: same fixture drift, plus repacking discarded the existing title/guide and feedback changed fixture status. Repacking now preserves the real guide and chapter headings; the fixture supplies a valid guide rather than expecting invention.

The old Critic normalization test expected rejected output to be written live. It now checks the original published report is unchanged and the normalized failed candidate is retained for inspection. New tests cover V6 from-scratch nine-phase mock execution, failing Critic, stale-final selection, phase-8 replacement rubric failure, source-policy retention, unexpected source output, second-file write failure, unique retries/stale files, unsupported publication, external edits, concurrent writers, Darwin dispatch/error mapping and abrupt process exits immediately before/after exchange with fingerprint-based recovery.

There is no packaging/build target or repository lint configuration. Full bytecode compilation is used as the build/syntax check. An explicit whole-tree Ruff E4/E7/E9/F scan reports 29 baseline findings and 26 remaining pre-existing findings after this change (mostly unused variables/imports and legacy test import placement); those unrelated files are not rewritten to mask the baseline. No model calls or paid services are used by these regressions.

## Runner isolation follow-up (PR 1 review)

The attempt is now created **before** prompt rendering or runner execution. The
runner receives only the candidate story and isolated prompt/output paths. Its
working directory is a retained `storyforge-runner-*` system-temporary directory
outside the repository, preventing normal discovery of repository agent config.
The manifest records that path, and logs are copied back to the run directory. A direct candidate artifact write is
rejected even when the runner reports success: only parsed, whitelisted bundles
can publish. Ordinary runner failures retain the candidate without publishing it. This protects
artifact-path writes, subject to the provider limitations below.
Dry runs render the planned prompt without copying the story or recording a failed
attempt. Manual bundles already supplied in a run directory still resume normally.

Provider behavior changes:

- Codex uses `--sandbox read-only` instead of `--full-auto`, and
  `--ignore-user-config` skips user `config.toml` while retaining normal auth.
  See the [official CLI reference](https://developers.openai.com/codex/cli/reference/).
  Custom model/provider settings in that file are no longer inherited; explicit
  `--model` remains supported. Older CLIs that reject the flags fail closed.
- Claude uses `--bare --tools "" --disallowedTools "mcp__*"` for text-in/text-out,
  without auto-loaded customization or model tools. See the
  [official CLI reference](https://code.claude.com/docs/en/cli-reference).
- OpenClaw retains its existing `agent --local` entry point and fallback behavior,
  but runs from the isolated attempt working directory. **It has no verified
  read-only filesystem boundary**: cwd isolation and staged input paths do not
  prevent a model tool from targeting a known absolute live path. The
  [official tool-permission guidance](https://docs.openclaw.ai/gateway/security/tool-permissions)
  requires host-specific configuration that this patch does not change.
  Disabling this provider is deferred pending owner acceptance; this patch does
  not claim to close unrestricted OpenClaw tool writes. Use the manual prompt
  pack when a verified provider boundary is unavailable.

These are invocation contracts, not an independently verified security boundary
against malicious host executables. Codex's read-only sandbox governs local
model-generated commands, not arbitrary external MCP services. User config is
skipped and the cwd is outside the repository, but managed integrations, temporary
directory ancestor configuration, and host policy must still be trusted;
this patch does not prove that every possible external tool is unable to mutate a
live story. Candidate cwd alone is not OS isolation. Tests use fake runners and
inspect exact argv; no real provider/model, account, or user computer was used.

Automation metadata is written to the candidate before exchange. After the commit
point, audit/summary write failures print a warning instead of reporting a failed
phase. Existing file modes survive atomic replacement; newly created files follow
the process umask. Retry feedback includes only changed candidate artifacts and
attempt-specific diagnostic snapshots, never inherited approved reports or later
logs. V4 early repair passes have no feedback role and remain valid empty passes.


Manual prompt-pack instructions point at the canonical run directory rather than
an expiring attempt workspace. Saving the requested response there and resuming
works both for the direct manual runner and the agent's manual fallback. A
successful manual fallback now propagates success. Rewritten diagnostic files
are recognized by inode and nanosecond modification/change metadata plus content,
so identical failures from consecutive attempts remain visible while untouched
older diagnostics are excluded.
