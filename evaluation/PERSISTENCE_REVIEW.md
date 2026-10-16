# Independent persistence review

Read-only review of project/editing/recovery changes; no files in that lane modified.
Focused persistence/editing/recovery and evaluation tests initially passed (217 tests),
but the following additional real synthetic probes reproduced gaps.

## High: protected junction survives one edit only

`editing._finish` removes `anchors` and `fixed_anchor_indices` for geometry edits.
`validate_shared_junction_edit` discovers protection only from those fields.

Reproduction using the generated fixture in `tests/test_editing.py`:
1. A has four vertices `(10,10),(20,10),(30,10),(40,10)` in grid coordinates;
   B starts at A's second vertex and continues to `(20,20)`.
2. Set A's `fixed_anchor_indices=[1]`; B has no fixed anchor.
3. Move only A's last vertex to `(40,12)`; preflight correctly permits the edit.
4. The result has no fixed-anchor metadata.
5. Delete its second vertex, then run the guard against B. The guard permits it,
   although the formerly protected shared junction is disconnected.

Actual probe output: `second edit disconnected protected shared junction after
first harmless edit; fixed metadata None`.

Requested fix: retain persistent junction protection independently of disposable
solver guides (or conservatively retain protected native XY). Exercise repeated
edit, split, correction and save/load sequences, not only one-shot preflight.

## Medium: malformed engine evidence passes project validation

A valid generated feature with `engine_evidence=[]` saves and loads successfully.
`move_vertex` then raises `TypeError: list indices must be integers or slices,
not str` when `_finish` writes `engine_evidence['stale']`.

Requested fix: validate the introduced evidence structure at load/save and edit
boundaries; malformed input should raise actionable ValueError before mutation.
Also check identity/version consistency and non-object diagnostics where consumed.

## Checks that passed

Existing round-trip/migration/unknown-engine refusal, correction provenance,
stale-evidence retention, shared-junction one-shot rejection and recovery tests
all passed in the reviewed snapshot. These do not establish full network editing.

## Final recheck: both findings fixed and verified

The separate persistence lane added persistent native-XY protection and shared
engine-metadata validation. This reviewer reran both original synthetic probes:

- After the harmless first move, deleting the shared protected vertex now raises
  `ValueError: This edit would remove a protected junction. Keep its exact native XY vertex.`
- Saving `engine_evidence=[]` now raises
  `ValueError: Line engine_evidence must be an object.`

The final combined evaluation/core/grid/project/editing/recovery run passed
**267 tests**. Intermediate split and metadata-loss regression failures observed
while the lane was being edited are no longer present in that final run.

The original findings above are retained as the review trail, not open defects.
No persistence implementation files were modified by this reviewer. This does
not claim general network topology support or independent human acceptance.
