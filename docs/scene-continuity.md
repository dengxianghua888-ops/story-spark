# Opt-in position-scoped continuity (S1)

This is an offline, standard-library evidence projection for the split scene
writer. It does not evaluate literary quality, extract facts, approve prose,
call a model, or modify a story. Synthetic tests establish contract behavior,
not fewer errors in real novels. The implementation is independent; no upstream
novel-generator code or dependencies were copied.

## Scope and compatibility

Without `continuity-ledger.json`, existing stories and multi-scene prompts still
work. They have **no structured continuity guarantee**. Their full beat bible
remains available, so a model may still reveal a future plan too early.

With a ledger, `generate_scene_batches.py` automatically uses one scene per
prompt even if `--batch-size` is larger. Both initial and repair prompts use the
same freshly computed projection. Global chapters/mechanisms are omitted from
this path: only the current scene card is a plan. Cards, title, genre, Style DNA,
and previous failed prose are still authored inputs, not automatically sanitized
spoiler-free documents. Keep future revelations out of those current inputs.
This is input scoping, **not a semantic anti-spoiler guarantee**.

Whole-stage scene-writer prompts (v4, production, production_v6) cannot isolate
future facts when producing multiple scenes together. They reject an opted-in
ledger and direct the user to the split utility. Other phases do not consume this
projection. The split utility retains its production scene-writer contract; it
is not a replacement for every mode's specialized prompt. No general pipeline
approval or resume protocol has been changed.

## Human-maintained ledger

A minimal entry looks like this (hash placeholders must be replaced):

```json
{
  "schema_version": 1,
  "entries": [{
    "id": "key-transfer-2",
    "status": "accepted",
    "reviewed_by": "editor-name",
    "entity_id": "key",
    "field": "holder",
    "value": "阿白",
    "kind": "state",
    "valid_from_scene": "scene-02",
    "source": {
      "scene_id": "scene-02",
      "sha256": "SHA256_OF_SOURCE_DRAFT_BYTES",
      "prefix_sha256": "SHA256_OF_ALL_DRAFTS_THROUGH_SOURCE",
      "quote": "阿青把钥匙交给阿白。"
    }
  }]
}
```

Review the scene and interpretation yourself, then deliberately write an
`accepted` entry. `reviewed_by` is a record of that decision, not authenticated
proof of a human review. This utility never changes `candidate` or `rejected`
entries into accepted entries; those entries do not enter prompts. Machine
rhythm validation and successful generation are not fact acceptance. Never ask
a generation model to author accepted entries as an automatic pipeline step.

To inspect evidence without modifying any files, from the repository root:

```sh
PYTHONPATH=scripts python -c 'from pathlib import Path; from scene_context import source_evidence; print(source_evidence(Path("stories/MY_STORY"), "scene-02"))'
```

Copy the returned source fields and an exact nonempty quote only **after**
reviewing the current prose. Hashes bind bytes, not the truth of an interpretation.
Sources are derived from validated scene IDs inside the same story; user paths
are never accepted. Symlinks escaping the story are rejected.

Scene cards must use matching `scene-N.json` / `scene_id` values. Numeric order
handles `scene-2` before `scene-10`; duplicate numeric aliases are rejected.
An accepted fact is visible only if its source precedes the target scene and
its `valid_from_scene` is at or before the target. Effective position cannot
precede the source. Thus a scene's own events are never assumed already to have
happened at its start. Future facts, quotes and candidate payloads are omitted.

The latest effective accepted value wins for each `(kind, entity_id, field)`;
same-position ambiguity is rejected. Use stable entity IDs. A crowd's false
belief belongs to that crowd's belief field, not to another person's identity.
Express destroyed objects and departed characters as explicit state changes.
For promises, use `kind: "debt"`, a stable field, and a value such as
`{"status":"open","text":"归还信件"}`; a later accepted value with
`status: "resolved"` closes it. Open debts remain mandatory context.

## Revision and acceptance boundaries

Every visible fact checks its source bytes and all preceding draft bytes against
the recorded prefix hash (missing earlier drafts are included as missing markers).
Editing or newly adding an earlier draft invalidates affected evidence even if
that draft has no explicit fact entry. Stale evidence stops that opted-in scene
with an error; it does not silently fall back to an older state and resurrect an
object. Future draft edits do not invalidate an earlier scene's projection.

No drafts or ledger entries are repaired automatically. Re-review the affected
interpretations and refresh evidence deliberately. Old `runs/.../scene-context/`
snapshots remain historical records, never cache inputs. Projections are rebuilt
for initial/repair prompts and include a content hash. Editing a reviewed scene
during a generation run can therefore require review before later scenes run.
A newly generated scene is not accepted merely because the script continues;
without manual entries, it contributes no structured facts or excerpt. For this
pilot, run/review selected scenes rather than assuming an unattended batch is a
complete accepted-fact feedback loop. `--force` from scene 1 is rejected with a
ledger because it would delete the evidence sources.

## Budget and audit

`--context-max-chars` defaults to 16000 Unicode characters of serialized JSON,
including the context hash and audit metadata. It is **not** a tokenizer budget
or a bound on the whole prompt. The contract, current plan, accepted states and
open debts cannot be silently dropped. Only the latest accepted source excerpt
may be tail-trimmed; the budget report records original/kept sizes and reason.
If mandatory content alone cannot fit, increase the budget or review the ledger;
no silent legacy fallback occurs. Prompt files carry the actual evidence for
each attempt, and `runs/<run-id>/scene-context/<scene-id>.json` records the initial
snapshot. The projection code itself is read-only.

## Offline regression

`python -m pytest tests/test_scene_context.py -q` covers a synthetic six-scene
story: key transfer, mistaken suspicion, departure/destruction, identity reveal,
and promise fulfillment. It checks source/prefix revision, rejected candidates,
budget clipping, numeric ordering, path confinement, generation/repair wiring,
and unchanged legacy behavior. Real-author blind evaluation, model obedience,
and improvements to literary quality are **NOT_RUN**.

### Scoped repair boundary

For ledger-enabled generation, automatic prose/card cleanup and question-pressure
reduction are restricted to the current generated scene. Earlier accepted drafts,
their cards, other scenes, and the ledger are not rewritten. Scoped repair does
not assemble `draft.md`; the split runner assembles it only after all batches
pass. Legacy whole-story repair remains unchanged when no scene IDs are supplied.
An integration regression runs the actual split runner with offline model output,
a forced retry, real repair/validation and subsequent scenes, and checks accepted
history byte-for-byte. No paid model is invoked by these tests.
