# Experimental Auto stream contract (0.3)

Implementation ownership: core lane owns new `stream_auto.py`, `analysis_grid.py`
and dedicated tests. Persistence lane owns project/editing/recovery and tests.
UI lane owns app/canvas/desktop_actions/preferences and dedicated tests. Evaluation
lane owns new evaluation module/scripts/tests. Integrator owns existing tracing,
terrain integration seams, shared contracts/version/config/CI and final delivery.
Do not alter another lane's files. All changes descend from sanitized public main.

## Stable boundary for this implementation

`stream_auto.trace_auto(terrain, anchors, params=None, cancel=None,
fixed_anchor_indices=None) -> TraceResult`. Anchors and result.cells retain current
working-grid row/column coordinates for compatibility only. Routing internally
uses a source-native analysis grid and converts output through map XY. Result
coordinates are source-native XYZ, sampled from source. Params is existing
TraceParams used only for requested output spacing/simplification; Auto search
and terrain scales never depend on legacy corridor/smoothing/attraction controls.
`trace_auto` never invokes legacy trace as a silent fallback.

Result.metrics includes `engine='stream_auto'`, `engine_version=1`,
`status='candidate'|'ambiguous'|'unresolved'`, `analysis_resolution`,
`effective_config` (JSON object), and `diagnostics` (list of JSON objects with
`code`, `message`, optional native `location` XY). Source identity, domain
truncation and conditioning decisions must be disclosed. Confidence is relative
not a calibrated probability. Unresolved may raise actionable ValueError if no
safe geometry exists. No invented paths on flat/no-evidence terrain. Cancel uses
existing TraceCancelled. NoData full native segment validation is mandatory.

New stream Auto is experimental and opt-in until independent promotion evidence
exists; current `trace` is unchanged legacy routing for all other modes. UI must
persist engine choice in draft parameters separately (`settings.stream_engine`
and `settings.draft.engine`) and in accepted feature `engine`/`engine_version`.
Feature parameters remain legacy TraceParams, never reinterpret old distances.
Persistent `protected_junctions` contains exact native XY independent of disposable
solver anchors. Edits/split/join/correction retain protection or reject removal;
`project.protected_junctions` merges persistent and legacy fixed-guide locks.
`project.validate_engine_metadata` validates structured diagnostics, evidence and
consistent engine identity at persistence/edit boundaries. This is conservative
exact-vertex protection, not a coordinated junction network.
Schema 2 writer, schema 1 reader migration explicitly identifies old features
as `engine='legacy'`, version 1; geometry unchanged. Unknown engines/versions
must not silently retrace. Keep metrics engine evidence separate from geometry QA;
edits mark evidence stale and retain provenance. If shared junction editing is
not safely implemented, reject changes that would disconnect coincident protected
connections; do not claim full network-topology support.

UI import occurs lazily from `.stream_auto`; versioned core API above is stable.
Opt-in selection applies only to stream tool and explicit Auto retrace; correction
boundaries remain fixed. Reference layers must be separate from accepted features.

Evaluation inputs must never reach solver except explicitly declared guide XY.
Use development/validation/acceptance catchment splits and disclose missing
reviewed independent holdout; no default promotion with only the initial pilot.
