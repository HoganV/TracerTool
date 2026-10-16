# Application module contracts

## Feedback revision (2026-10-15–16)

Disjoint ownership for this revision: tracing lane owns `tracing.py` and
`tests/test_tracing.py`, `tests/test_quality.py`; display lane owns `terrain.py`,
`preferences.py`, `tests/test_terrain.py`, `tests/test_preferences.py`; persistence
and documentation lane owns `project.py`, its tests, and docs other than this
contract plus CHANGELOG.md. Integrator owns app/canvas/desktop_actions/editing,
editing and integration tests, version/configuration, this contract and final
desktop acceptance. The tracing validation lane owns `tests/test_tracing_feedback.py`.

Implemented compatible interfaces: `TraceParams` uses cell-relative defaults with
both smoothing defaults zero; `relax_anchors: bool = True` allows rough assisted
guides to move. Missing persisted `relax_anchors` restores False for an explicit
legacy retrace; saved coordinates never change on load. `trace` adds optional
`fixed_anchor_indices` to preserve snapped connections and segment boundaries.
Search radius accepts finite values of at least one cell without an arbitrary upper cap;
terrain-feature scale and final target spacing are independent of that radius.
`default_params(terrain, kind='stream') -> TraceParams` supplies new-draft defaults.

Display adds `ras`, `topographic`, and `spectral` palettes and a `view` stretch.
`Terrain.rgb(..., view_bounds=None)` accepts clipped half-open raster bounds
`(row_start, row_stop, col_start, col_stop)` for visible valid-cell min/max.
The canvas supplies bounds after pan/zoom using a debounced refresh; no visible
valid cells fall back to the full terrain range. Display changes never alter Z.

Internal contract agreed before parallel implementation. Coordinates are always
in the DEM CRS; UI scene coordinates are column + 0.5, row + 0.5. Arrays index
row, column. No silent reprojection. Source elevations are retained for export.

## `terrain.py`

`Terrain.load(path, max_dimension=2400) -> Terrain` reads band 1 and records any
resampling. Properties: `path` (str), `data` (2D float32, invalid = NaN), `valid`
(bool array), `transform` (Affine), `crs` (rasterio CRS or None), `width`,
`height`, `resolution` (float, working-grid spacing in CRS units), `units`
(str), `metadata` (JSON-safe dict including original width/height, original
resolution, working resolution, min/max, CRS), and `bounds` (left,bottom,right,top).
Methods: `xy(row, col)` returns pixel-center (x,y); `rc(x,y)` returns fractional
(row,col); `sample(x,y)` returns source elevation or None; `rgb(style='Terrain',
azimuth=315, altitude=45, z_factor=1)` returns height x width x 3 uint8 RGB.
Styles: Terrain, Hillshade, Slope, Elevation. Geographic/missing CRS is viewable
but tracing refuses unless projected. Reject rotated/sheared transforms in v0.1.

## `tracing.py`

`TraceParams` dataclass with float fields `corridor=12` (working cells),
`smoothing=0` (working cells), `terrain_weight=8`, `spacing=3` (target working
cells), `simplify=0.75` (bend tolerance in working cells),
`line_smoothing=0` (assisted geometry smoothing in working cells), and boolean
`relax_anchors=True`. Modes: `ridge`, `stream`, `slope_break`, `manual`.
`trace(terrain, anchors, kind, params=None, cancel=None, fixed_anchor_indices=None)
-> TraceResult` accepts anchors as (row,col) working cell indices/floats.
Result dataclass: `coordinates`
(list of [x,y,z]), `cells` (list of [row,col]), `metrics` (JSON-safe dict),
`warnings` (list[str]), `anchors` (original native XY guides), and
`fixed_anchor_indices` (explicitly protected guide indices). The last two fields
default to empty lists for compatibility. `trace_downstream(terrain, start, params)` optional.
All path vertices including simplified/resampled segments must avoid NoData.
Assisted endpoints use valid cell centers and may move when rough guides are
enabled; manual anchors can be fractional. Snapped connections and correction
boundaries stay fixed. Ambiguous terrain leaves guides in place.
Exact snapped vector anchors are restored by the UI and revalidated. The
guidance corridor is explicit.

## `project.py`

`new_feature(name, kind, result, params) -> dict`: id/name/kind/coordinates/
metrics/warnings/parameters/visible. Result is TraceResult; params dataclass.
`save_project(path, terrain_path, features, settings) -> None`: versioned JSON,
relative terrain path, atomic write. `load_project(path) -> dict`: returns
`terrain_path` resolved absolute, `features`, `settings`, validates schema.
`export_geojson(path, features, crs) -> None`: native coordinates with explicit
CRS metadata (document not RFC7946), or reject unsupported cases.
`export_shapefile(path, features, crs) -> list[str]`: PolyLineZ .shp/.shx/.dbf/
.prj/.cpg, preserve CRS and Z, readable short field names. Export selected
features is handled by caller. Raise actionable ValueError on invalid input.

## Ownership

- Terrain agent: terrain.py, tracing.py, tests/test_terrain.py, tests/test_tracing.py.
- Persistence agent: project.py, tests/test_project.py.
- Research/build agent: README.md, docs except this file, packaging and CI.
- Integrator: app.py, canvas.py, __init__.py, __main__.py, pyproject.toml,
  integration tests, final integration and review.

## Workflow hardening cycle (2026-10-14)

Integrator owns app.py, canvas.py, version/configuration, and UI integration.
Terrain lane owns editing.py, tracing.py, terrain.py and their tests.
Persistence lane owns project.py, recovery.py and their tests.
Release lane owns docs except this contract, scripts, CI, packaging and platform
investigation. No lane changes another lane's files without coordination.

### Editing operations (`editing.py`)

All functions are pure (do not mutate arguments), preserve original geometry
outside the edited portion, validate complete segments against NoData, and
return JSON-safe feature dicts. Recompute length/profile QA after edits. Reject
zero-length edges and lines with fewer than two distinct vertices. Coordinates
are native XYZ; cursor locations passed to insert/move are native XY.

- `move_vertex(terrain, feature, index, xy) -> feature`
- `insert_vertex(terrain, feature, after_index, xy) -> feature`
- `delete_vertex(terrain, feature, index) -> feature`
- `reverse_feature(terrain, feature) -> feature`
- `split_feature(terrain, feature, index) -> (feature, feature)`; split vertex
  must be internal, preserve XYZ and create a new id for the second part.
- `join_features(terrain, first, second, tolerance) -> feature`; orient the
  closest endpoints, require same kind, merge within tolerance in map units.
- `replace_segment(terrain, feature, start, end, result, params) -> feature`;
  inclusive indices, result is TraceResult, keep the original boundary vertices
  exactly, preserve outside XYZ and record correction provenance.
- `refresh_feature(terrain, feature, coordinates, operation) -> feature` for
  full replacements. Manual changes invalidate stored trace anchors, which
  the UI may reconstruct explicitly from geometry for future retracing.

`trace(..., cancel=None)` adds an optional callable checked during work; raises
`TraceCancelled` when requested. Existing positional calls stay compatible.
TraceResult gains optional `anchors` (native XY list) so accepted features can
store the original guide points. Optional fields must load in v1 projects.

### Recovery (`recovery.py`)

`RecoveryStore(directory)` writes per-session atomic snapshots without altering
explicitly saved projects. `save(session_id, terrain_path, features, settings,
project_path=None) -> path`; `list_entries() -> list[dict]` (path, updated_at,
project_path, terrain_path, feature_count); `load(path) -> project dict`;
`discard(session_id)` removes only the current session record. Draft state may
be included in settings. Bad/incomplete recovery files must not block startup.
Snapshots retain the last good content after failed writes. Source fingerprints
are optional backwards-compatible settings metadata: source CRS/grid plus
SHA256 digest computed on explicit source load, never each mouse event.

### Desktop release 0.2.0 additions

Manual trace anchors retain fractional working-grid coordinates, including two
separate points in one cell. Assisted modes route through cell centers; the UI
preserves exact snapped endpoints after validating complete resulting segments.
Adjacent assisted guides in the same working cell are rejected explicitly.

`Terrain.load(..., compute_fingerprint=True)` records `source_sha256`;
`fingerprint()` checks source identity. `rgb` accepts palette, stretch,
low/high, shade_strength, gamma, multidirectional and vertical_units, all
strictly display-only. Source decoded Z is never overwritten.

`preferences.py` owns validated nested display/editing/session/export defaults
and dialogs. `desktop_actions.py` owns UI action helpers. Preferences are
preflight-rendered and saved atomically before replacing active settings.
`settings.draft` contains native XY anchors, kind, parameters, optional
edit_target and inclusive segment_range; referenced geometry must validate.
Existing schema-1 projects remain readable without the optional fields.

`raster_ops.reproject_dem(source_path, destination_path, target_crs,
resolution=None, resampling='bilinear', source_crs=None, cancel=None)` writes a
new DEM atomically, preserving source elevation units/calibration interpretation
and NoData. `transform_features(features, source_crs, target_crs, z_scale=1)`
returns detached transformed features. Z changes only by an explicit multiplier;
vertical datum transformation is unsupported. The UI confirms changed export
CRS/Z settings before writing.

Recovery remains separate from explicit saves. Successful project saves retain
a previous-valid `.bak`. Recovery cleanup failure must not invalidate a
successful save. A blocked normal recovery folder falls back to a disclosed
temporary folder; source files are never modified.

### Historical line-quality revision within unreleased 0.2.0

The following defaults describe 0.2.0; the feedback revision above supersedes
them for new drafts in 0.2.2.

`TraceParams.line_smoothing=4.0` is a new optional output-geometry smoothing
radius in working cells, valid 0–50, applied to assisted modes only. Terrain
smoothing defaults to 2 cells; target arc-length spacing defaults to 8 cells.
Legacy schema-1 features and settings lacking line_smoothing remain valid;
explicit retrace restores 0 for that missing field. Saved coordinates are never
recomputed on load. New DBF fields report output smoothing and edit provenance.

Target spacing no longer means retaining every intermediate raster-path bend.
Output must use fresh arc-length sampling, retain fixed guide anchors and
meaningful geometry, and validate every final segment against NoData. Smoothing
must stay constrained by the terrain feature/corridor; visual attractiveness
alone is insufficient. Actual spacing distribution is shown in the UI and
used in quality tests, including straight/curved levees and anomalies.

### Final data-integrity review

Source raster values are decoded in float64 before scale/offset, and the
source sampling cache retains that precision. Only the calibrated working
display grid is cast to float32. Exported Z always comes from source sampling.

Explicit transformed exports retain original measurements in `source_metrics`,
recompute output XY lengths/spacing and Z statistics, and record the output
CRS and Z multiplier in provenance. A multiplier does not identify a vertical
unit or datum. Source-grid measurements are not labeled as output measurements.
