# Autonomous stream-overhaul implementation and GitHub delivery

Status: execution contract awaiting the user's **go**. No implementation or remote
publication is authorized by the creation of this document alone.

Technical rationale, researched datasets and baseline results:
[STREAM_OVERHAUL_PLAN.md](STREAM_OVERHAUL_PLAN.md).
Spatial invariants: [INTERFACES.md](INTERFACES.md).
Publication restrictions: [PUBLISHING.md](PUBLISHING.md).

## 1. What “go” authorizes and what “finished” means

A subsequent “go” referring to this runbook authorizes the integrator to implement,
test, review, make scoped commits, push a feature branch to **HoganV/TracerTool**,
open/update a PR, monitor/fix CI, merge when repository policy allows, tag the
verified merge commit and publish a **GitHub prerelease** with eligible assets.
It authorizes routine dependency and algorithm decisions within this document,
public reference-data downloads within the resource limits below, disposable
environments/worktrees and normal GitHub-hosted CI. It does not authorize actions
before that “go”.

Default deployment means a tested desktop application delivered through GitHub
source/PR/release workflows—not a web deployment, package-index upload or installer
on the user's machines. Target the next unused 0.3-series version, provisionally
application **0.3.0**, prerelease tag **v0.3.0-rc.1**. Keep package/runtime version
constants identical; test and document the RC-tag-to-application-version mapping.
Recheck remote versions first and never overwrite an existing tag/release.

The autonomous loop performs routine reviews and gate decisions itself. Do not
ask the user to approve every patch, commit, parameter choice or CI retry. Do not
replace missing evidence with guessed results merely to avoid an interruption.

### Completion classes

| Class | Required outcome | What is not claimed |
|---|---|---|
| **A: default-ready source prerelease** | Required implementation packages complete; integrity and paired-reference promotion gates pass; native hosted source CI green; PR merged; exact merge SHA tagged; published source prerelease verified. | Survey/hydrologic validation, independent human productivity and clean interactive Windows acceptance unless separately performed. |
| **B: experimental source prerelease** | Same functional/integrity/integration checks, but insufficient independent labels or unmet statistical quality promotion target. New engine explicitly experimental/opt-in; legacy remains new-draft default. PR/release states limitations and failed/open gates. | Successful default overhaul or acceptance of the original low-tuning goal. This is a partial outcome, not “all changes complete.” |
| **C: blocked delivery** | No safe complete application or authorization/policy unavailable. Preserve reviewed local branch/evidence; remote draft PR only if safe/authorized; give precise blocker and resume pointer. | Merge, release, deployment or passing acceptance. |

Portable assets are an **additional gated deliverable**, not equivalent to source
publication. Aim to produce and verify native Windows/Linux packages. Attach them
only after the distribution requirements are met. Do not attach unreviewed
binaries or call an experimental result fully complete. If full binary delivery
is mandatory, missing distribution/interactive acceptance remains a blocker.

The earlier proposed 90% no-settings acceptance and 50% human-time savings require
actual human/operator evidence. Automated or agent-operated tests are proxies,
not fabricated participants. Keep those claims open if unavailable; use class B
where missing evidence prevents default promotion under the frozen gate policy.

## 2. Hard boundaries and preauthorized decisions

### Always preserve

- Editable XY stays in source projected CRS; explicit export reprojection acts on
  a detached copy. Arrays are row/column, scenes column/row; use cell centers.
- Decode source band scale/offset; preserve source Z precision, units and datum
  uncertainty. Conditioning and display never overwrite the source or exported Z.
- NoData is impassable for routing, refinement, editing and complete final chords.
- Saved coordinates do not move on open. Versioned migration precedes any changed
  interpretation. Legacy retracing uses explicit engine identity/selection.
- Manual, ridge and slope-break behavior does not silently switch engines.
- Preview is separate from accepted geometry; local correction preserves exact
  boundary and outside XYZ; undo/redo and recovery remain usable.
- No runtime accounts, network, telemetry, uploads or automatic updates required.
- Public research data and user reference data are read-only; never publish their
  payloads, identifying screenshots or local manifests accidentally.

### Integrator may decide without asking

- Pure-Python/SciPy/NumPy or permissively licensed maintained implementation,
  cache layout, dataclasses, algorithm internals, generated fixtures and UI labels.
- A deterministic baseline before any learned ranking. Omit ML if it does not
  independently improve the frozen validation criterion; document the omission.
- Conservative handling of absent units, unresolved culverts, genuine sinks and
  competing branches: localized diagnostics or abstention instead of silent cuts.
- Acquisition/source substitutions with equal or stronger provenance; record
  substitutions before comparing results. Do not downgrade blind evaluation data
  quietly to satisfy a target.
- Minimal prerequisite bugs in touched workflows, with failing tests; no broad
  unrelated UI redesign or drive-by refactors.
- Local bot attribution if no configured commit identity: `TracerTool Agent` with
  `tracertool-agent@example.invalid`, repository-local only, and AI disclosure.
  If verified-commit policy disallows it, use an existing authorized identity or
  stop; never impersonate a human or disable signing requirements.

### Not authorized

Force/mirror/all-branch pushes; rewriting published/private history; deleting
existing releases; bypassing rulesets/reviews/signing; changing visibility,
repository permissions or secret settings; new paid infrastructure/GPU services;
accepting credentials in chat; changing another Hermes profile; copying GPL-only
research implementations into MIT application code without a separate decision;
claiming tests/field validation not performed. Do not suppress safety approvals.

## 3. Verified starting state and launch readiness

These are observations from planning, not assumptions to reuse without checking:

| Item | Observed state | Launch action |
|---|---|---|
| Original development tree | `main`, `5e411efe91a63589b643b99f8d19e22b41f60cc9`; no remote; full-history audit **fails** on historical private reference metadata | Never add a publishing remote or push from it. Preserve untouched as a private baseline. |
| Sanitized publishing tree | `dist/github/TracerTool`, clean; origin `https://github.com/HoganV/TracerTool.git`; main `8cababee0d233b97a2d054cdbc7ce52be5ba77e0` | Re-fetch and confirm ancestry; implement in this lineage or a fresh full clone of this remote. |
| Remote main | Matched sanitized main in read-only `git ls-remote` | Re-read before branch and merge. Do not overwrite intervening work. |
| Sanitized audit | `python scripts/check_publication.py --root dist/github/TracerTool --history` passed | Repeat before changes, then on every committed publishing candidate. |
| Source suite | Prior investigation: 457 passed in 46.94 s in original `.venv` | Repeat in execution environment and then sanitized integration tree. |
| GitHub tooling | `gh` absent from current PATH; GH_TOKEN/GITHUB_TOKEN not set | Install user-local official CLI if needed; verify an authorized existing account. Absence of env variables is not proof no other credentials exist. |
| Commit identity | Not configured in inspected trees | Use authorized local identity or disclosed bot default; never change global config. |
| Desktop | DISPLAY/WAYLAND_DISPLAY absent; Xephyr and ogrinfo available | Discover accessible desktop safely. Use isolated Xvfb/Xephyr if available; label virtual-display evidence accurately. |

**Before promising uninterrupted publication, verify authentication now or at
launch.** User can run `gh auth login --hostname github.com --git-protocol https
--web` in their own terminal after installing the official CLI; credentials never
need to be pasted into chat. Confirm appropriate repository/workflow permissions.
The agent must not scrape credential files or print token-bearing configuration.
If no usable auth is available on “go”, complete independent local work, but
remote delivery is genuinely blocked until the user authorizes an account.

Read-only GitHub launch checks, after CLI is available:

- `gh auth status` (capture/redact token-bearing output; never print token values).
- `gh repo view HoganV/TracerTool --json nameWithOwner,defaultBranchRef,viewerPermission`.
- Inspect open PRs, latest releases/tags, branch rulesets/protection and workflows.
- Verify branch write, PR, merge, workflow-dispatch and release permissions through
  available account/policy metadata; unknown permissions are not assumed granted.
- If required reviewer/environment approval is human-only, identify it before
  launching long work. Never disable it to satisfy “no interruption”.

Do not create a remote test branch just for planning. No remote changes are
performed by this runbook's preparation.

## 4. Durable execution state and recovery

Create local, ignored `artifacts/stream-overhaul/run/` on execution. Public-safe
contracts, tests, scripts and summary reports belong in source; raw data, logs,
internal reviews, local paths and operational checkpoints do not.

Persist at every phase boundary and before external writes:

- `state.json`: run ID, plan revision, execution root, public base SHA, feature
  branch, current task/status, exact tested SHA, validation-set identity, holdout
  consumption, PR/run/release handles, external operation intent and last result.
- `tasks.json`: task IDs, dependencies, file ownership, worker identity, states,
  attempt count, expected checks and evidence pointers.
- `decisions.md`: option/decision/evidence/why; record contract/dependency changes.
- `evidence.json`: command, cwd, environment category, exit code, report path,
  source SHA, input identities and honest result classification.
- `handoff.md`: completed work, active worktree branches, next runnable command,
  known blockers and exact external handles. Never include secrets.

Task states: `ready → running → implemented → reviewed → integrated → verified`;
also `blocked`, `rework`, `not_selected`. A child cannot declare a task closed;
the integrator verifies evidence and transitions it. Completed-plan checkboxes
never substitute for exercising the application.

Use process notifications for bounded builds/CI waits, not blind sleeps. Keep
foreground loops bounded. No detached agent is assumed to survive conversation
termination. Durable files make resume safe, but do not themselves schedule a
continuation. If the session stops, recover by reading state, verifying git and
remote targets, then resuming the first unverified task—not repeating writes.
There is no promise that an unattended process will survive `/stop`, auth expiry,
host failure or a platform turn limit.

External writes follow **intent → act → read back exact target → record**.
Before repeating after a timeout, discover whether the branch/PR/tag/release
already exists and matches the intended SHA. Never create duplicates blindly.

## 5. Agent topology and integration discipline

The parent integrator owns scope, public lineage, contracts, cross-module changes,
version/configuration, release decisions and all GitHub writes. Workers never
push, merge, tag, publish, change shared dependencies or close parent tasks.

Prefer 3–4 active implementers plus an independent reviewer. Add more only for
truly disjoint work. New paths below are proposals, to be ratified before code.

| Lane | Exclusive implementation ownership | Responsibilities |
|---|---|---|
| Integrator | `docs/INTERFACES.md`, `pyproject.toml`, version constants, top-level trace dispatch, CI/release config and integration seams | Freeze contracts, serialize shared edits, run integration, remote delivery. |
| Evaluation/data | New `evaluation/`, evaluation/download/report scripts and dedicated tests | Provenance, manifests, metrics, split freezing, baseline, reproducible reports. No algorithm tuning against blind acceptance. |
| Raster/analysis | New source/grid/cache modules, `terrain.py`, dedicated grid/cache tests | Native window reads, transforms, immutable calibration, budgets, source identity and mask semantics. |
| Hydrology | New flow/conditioning/evidence modules and their tests | Flats, sinks, accumulation, multiscale terrain evidence, boundary uncertainty. Coordinate API through integrator. |
| Reach solver | New candidate-graph/stream-solver modules, stream algorithm tests | Joint soft guides, connectivity, alternatives, refinement and structured uncertainty. Starts after analysis contract. |
| Persistence/editing | `project.py`, `recovery.py`, `editing.py`, migration/topology/geometry-QA modules and corresponding tests | Engine provenance, structured diagnostics, source references, correction invariants and junction semantics. |
| UI | `app.py`, `canvas.py`, `desktop_actions.py`, `preferences.py`, assigned UI tests | Auto workflow, branch alternatives, reference/diagnostic layers, cancellable jobs, review/edit/save integration. |
| Release/docs | Build/verification scripts and docs except shared contracts/version/changelog until assigned | Package provenance, dependency inventory, frozen acceptance, public-safe release evidence. |
| Independent reviewer | Read-only diff, tests and evidence; no overlapping implementation | Spec compliance then code/security/data-integrity review, failure reproduction. |

Activate lanes in waves rather than concurrently modifying every module. Assign
specific tests once, not by vague “all integration tests” overlapping ownership.
File ownership can transfer only at a recorded integration barrier.

### Worker ticket contract

Each dispatch includes: task ID; exact worktree/base SHA; owned files; frozen
interface version; prerequisites; user-visible behavior/non-goals; required RED
and GREEN commands; invariants; budgets; expected output artifacts; and prohibition
on remote writes. Workers load relevant repository and skills context themselves.

Return: changed files, actual failing/passing commands and exit codes, produced
commit/diff, evidence paths, remaining risks, and explicit actual completion.
Reported success is not accepted without parent read-back/reproduction.

Use separate worktrees/branches based on **sanitized public history**. Set up a
shared read-only corpus, separate cache/output directories, and avoid concurrent
writes to one `.venv` or build directory. Integrator cherry-picks/rebases only
reviewed public descendants. Never cherry-pick original private-development
commits or copy their `.git` directory. Never mix a teammate's unfinished files
into a commit. Do not use `git add -A` for publication; stage explicit allowlists.

## 6. Implementation waves and acceptance tickets

### Wave 0 — safe launch and fixed scope

**T00: public execution root and baseline.** Recheck section 3, create feature
branch `feat/stream-auto-overhaul` or a unique suffix, clean full-history audit,
reproducible Python environment, exact suite/smoke/dependency baseline and state.
Copy only reviewed public-safe planning docs into execution root, using relative
paths. Preserve new work already present on remote; record differences.

**T01: contracts and migration policy.** Specify source/analysis/display grids,
analysis request/result, physical distances, source-unit QA, diagnostics codes,
cache identity/cancel, engine IDs, references and junction operations in the
contract. Define valid result outcomes: candidate/ambiguous/unresolved/cancelled,
not “always a line”. Version schema explicitly (proposed schema 2), with schema-1
fixtures and old coordinates unchanged. Decide parameter semantics before workers
consume them. Contract tests first; no placeholder API that silently returns a
legacy line as a new engine result.

### Wave 1 — benchmark plus foundations, in parallel

**T02: paired-data harness and baseline.** Convert existing Minnesota pilot into
replayable fetch/verify/evaluate tooling; acquire acquisition-matched and
independent-source examples with reviewed licenses. Preserve raw requests and
full returned vector extents. Pin raw/conditioned status, dates, units, target,
uncertainty, source fingerprints, split and guide budget. Measure exact continuous
segment distances or quantitatively bounded sampling error, uniform arc-length
sampling, bidirectional metrics, reach-level distributions, failures and timing.
CLI must continue after one case fails and produce machine-readable results.

**T03: source/grid/cache foundation.** Native calibrated window reads, separate
display transform, rectangular pixels, explicit projected CRS requirements,
source-level complete-segment mask validation and bounded caches. Unit unknowns
stay unknown. Identity changes invalidate caches. Source-scale/offset applied
exactly once. Test file replacement mid-job and cancellation during cache commit.

**T04: persistence/provenance foundation.** Schema migration, immutable engine
identity, effective Auto settings, structured located diagnostics, draft intent,
reference fingerprints and optional junction IDs. Geometry edits invalidate only
stale engine evidence and recompute common geometry/profile QA centrally; do not
strip every diagnostic or preserve stale English warning text. Read old projects
without retracing and reject unknown future schema safely. Invalid geometry
(including adjacent duplicate XY) has explicit rejection/repair semantics.

**T05: CI safety skeleton.** Add tests for new tooling/manifest schemas and public
privacy checks. Plan reproducible hosted corpus evaluation with only licensed
public AOIs and sanitized reports; network-dependent tests remain separate from
fast deterministic tests. CI cannot silently skip required quality gates because
an input file was missing. Build distribution remains off until cleared.

**Barrier 1:** T01 interfaces stable; T02 produces real baseline; T03/T04 focused
and cross-boundary tests pass. Integrate and run full suite before more lanes.

### Wave 2 — one working native-resolution stream slice

**T06: drainage analysis.** Implement transparent raw/flat-resolved D8 baseline,
flow accumulation in physical area units, pit/spill and boundary uncertainty;
then candidate multiscale directional valley evidence. Expose upstream-domain
truncation; an arbitrary small window cannot claim complete contributing area.
Use connected-domain preparation, bounded expansion and explicit uncertainty.

**T07: analysis-only conditioning.** Numerical flat policy, candidate fill/breach
limits and changed-area/depth/length diagnostics. Preserve real closed-basin
uncertainty and NoData barriers. No automatic material cut without user-facing
policy/consent. Unknown vertical units disable physical-depth assumptions.
Synthetic cases distinguish harmless quantization from genuine sinks/roads.

**T08: reach graph and solver.** Create connected candidates and junctions; seed
snapping to several plausible reaches; optimize all soft guides jointly with
hard connections fixed; choose start/destination path using drainage, local
orientation and feature evidence. Expand analysis/search automatically within
limits, not just the old chord corridor. Return alternatives or abstain where
appropriate. Guard wrong tributary shortcuts and inappropriate basin crossings.

**T09: geometry and QA.** Refine within evidence envelope, physically meaningful
spacing/tolerance independent of search radius, full native-source NoData
supercover and exact hard-node preservation. Sample source Z; compute raw-profile
QA separately from conditioned-flow diagnostics. Tie numerical tolerances to
actual units/noise; no universal Z threshold pretending feet equal metres.

**Barrier 2:** CLI vertical slice must trace a native-resolution meander outside
the old default corridor, identify ambiguity on flat ground, handle a confluence,
stop at a genuine unresolved sink and preserve source-Z/NoData/fixed-node
invariants. Compare to real development reaches before UI work; do not declare
success from generated valleys alone.

### Wave 3 — usable Auto editor and durable connections

**T10: jobs and responsiveness.** Snapshot immutable requests, phase progress,
cooperative bounded cancellation or isolated killable work for compiled stages,
latest-generation result suppression and transactional cache installation.
Allow pan/zoom and inspection while analysis runs; cancel/close safely, without
late mutations to another terrain/project. No expensive main-thread preparation.

**T11: Auto UI and review layers.** Stream defaults to Auto only after promotion;
before that visibly experimental Auto option. Start/end guided reach, branch
alternative selection, soft/fixed guide distinction, located uncertainty,
source/analysis resolution disclosure, separate reference/prediction/accepted
layers, advanced numeric controls collapsed. References never enter accepted
feature exports. Include conservative single-seed downstream with explicit edge,
flat, sink and uncertainty termination if it meets the same contracts.

**T12: editing and connection integrity.** Accept/correct/retrace/undo/redo,
protected exact endpoints, unchanged outside XYZ, source sampling, diagnostics
lifecycle and draft/recovery round trip. Persistent shared junction identities
must either propagate safe edits transactionally across incident reaches or
reject an unsafe edit with an explanation; never silently leave a gap. Define
split/join/reverse/delete behavior and undo the network change as one operation.
No promise of arbitrary network extraction/distributary editing in this release.

**T13: visible and end-to-end tests.** Open real public DEM, prepare, click rough
seeds, inspect alternatives/diagnostics, accept, correct, cancel, edit junction,
save/reopen, recover, export/read-back and compare source Z/CRS. Run automated Qt
offscreen checks plus real Qt mouse/keyboard exercise in an available isolated
native or virtual desktop. Capture generated/public-only evidence with provenance;
virtual display and agent review are not independent human usability testing.

**Barrier 3:** integrated desktop workflow works without settings hunting on the
frozen development cases; full regression suite and independent export reader
pass. Fix blocker defects, not unrelated visual redesign.

### Wave 4 — qualify rather than endlessly tune

**T14: candidate comparison and calibration.** Select deterministic candidates
using only development data; use validation for bounded model/config selection.
Compare current defaults, equal-budget current tuned-global baseline,
flat-resolved/conditioned D8 and new multiscale graph method. Trial D-infinity/MFD
or learned ranking only if a specific failure hypothesis warrants it and
Windows/CPU/offline/license requirements are feasible. Record selected and
rejected variants. Deep learning, GPUs and runtime online services are not
required. Non-selected alternatives are legitimately not implemented.

**T15: sealed acceptance and promotion decision.** Freeze candidate SHA/config,
scoring code, case list and thresholds; independent evaluator runs geographically
held-out cases. Once inspected for tuning, those cases become validation; do not
keep calling them blind holdouts. No silent exclusion of failures. Apply section 7
and record class A/B/C. Do not redefine goals after seeing failure.

### Wave 5 — review, GitHub integration and release

**T16: independent review and documentation.** Fresh context reviews spec and
full public diff, then source/data-integrity/security. Fix findings with regression
tests. Update guide, research decisions, changelog, validation evidence, AI
disclosure, release notes and limitations. Normalize paths and scan every planned
tracked file before first commit; untracked docs are not covered by tracked-file
audit until explicitly inspected/staged. No private screenshots/corpus included.

**T17: PR CI and merge.** Execute section 9. Required matrix, publication and
quality checks must be green for exact candidate; no unresolved critical review
issues. Review remote changes before merge, rerun on changed base and comply with
required reviewers. Read back merged state/SHA and requalify that final SHA.

**T18: reproducible source and portable builds.** Build exact merged source
archive/checksum and native Windows/Linux packages. Frozen smoke must exercise
new Auto engine, cache/cancel-safe path, migration/save/export and resources—not
only legacy trace smoke. Extract in fresh Unicode/spaced paths, clear development
resource variables, verify source/engine IDs and archive contents. Inventory actual
bundled native dependencies, not just installed pip distributions. Run binaries
without source checkout or developer Python/GDAL/PROJ discovery. No `--skip-smoke`.

**T19: publish and verify release.** Tag exact verified merge SHA, create draft
prerelease, attach only cleared assets, read back draft tag/asset manifests,
publish prerelease, download public assets and verify SHA256/CRC/source identity.
Record GitHub URL, target SHA, PR, CI runs, checksums, open gates and actual
completion class. Never report success just from an upload command exit code.

## 7. Dataset, promotion and resource policy

### Data floor and separation

Aim for the earlier 12-catchment/four-setting corpus with approximately 20 reviewed
reaches each. Before tuning, establish a minimum publication-quality floor of
**six independent catchments across three contrasting settings**, at least two
acquisition regions, and at least 60 evaluable reaches total, with at least two
catchments and 20 reaches reserved for acceptance. Include an independent-source
label stratum; label limitations remain explicit. This smaller floor is not
statistical proof of universal accuracy and does not waive human acceptance.
If provenance/coverage cannot meet this floor, report partial evidence and class B,
not a quietly weakened default promotion.

Freeze catchment splits with geographic buffers and acquisition-lineage checks;
overlapping tiles and upstream-connected areas cannot straddle splits unnoticed.
Reference shapes must never enter candidate generation, analysis surfaces or
solver caches. Declared reference-derived endpoints are identical across methods;
extra reference-derived guides are not hidden assistance. Freeze label exclusions
and resolvable/ambiguous classifications before seeing candidate results.

Use synthetic fixtures for invariants; keep real-data inputs outside Git. A
manifest may contain public source URLs/IDs, allowed roles, hashes and attribution,
never user/private paths. One agent curates provenance, another evaluates label
suitability without seeing candidate results where feasible. Agent adjudication
is labeled as such. Unclear labels are unknown, not adversarially convenient
negatives. Score culverts/waterbodies/sinks separately rather than exclude them
from all summaries. Pin guide placement before comparing engines.

### Mandatory integrity gates (all delivery classes)

Zero source modifications or NoData crossings; exact fixed-node/boundary retention;
source Z precision and calibration retained; legacy coordinates unchanged; no
wrong-CRS application; invalid/moved-source behavior actionable; atomic ordinary
failure semantics retained; no executable deserialization; no canceled/stale
request can install a preview/cache; same request/version deterministic; required
suite/smoke/source audit passes; reference layers never exported as accepted work.

### Algorithm and experience promotion

Freeze exact metrics before acceptance: target at least 30% lower paired
reach-level p95 bidirectional localization error versus old defaults, no material
wrong-branch/connectivity regression, and disclose per-setting/worst-case error
and abstention coverage. Missing/failed paths stay in denominators with explicit
failure accounting; finite-only average cannot win by dropping hard cases.

Target at least 90% no-numeric-tuning acceptance on reviewed resolvable reaches
and median at most one extra intent guide. Acceptance criteria include branch
correctness and documented source uncertainty, not only visual smoothness. Report
agent-guided proxy and independent operator results separately. The proposed
50% reduction in human editing time is an unclosed research gate until actually
measured. Do not advertise it based on an automated script.

Target warm short-reach preview p95 <1 s and cancel response <250 ms, with fixed
hardware/domain and peak memory. Record cold preparation separately. Missing the
performance target blocks a claim of that target and may require class B; source
integrity and UI responsiveness are never traded away for speed.

### Resource defaults, adjustable downward without asking

Initial corpus download budget 10 GiB; total local run data/cache/build budget
40 GiB and preserve at least 20 GiB free disk. Stream/range/AOI requests, avoid
national archives. Retries use timeouts/backoff and validate content/format, not
HTTP status alone. Reject unsafe archive paths, suspicious executables and
unchecked model payloads. No paid service or large cloud/GPU job.

Limit concurrent heavy local workers based on actual RAM/CPU; analysis target at
most min(4 GiB, one quarter detected RAM) per active job, with explicit estimate
and disk-backed/tiled alternative. Do not allocate full giant raster stacks just
because the TIFF opens. Out-of-budget or upstream-incomplete analysis returns a
diagnostic, not a hidden downsample presented as full resolution.

At most two materially different repair/hypothesis cycles after a failed candidate
evaluation; then independent architecture review and explicit class B/blocker
rather than endless tuning. At most two independent-review fix/reverify cycles;
about three attempts for repeated same-file lint/type failure or CI root cause,
then checkpoint and escalate the real blocker. A transient network retry is not
license to loop indefinitely. This honors verification limits rather than
promising impossible uninterrupted repair.

## 8. Per-ticket development and verification loop

1. Read definitions and call sites; verify dependencies and current contract.
2. Add one red-capable behavioral test; run and retain expected failure evidence.
3. Implement the smallest vertical slice through real code; no production stubs.
4. Run focused tests, exercise CLI/UI path, then relevant boundary round trips.
5. Refactor only while green; preserve generated/public-fixture determinism.
6. Independent reviewer checks spec compliance and then logic/security/integrity.
7. Parent checks actual diff and evidence, reruns meaningful tests, stages explicit
   files and creates a scoped commit in sanitized lineage.
8. On integration barrier, run full suite and smoke, then audit committed snapshot.

Known repository commands (use execution root's installed interpreter):

- `QT_QPA_PLATFORM=offscreen python -m pytest -q`
- `QT_QPA_PLATFORM=offscreen python -m tracertool --smoke-test`
- `python -m pip check`
- `git diff --check`
- `python scripts/check_publication.py --history` (committed, clean public tree)
- `python scripts/build_source.py --commit EXACT_SHA`
- `python scripts/build_portable.py`
- `python scripts/verify_portable.py EXACT_ARCHIVE`

New evaluation/fetch/report tools and flags are to be implemented and tested in
T02/T05; they do not exist merely because this document names them. Include
`--help`, generated-case smoke, real pilot replay, corrupt/missing inputs,
reproducible JSON output and threshold-failure exit status in their acceptance.
Use `ogrinfo` as an independent export reader where available; same-library
read-back alone does not establish target-GIS interoperability.

## 9. GitHub delivery transaction

### 9.1 Source PR

- Publish solely from sanitized descendants. No original-workspace commit SHAs
  in public branch ancestry, and no local checkout paths in source or reports.
- Inspect existing PRs for duplicates. Push only the explicit feature branch;
  read back remote SHA. Create/update one PR against the observed default branch,
  with scope, class, exact checks/evidence and known limitations.
- Existing `.github/workflows/ci.yml` has publication audit and Linux
  3.11/3.12, Windows 3.13/3.14.7 source test/smoke matrix. Preserve supported
  interpreters unless evidence justifies a separately documented compatibility
  change. Extend Auto smoke and deterministic integration coverage.
- Add a bounded public-corpus quality job or a verifiable evaluation attestation
  keyed to candidate SHA/config/data/scoring identities. Independent promotion
  evaluator consumes the sealed acceptance set. Do not upload raw vectors/TIFFs.
- Public reports use an explicit allowlist; remove local paths/private feature
  identities, source inputs and machine credentials. Metadata can be sensitive too.
- Use least-privilege read permissions for tests, pinned official Actions,
  no credential persistence, and no privileged fork-code checkout. Release writes
  get narrowly scoped permissions only in the trusted publication job.
- Use `gh pr checks` and exact run logs for actual results. Fix causes and push
  scoped commits; never disable failing tests/audits or mark required skipped
  jobs as equivalent to successful execution.
- Merge only the expected PR head after all required checks/reviews; use expected
  head-SHA protection supported by the installed CLI/API. If branch protection
  requires someone else, it is a blocker—not permission to bypass it.
- Read back `state`, `mergedAt`, merge SHA and default-branch ref. Re-run relevant
  checks/builds on the **merge SHA**; PR-head success may not apply to the merged tree.

### 9.2 Portable workflow and provenance improvements

Current portable jobs run only on manual dispatch with `build_portable=true`;
`upload_portable=false` by default and no Release is created. Preserve that
separation until distribution clearance exists.

Reject dispatch combinations with `upload_portable=true` and
`build_portable=false` instead of silently skipping the requested deliverable.
Bind distribution clearance to the exact commit and component inventory; a
dispatch boolean is not clearance. Use an existing protected environment or a
reviewed machine-verifiable clearance record. Creating/changing repository
environments or rulesets is not authorized; a required human approval remains
a genuine blocker. If merge queues are already enabled, add `merge_group`
coverage so required checks run; do not enable a queue merely for this run.

Implement a trusted, exact-ref native build path with:

- tests on the actual requested commit, explicit application/engine/schema IDs,
  final git commit/tree identity and source-hash manifest in build-info;
- frozen Auto-path smoke plus native extracted ZIP verification, source identity
  equality and archive inventory/size checks;
- packaged dependency/native-binary inventory, complete notices and required
  source/relinking delivery materials, no private paths/data;
- per-platform checksums and a release-manifest relating commit/run/assets;
- public artifact upload only after the same distribution clearance required for
  Release assets—Actions upload is distribution too.

For release builds, record a stable OS/Python baseline and reviewed platform
dependency locks with hash-verified acquisition, separately from broad source
compatibility CI. Cover build specs, hooks, config and copied docs in provenance,
not only `src/**/*.py`. Keep dependency installation and executable testing out
of any privileged publication job; it consumes explicitly verified assets only.

Harden archive verification with member/expanded-size bounds, duplicate-name and
symlink policies, complete payload allowlists and enforced build provenance.
An adjacent checksum detects corruption, not authenticity: the verifier executes
the packaged binary, so accept only trusted exact-run artifacts and run them in
disposable target-platform environments without credentials or private data.

Native runner tests establish actual Windows execution, not an interactive clean
Windows or workplace-machine acceptance. Preserve this distinction in release
notes. If license review or required human/GIS acceptance remains open, run
build verification without binary upload and publish source only. Do not weaken
existing docs/PUBLISHING.md to make a binary gate disappear.

### 9.3 Draft, publish, read-back

1. Select unused RC tag; verify source/merge/build identities and completion class.
2. Create tag at exact merge SHA and read back resolved target.
3. Build source ZIP from that sanitized commit; verify inclusion list and checksum.
4. Create **draft + prerelease**, attach only eligible assets with explicit
   target/tag/notes. No automatic stable/latest promotion.
5. Read draft back: repository, tag target, prerelease state, assets, sizes and
   manifest. Download and hash assets; compare expected inventory, not just count.
6. Publish prerelease, then read public release and download links back again.
   Verify `isDraft=false`, `isPrerelease=true`, correct tag/commit, asset hashes.
7. Finish with public URL, exact SHA, PR/CI URLs, tested platform categories,
   default/experimental status, eligible asset list and remaining acceptance work.

No source/binary release success claim is made until these reads succeed.
If publishing fails, preserve the draft and record its handle; resume idempotently.

## 10. Failure and rollback policy

| Failure | Autonomous response | When intervention is unavoidable |
|---|---|---|
| Corpus URL broken/403 | Official alternate source/service, bounded retry, pin replacement provenance | No sufficient licensed coverage for promised promotion; class B or blocker, never invented data |
| New solver underperforms | Falsifiable diagnostic, bounded alternative, independent review, keep legacy default | Cannot meet core functional/integrity floor; no merge/release as completed overhaul |
| Long job or OOM | Cancel, reduce parallelism, bounded domain/disk cache, disclose boundary uncertainty | Required input cannot be analyzed honestly within available resources |
| Source/CRS/unit mismatch | Reject or request explicit in-app metadata during future use; tests cover it | Actual missing required information cannot be retrieved; never silently infer datum |
| Auth expired/permission missing | Continue independent local work and checkpoint remote operation | Account authorization, protected reviewer approval or workflow environment approval needed |
| CI bug | Read exact failed logs, regression test, scoped fix, rerun within limits | Repeated unresolvable root cause; don't bypass guards |
| Binary clearance unavailable | Verify builds privately, source-only prerelease with explicit limits | User requires public binaries with gates that cannot be completed autonomously |
| Private data found before push | Remove from candidate branch by rebuilding from clean sanitized public base; audit every reachable commit | Already pushed leak: stop further publication, notify user; removal/history/security response needs separate handling |
| Remote main moved | Fetch, review diff, integrate in public lineage, rerun checks | Conflict with unrelated unfinished work or policy requiring user decision |
| Release defect found | Stop publication if draft; if public, mark notes affected and prepare reviewed revert/hotfix | Destructive deletion, rewriting published tags or unpublishing assets not preauthorized |

Rollback uses ordinary reviewed **revert commits**, a new patch/RC tag and fresh
checks. Do not reset published main or retarget an existing tag. Keep legacy engine
available for existing projects, but never silently switch after an Auto failure;
show the explicit fallback and its changed semantics.

## 11. Exact launch and final reporting contract

On “go”, load this runbook, technical plan and current repository contracts,
revalidate readiness, create durable state, then execute the dependency waves.
Do not stop at a scaffold, a plan, a passing subset or a PR that nobody checked.
Continue through independent review, hosted CI, safe merge and verified prerelease
as far as real permissions/evidence permit. Report progress at major milestones
without requiring user responses for routine decisions.

Final report is short and factual: **completion class**, implemented behavior,
version/tag/SHA, release/PR/CI URLs, measured quality and platform results, assets
actually published, and remaining blockers/gates. Any unfinished mandatory ticket
is named. A class B or C outcome is not described as the full requested overhaul.

### Ready-to-run checklist

- [ ] User has said “go” referring to this contract.
- [ ] Verified GitHub authorization/permissions and branch-policy readiness.
- [ ] Sanitized root/base and original private-history prohibition confirmed.
- [ ] Run state/tickets initialized; ownership/contracts recorded before dispatch.
- [ ] Baseline, data split/metrics and promotion criteria frozen.
- [ ] Every mandatory ticket independently reviewed, integrated and verified.
- [ ] Source/privacy/dependency review and exact-SHA hosted CI green.
- [ ] Merge target read back; final-source/frozen checks tied to merge SHA.
- [ ] Draft assets eligible; public prerelease read back and downloads verified.
- [ ] Honest final completion class, limitations and resume/rollback evidence.

## 12. Independent planning review incorporated

Two read-only reviews checked scientific acceptance and release engineering.
Their recommendations are reflected in the outcome classes, holdout isolation,
reference-input prohibition, immutable source/merge identities, distribution
clearance, archive authenticity boundaries and bounded failure handling above.
No review result substitutes for implementation tests or authorizes publication
before the user's go. Authentication and protected-branch readiness are still
unverified, so interruption-free remote delivery is conditional on resolving
those prerequisites; local implementation can proceed independently.
