# Roadmap and delivery controls

TracerTool is an independent, offline desktop editor for turning terrain into
reviewed stream centerlines and breaklines. Version 0.2.0 delivers complete
local editing, correction, settings, recovery and export workflows, plus Linux
and Windows portable executables. Phase completion is determined by evidence,
not by the presence of a UI button or build recipe. The 0.2.2 feedback revision
adds conservative tracing defaults, movable draft guides and display options;
it does not close the independent accuracy or platform acceptance gates. Some
later-phase work has been pulled forward; the remaining gates stay explicit.

## Product decisions

- Native PySide6 desktop UI, Python scientific/geospatial core, no server.
- One DEM per project initially; source projected coordinates are preserved.
- Assisted anchor-to-anchor routing is primary. Human review remains explicit.
- Stream, ridge crest, slope break, and manual lines share the same editor.
- JSON projects preserve editable lines and settings; PolyLineZ shapefiles are
  the primary GIS handoff. Source raster paths are referenced, not embedded.
- A portable folder/ZIP is the Windows delivery target. A single-file executable
  and an installer are optional later conveniences.
- Original code is MIT. User TIFFs have no granted redistribution license and
  are excluded from releases. Dependencies retain their own licenses.

## Segmented delivery plan

| Phase | Work packages and parallel lanes | Dependencies | Exit evidence |
|---|---|---|---|
| **0. Baseline and contracts** | Inventory TIFFs; research candidate methods; agree coordinate, trace, project, export interfaces; record risks. | None | Reproducible inventory, linked research, synthetic fixtures, agreed ownership. |
| **1. v0.1 working prototype** | A: raster load/shading and corridor tracing. B: atomic JSON project persistence and Z shapefile export. C: Qt map/editor, preview/accept, feature management, profiles. D: guide, tests, portable build recipe. | Phase 0 contracts | Open real TIFF, trace each mode, edit, save/reopen, export/read back; review UI; all integration tests pass. Windows recipe does not count as a verified Windows binary. |
| **2. v0.2 local desktop build** | Delivered: segment/full retracing; move/insert/delete/split/join/reverse; snapping; background operations; recovery and backups; project preferences; real Windows PE build with pinned dependencies. Remaining: operator benchmark, connected-network rules and clean Windows acceptance. | Stable Phase 1; interaction and persistence tests | Local editing and frozen smoke evidence recorded. Full phase acceptance still needs measured operator benefit and a real Windows machine with no Python/ArcGIS installed completing the workflow. |
| **3. v0.3 robust terrain intelligence** | A: optional Priority-Flood/breaching with fill-depth inspection. B: D8/D-infinity accumulation, drainage suggestions, pit/flat QA. C: multiscale directional ridge/slope-break responses and adaptive spacing. D: benchmark comparison and confidence visualization. | Phase 2 benchmark; conditioning interfaces | Improvements against current and manual baselines on held-out terrain; source Z remains unchanged; ambiguous or disconnected cases are visible. |
| **4. v0.4 large projects** | A: tiled full-resolution windows, overview rendering and cache limits. B: mosaics and seam behavior. C: GeoPackage and vector reference layers. D: migrations and expanded integrity manifests. Separate terrain reprojection, transformed exports, recovery and source fingerprints were delivered in v0.2. | Stable spatial/project model | Multi-tile tests, memory budget and cancellation targets met; no resolution loss hidden from the operator; moved projects recover predictably. |
| **5. v1.0 dependable release** | Accessibility and keyboard review; complete tutorials; repeatable package manifests; third-party license/source delivery; signing decision; support and bug templates. | Accepted prior phases | Release checklist below completed; tested Windows ZIP and checksum; reproducible bug report; documented limits and migration path. |

Phases describe scope, not promised dates. The six original terrain tiles are
small enough for native-resolution v0.1 work; large-area streaming is a separate
engineering task. A cross-platform codebase is not evidence of successful
installation on every platform.

## Agentic execution model

One integrator owns the application boundary and accepts each work package. Use
parallel agents for disjoint files; the initial contract is
[INTERFACES.md](INTERFACES.md). Shared infrastructure changes are proposed to the
integrator before implementation. Work packages have these fields:

```text
ID / owner / files owned / dependencies
User-visible outcome / explicit non-goals
Inputs and outputs / coordinate and unit conventions
Acceptance checks / benchmark fixture
Risks / migration impact / documentation touched
Completion report: changed files, checks run, known gaps
```

Ready → in progress → review → integrated → verified is the default lifecycle.
Do not silently change a teammate's API to make a test pass. Resolve interface
differences before merging; re-run cross-module round trips after integration.
For longer work, use one isolated branch/worktree per lane once the shared
baseline is committed. Prefer small commits named for behavior. Never commit
private terrain, generated distributions, local environments, or credentials.

An agent may choose libraries and tune provisional defaults within its scope.
Changing source data, introducing external services, modifying licensing, or
claiming production accuracy requires explicit review with concrete evidence.
Normal application operation remains local. A blocked lane records the smallest
missing dependency and continues independent work instead of blocking the team.

## Review gates

**Spatial correctness:** identity and pixel-center round trips; known horizontal
and vertical units; projected, geographic, missing and rotated CRS cases;
NoData endpoints and intervening barriers; rectangular cells; source Z sampling.

**Algorithm correctness:** curved synthetic ridges/valleys/slope changes; flat
surfaces; competing features; pits; long segments; boundaries; reproducibility;
protected-anchor preservation and bounded rough-guide movement;
simplification/resampling cannot tunnel through NoData.
Hydrology claims require separate uphill, pit, flat, and outlet diagnostics.

**Project/export correctness:** schema validation; save/load equality; relative
source-path relocation; bad/missing input messages; atomic project writes;
shapefile fields, CRS, all sidecars, Z values and readable Unicode. Test the
export with an independent reader, then manually open it in QGIS and ArcGIS Pro
when available. Do not treat same-library read-back alone as interoperability
certification.

**Interaction:** novice can open, inspect, anchor, preview, accept, correct,
save/reopen and export without a console. Test dirty state, failed operations,
undo/redo, feature naming/visibility, cancellation and unsaved work. Capture a
screenshot of a real input and complete a deliberate manual editing exercise.

**Performance:** record hardware, input size, native/working resolution, initial
load, shade refresh, per-preview latency, peak memory, and exported vertex
counts. Initial targets for Phase 2: preview under one second for typical
short segments and responsive cancellation under 250 ms. These are targets to
measure, not v0.1 performance guarantees.

## Versioning and release policy

Use SemVer (`0.1.0`, `0.2.0`, …) for app releases and a separate integer project
schema. While pre-1.0, document every format or behavior change. Never reinterpret
an old project silently; either migrate with fixtures or reject it clearly.
Keep `pyproject.toml`, `tracertool.__version__`, changelog, and release artifact
names consistent. Pin resolved dependencies for release candidates and retain
the environment manifest generated by the build.

The CI configuration runs synthetic tests on Windows and Linux when invoked; it must not depend on the user's
TIFFs. Portable packaging is separately exercised with the target platform's
Python and bootloader. Wine provides a useful Windows compatibility-layer
check but does not satisfy native Windows acceptance. Do not
automatically publish a release just because CI produced an artifact. Version
0.2.0 is a local desktop build with the evidence boundaries in VALIDATION.md.
The broader dependable-release gate for v1.0 requires all of these checks:

- [x] Synthetic tests and all project/export round trips pass (287 tests on
  Linux and Windows Python/Qt under Wine).
- [x] Frozen executable smoke test loads GDAL/PROJ, Qt and a generated DEM
  in both packages (Windows execution under Wine).
- [ ] Windows 11 clean-machine open/trace/edit/save/reopen/export workflow passes.
- [ ] Standard-user Windows workflow, including paths with spaces/Unicode, is
  tested on a real Windows host. Local clean-extraction checks are recorded
  separately and do not satisfy this entire gate.
- [ ] Shapefile display, projection and elevations are inspected in target GIS.
- [ ] Operator-reviewed reference geometry supports positional-accuracy and
  productivity claims; no such claims are made for the local build.
- [ ] Dependency versions, hashes, notices and required license/source materials
  are included; user terrain is absent.
- [x] Current known limitations and a rollback-compatible project migration
  policy are documented.
- [x] Benchmark results support the stated timing and illustrative geometry
  claims; positional accuracy and productivity improvement are not claimed.

## Highest-priority work after v0.2.0

1. Build a small operator-reviewed reference-line set; the supplied TIFFs alone
   cannot establish centerline or breakline accuracy.
2. Complete and validate the Windows portable build on a real workplace-like
   computer; honor workplace executable policies without bypasses.
3. Add true hydrologic conditioning and junction constraints for stream network
   work; keep assisted valley tracing distinct from flow routing.
4. Handle larger DEMs at full analysis resolution with tiled workloads.
5. Extend long-session recovery, accessibility and export interoperability
   evidence using the [interaction checklist](INTERACTION_QA.md).
