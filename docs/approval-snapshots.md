# Reviewed blueprint snapshots and safe restart

The pipeline now treats a human approval as consent to a specific content snapshot,
not as an unrestricted `approved` flag. This is local integrity metadata, not a
cryptographic signature or a defense against someone who can edit both the story
and its approval records.

## Review and continue

Run with a stable `--run-id`. Without `--no-human-gates` (or the synthetic `mock`
runner), the pipeline pauses after the actual blueprint/beat stage: V4 phase 2,
production/ultra-short phase 4, production V6 phase 5.

```sh
python scripts/storyforge.py run --story stories/example --run-id revision1 --runner openclaw
python scripts/storyforge.py approve-gate --story stories/example --run-id revision1 --gate phase2_blueprint_review
python scripts/storyforge.py run --story stories/example --run-id revision1 --runner openclaw --from-phase 3 --resume
```

The example is V4; use phase 5 or 6 to continue production or production V6.
The historical gate CLI name is retained across modes. OpenClaw remains selectable
and the provider priority is unchanged.

Approval records bind the current candidate files, transitive upstream inputs,
source policy, prompt/bundle/template content, local validator and runner code,
workspace configuration, model/runner selection and generation-related
`STORYFORGE_*` environment settings. Environment values are hashed, not stored.
Run logs, timestamps, heartbeat interval and `story.yaml`'s `automation` section
are excluded. That automation section is also excluded from rendered model inputs.

Before each downstream stage (and each split-scene generation attempt), these
inputs are recomputed. A mismatch exits with a human-gate requirement instead of
silently accepting the current files. Re-run `approve-gate` after inspecting the
changed candidate. Use `--runner`, `--model`, `--skip-rubric`/`--no-skip-rubric`, or
`--rubric-threshold` on approval when reviewing changed execution settings; use
those same settings when continuing. Review uses the current environment.

Old stories containing only `approved` do not acquire synthetic historical
approval. Run through the blueprint stage to create a pending review for a known
run, then explicitly approve it. Missing candidate files or failed blueprint
validation prevent approval. Approval metadata is not copied from runner output.

The binding covers observable repository configuration and launcher arguments.
It cannot attest hidden settings or mutable model aliases inside external
providers. Pin a model version where the provider supports it. This change does
not claim that model output is factual or that a reviewer actually read it.

## Resume

`--resume` applies to completed stages in the specified run. It skips a stage
only when its actual input/prompt/configuration fingerprint still matches, every
recorded output matches, and the current phase validator succeeds. Missing or
legacy records, changed dependencies, changed outputs and invalid output cause
regeneration. It never restores missing artifacts from an old run. If a phase
rewrites one of its own inputs, it may conservatively regenerate on restart.

A manually supplied `phaseN.model.out` must answer a previously generated prompt
with matching inputs. First run the manual-prompt-pack runner, then save the
response at its instructed path and rerun with the same run ID. Unmatched old
responses are retained as `phaseN.model.out.stale-*` and are not accepted on a
later retry. Pending manual responses keep their original prompt, rather than
appending failure diagnostics for simply waiting on a response.

## Split-scene generation

This separate entry point also requires approval unless explicitly bypassed:

```sh
python scripts/storyforge.py approve-gate --story stories/example --run-id revision1 --gate phase2_blueprint_review --runner codex --model gpt-5.4
python scripts/generate_scene_batches.py --story stories/example --approval-run-id revision1 --run-id scenes1 --model gpt-5.4
```

Match the approved reasoning effort with `STORYFORGE_CODEX_REASONING_EFFORT` when
approving and `--effort` when generating. `--no-human-gates` is an explicit bypass
for intentional unattended/synthetic workflows, not an approval record.
