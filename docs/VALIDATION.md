# Validation record

## 0.2.2 — terrain display and draft tracing, 2026-10-16

The final Linux source suite passed **457 tests in 46.49 seconds**, using Qt's
offscreen platform. The application startup smoke test and installed-dependency
consistency check also passed. Real mouse/keyboard desktop exercises are
recorded separately below; the automated run alone does not establish an
interactive workflow.

The focused terrain/tracing coverage includes 60 feedback cases within 84
focused tests. On generated curved valleys, ridges and bank slope breaks,
rough guides offset by eight cells produce mean feature error below 0.5 cells
and maximum error at most 1.1 cells. These checks run at one-foot and 30-metre
horizontal cell sizes, preserve source Z and validate all final segments.
They also cover flat/ambiguous terrain, isolated pits, true downhill pit
termination, fixed connections and NoData barriers. Synthetic error is measured
against the generated feature, not independently surveyed terrain.

Wide-search cases range from 12 to 2,501 cells and an extreme finite radius of
1e200 without changing the 3-cell spacing target or allocating beyond raster
bounds. Tests check terrain-feature retention, actual spacing and NoData-safe
chords. Project and recovery coverage checks legacy missing fields, relaxed
and fixed guides, invalid booleans/indices, moved sources and unchanged XYZ in
project/GeoJSON/shapefile round trips. Shapefile numeric field capacity remains
a format limit with an actionable export error.

Interaction regressions cover view rendering without a progress-bar/layout
refresh loop, automatic previews queued after a display render, invalid custom
color ranges leaving prior settings intact, display-only palette/range changes
preserving an unaccepted preview, and snapped-guide indices being preserved,
reversed or invalidated as appropriate. A rapid insertion followed
by a drag no longer creates a duplicate guide through a double-click event.

### Continuity correction found during native inspection

A wide-radius ridge preview exposed an endpoint leaving the continuous crest
to chase a short, sharp neighboring bump. Candidate guides had relied too much
on evidence at one cross-section. The corrected score samples along the local
guide direction up to eight cells on each side, limited to one quarter of the
nearest guide separation around bends. This support distance is independent of
search radius; it does not enable either optional smoothing stage.
Available one-sided terrain supports guides at raster edges. Nine additional
boundary and NoData cases verify that support stops at gaps and diagonal
corner touches, and that valid guides near the edge still adjust to the feature.

Eighteen additional regression cases place one-, two- and three-cell-long
bumps or pits beside a continuous ridge or channel at the first, middle or last
guide. In the motivating synthetic comparison, maximum centerline deviation
fell from 45 cells to zero; the tests require at most one cell and preserve
source Z, spacing and NoData safety. This is a synthetic reproduction of the
failure mechanism, not a bound on real-terrain positional accuracy.

The repeated native ridge trace, using a 48-cell radius and 3-cell target
spacing, visibly stayed on the crest without the previous endpoint tail and
was accepted, saved and exported. It
contained 237 vertices over 704.036 feet, compared with the earlier 770.752-foot
route. Minimum sampled Z was 995.372 feet instead of 986.542 feet; the affected
endpoint was 995.378 feet instead of 987.670 feet. These heights describe the
source DEM sampled at the two routes, not an independent survey comparison.
The accepted ridge had 3.0-foot median spacing and a 2.7–3.0-foot range;
exported XYZ matched the project, sampled source Z and NoData-safe segments
were verified. The inspection image is retained locally and is not published.

### Hosted source checks for the initial 0.2.2 snapshot

The [initial 0.2.2 workflow](https://github.com/HoganV/TracerTool/actions/runs/38917533376)
passed for source commit
[`3459a7e`](https://github.com/HoganV/TracerTool/commit/3459a7e):

| Hosted environment | Automated suite |
|---|---|
| Linux, Python 3.11 | 430 passed in 34.47 seconds. |
| Linux, Python 3.12 | 430 passed in 34.60 seconds. |
| Windows, Python 3.13 | 430 passed in 71.96 seconds. |
| Windows, Python 3.14.7 | 430 passed in 79.53 seconds. |

All four environments also passed the startup smoke test and dependency
consistency check; the complete-history publication audit passed. These are
native source-installation tests with Qt offscreen, not interactive Windows or
portable-package acceptance. This hosted snapshot precedes the endpoint
continuity correction described above. Its later 457-test local result must
not be attributed to this 430-test workflow; hosted follow-up verification is
not yet recorded here.

### Native Linux computer-control checks

The real Linux Qt application was operated with mouse and keyboard on private
one-foot projected terrain and the additional lower-resolution geographic
USGS terrain. The geographic source was viewed directly, then used to create
an explicit projected copy with 30-metre output cells. Loading that larger copy
used the disclosed reduced working grid at approximately **47.4422 metres per
cell**. The source input was retained. A 3-cell spacing setting on that working
grid represents about 142.3 metres, not 3 metres or the copy's 30-metre cells.

The exercised workflows included RAS-inspired colors and current-view min/max,
zoom and pan, rough-guide insertion/move/deletion, Ctrl+Z/Ctrl+Y, preview and
acceptance, project save/reopen and shapefile export. Changing the palette and
elevation range retained the unaccepted preview with Apply enabled. Wrapped
parameter help was inspected visibly. Repeated display changes and guide edits
were used to check the interaction fixes above. Private source
filenames and screenshots remain outside the public documentation and source.

The final repeated coarse-terrain trace used a **500-cell search radius** with
**3-cell target spacing** and five rough guides. It produced **136 vertices**
over **19,087.4 metres**, with measured spacing **142.2 metres median,
131.6 minimum and 142.2 maximum**. This demonstrates that the wider search does
not force coarser output spacing in that exercised case. The final-code line
was previewed, accepted, saved and exported; project/export read-back checks
confirmed the stored coordinates.

The final-code one-foot trace produced **467 vertices over 1,307.3 feet**,
with spacing **3.0 feet median and range 0.9–3.0 feet**, using 12-cell radius,
3-cell spacing and both smoothing settings zero. It was accepted, saved and
exported after the display changes above. Shorter edges remain possible around
necessary bends; target spacing is not a promised minimum.

PyShp read-back matched each project's exported XYZ exactly.
Every Z matched sampling from the loaded source raster within 1e-8, and every
final segment was validated against NoData on both fine and coarse terrain.
For the coarse project, that source raster is the explicitly reprojected copy;
its resampled values are not claimed to be identical to the geographic source.
These are observed workflow and geometry measurements. No independently
labeled channel or crest was available to establish real-world accuracy.

### Limits for this revision

No 0.2.2 portable package, frozen-resource smoke test or interactive native
Windows acceptance was performed. Hosted results apply to the exact source
commits identified above. The 0.2.1 checks and 0.2.0 portable/Wine evidence below
apply only to those historical snapshots.
QGIS/ArcGIS Pro acceptance, independent terrain accuracy, hydrologic validation
and measured operator productivity remain open gates.

## 0.2.1 — Windows Python 3.14 installation

The [Python 3.14 compatibility workflow](https://github.com/HoganV/TracerTool/actions/runs/38773225094)
passed on 2026-10-15 for commit
`d7221e41a490ee6c5da19002cfe7c24fef07843c`:

| Hosted environment | Qt/PySide6 | Automated suite |
|---|---|---|
| Windows Server 2025, Python 3.14.7 x64 | 6.10.3 | 311 passed in 48.45 seconds. |
| Windows Server 2025, Python 3.13.16 x64 | 6.9.3 | 311 passed in 46.27 seconds. |
| Linux, Python 3.12 | 6.12.0 | 311 passed in 23.65 seconds. |
| Linux, Python 3.11 | 6.12.0 | 311 passed in 24.27 seconds; 152 warnings. |

All four environments passed dependency installation, `pip check`, and the
startup smoke test. Runtime output confirms the exact Windows interpreter and
Qt versions above. The complete-history publication audit passed. A local
Linux regression run also passed all 311 tests in 32.63 seconds.

These are source-installation checks with Qt's offscreen platform, not an
interactive test on the recipient's work machine. No 0.2.1 portable package
was built or published. Historical 0.2.0 portable evidence below does not
establish a Python 3.14 frozen build. Terrain algorithms and project schema
are unchanged in this patch.

## Historical 0.2.0 desktop baseline

**Version 0.2.0 desktop snapshot:** the source suite passed 287 tests on Linux and
287 tests with Windows Python/Qt under Wine. The line-quality comparisons and
native desktop exercises are recorded below. Archives labeled `interim` are
superseded snapshots, not the final delivery.
See [LINE_QUALITY_REVIEW.md](LINE_QUALITY_REVIEW.md) for the before/after record.

Local measurements: 2026-10-14–15, Linux x86_64, Python 3.12.3, Intel Core
i5-12600K. Windows checks use official Windows CPython 3.13.16, Qt 6.9.3 and
Wine 11 on this same host. These are functional checks and a reproducible
processing benchmark, not independent validation of line accuracy.

## Historical 0.2.0 public repository preparation

The subsequent public-source preparation passed **311 tests on Linux** in
32.96 seconds, and **303 tests with 8 skips under Windows Python/Qt in Wine**
in 40.67 seconds. The eight skips require Git, which is absent from that
isolated Windows toolchain; all corresponding repository checks passed on
Linux. Subsequent GitHub-hosted checks also passed on Windows and Linux, as
recorded below.

The additional checks cover a deterministic synthetic levee/stream demo,
source elevations, geometry and screenshot generation, plus public-file and
history protection. They detect deleted-but-retained private files, raster
sidecars, private filename/metadata patterns, broken local links, inconsistent
versions, shallow history and uncommitted tracked changes. This focused guard
does not constitute an exhaustive secret, license or image-provenance audit.
The source smoke test and installed-dependency consistency check also passed.

Private reference identifiers in the current documentation were replaced by
anonymous labels. The original development history remains local; publication
uses a separate sanitized history as described in [PUBLISHING.md](PUBLISHING.md).
The README image is a real Qt capture of the generated synthetic fixture. It
contains no private terrain and makes no positional-accuracy claim.

## Historical 0.2.0 first GitHub-hosted source verification

The [first public workflow run](https://github.com/HoganV/TracerTool/actions/runs/38771382982)
passed on 2026-10-15 for source commit
`abcb1612db86cb57c51afdf104def654f5007b51`:

| Hosted environment | Automated suite |
|---|---|
| Windows, Python 3.13 | 311 passed in 46.45 seconds, including the Git-dependent checks. |
| Linux, Python 3.11 | 311 passed in 23.08 seconds; 152 warnings reported. |
| Linux, Python 3.12 | 311 passed in 21.71 seconds. |

All three jobs also passed dependency consistency and the application startup
smoke test. The complete-history public-source audit passed. Portable-build
jobs were skipped, as configured for ordinary pushes; this run published no
binary artifacts.

These source tests used Qt's offscreen mode. Windows runner success is evidence
of native Windows automated execution, not interactive desktop acceptance or
a clean extracted Windows portable-package test. Those gates remain open.

## Historical 0.2.0 evidence categories

| Environment/check | Result and boundary |
|---|---|
| Linux source and frozen Qt application | Startup/render/trace/save/export checks passed; native XCB launch and real-terrain screenshot inspected. Final source suite: 287 tests passed in 29.10 seconds. |
| Windows source application | Final source suite: 287 tests passed in 38.54 seconds with Windows CPython/Qt under Wine 11, including offscreen desktop workflows. |
| Native Linux desktop interaction | Real mouse/keyboard control in a separate Xephyr X11 desktop completed tracing, correction, settings, save/reopen/export, recovery and geometry-editing tasks described below. This was not the locked main desktop session. |
| Windows portable executable | Actual PE32+ GUI x86-64 executable built using Windows PyInstaller. Frozen and clean-extracted smoke tests passed under Wine 11; bundled Qt platform plugin, PROJ database and CPython license verified. |
| Independent format reader | GDAL `ogrinfo` confirmed demonstration shapefile geometry, feature count, CRS units and fields. |
| Revised levee geometry | Same-guide comparisons: straight levee 620→203 vertices, median spacing 7.97 cells; curved levee 580→174, median 7.88. All revised edges ≥5 cells in these two cases; imagery/vertex overlays visually inspected. |
| Interactive Windows desktop | Not performed. Hosted Windows offscreen tests and Wine do not satisfy this gate. |
| QGIS / ArcGIS Pro handoff | Not performed; independent GDAL read is narrower evidence. |
| Operator-reviewed positional accuracy | Not measured; no labeled reference geometry supplied. |

Release source hashes and dependency versions are recorded in each bundle's
`build-info.json` and `build-environment.txt`. Exact test logs and local desktop
artifacts remain in ignored build/artifact directories rather than the public
source tree.

## Historical 0.2.0 final portable-package checks

Both final 0.2.0 packages were built from the same application-source SHA-256
map, matching the tested source. Each archive passed its SHA-256 and ZIP CRC
checks, extraction into a fresh path containing spaces and `Ω`, and the frozen
smoke scenario from that extracted directory. Python/GDAL/PROJ environment
overrides were removed; Linux also ran without `LD_LIBRARY_PATH`. These checks
exercise bundled dependencies rather than relying on the source environment.

The final archive names are:

- `dist/linux/TracerTool-0.2.0-linux-x86_64-portable.zip`
- `dist/windows/TracerTool-0.2.0-windows-amd64-portable.zip`

Each has a matching `.zip.sha256` file. The Windows executable is PE32+ GUI
x86-64; its Qt platform plugin, PROJ data and CPython license are present.
Bundled DLL headers contain no Wine builtin/placeholder markers. No TIFF,
project file or detailed reference inventory is present in either archive.
A short privacy note replaces `docs/INPUTS.md` in those local portable archives.
The later sanitized source archive includes the public data/example guide.
The old `dist/TracerTool` application was preserved.

These are verified local builds. The actual Windows checks ran under Wine,
and clean Windows/target-GIS acceptance remains open.

## Historical 0.2.0 native mouse/keyboard acceptance

The integrator controlled the real application through mouse and keyboard in
a separate Xephyr X11 desktop, using the supplied TIFFs. The main desktop was
locked; this evidence does not claim interaction with that locked session.
The following workflows were exercised and resulting files/state inspected:

- Stream/ridge previews and acceptance, fixed-boundary segment correction,
  zoom/pan/Fit, project save/reopen, and shapefile export.
- All five settings tabs; Viridis colors, multidirectional hillshade and
  5-foot contours; 5-second recovery interval. Saved preferences read back
  correctly and display changes left accepted geometry unchanged.
- Recovery of two accepted lines and a two-guide manual draft after forcibly
  terminating only the disposable test process, then reopening the recovery
  chooser in a fresh application process.
- Manual-line acceptance and vertex move/split/join/reverse/insert/delete,
  with saved provenance checked after the operations.

Local evidence is under `artifacts/desktop-acceptance/` and
`artifacts/quality/`; outputs include `Native workflow.tracer.json` and
`Native lines.shp`. Independent GDAL inspection confirmed two exported
3D Line String features with the NAD83(2011) source CRS and foot units.

The revised curved-levee path was also previewed and accepted with actual
mouse clicks on `private tile 5`: 176 vertices and median spacing 7.9 cells.
Its minimum edge was 1.3 cells because the clicked hard guides differed from
the exact analytical comparison guides. This is a separate case from the
174-vertex exact-guide comparison, whose edges all exceeded 5 cells. The
native result was visually clean, and its shorter edges were disclosed rather
than concealed by the target-spacing label. Its exported 176-vertex shapefile
was independently opened by GDAL as one 3D Line String with foot-based CRS;
exact XYZ/source-Z readback and all-segment NoData validation passed. The
export dialog was opened and closed again to verify the sidebar stayed
unclipped. The inspected view is `artifacts/quality/native-levee-zoom.png`.

The final **packaged Linux executable** was also launched with the native XCB
backend after removing `LD_LIBRARY_PATH`, `PYTHONPATH`, `PYTHONHOME`, `GDAL_DATA`,
`PROJ_DATA` and `PROJ_LIB`. It opened the quality-review project and rendered
correctly. Real mouse input selected the line, entered retracing, chose the
levee preset, changed line smoothing to 6 cells and target spacing to 10 cells,
and generated a 141-vertex preview with median spacing 9.8 cells. The crest
was visually clean. Cancel restored the original 176-vertex line. The native
log was clean; evidence is under `artifacts/quality/frozen-native-start.png`,
`frozen-native-adjusted-preview.png` and `frozen-native-cancel.png`.

## Historical 0.2.0 final review corrections

- Converted vector exports preserve source metrics separately and recompute
  output metrics. GeoJSON metadata now states the actual output coordinates;
  explicit Z scaling does not infer a vertical unit or datum.
- Calibrated integer DEMs decode to float64 before applying band scale/offset,
  retaining source-sample precision for exported elevations. Regression cases
  cover large stored integer values whose small decoded differences previously
  disappeared in float32.
- Recovery checks directory writability before use and falls back to a stable
  per-user directory, so a later application process can discover snapshots.
- The sidebar derives its minimum width from actual control/font/DPI size
  hints and the scrollbar. Both the production Fusion appearance and Windows
  default styling are checked across all tools, so focusing a control cannot
  silently scroll the panel sideways; export-dialog return stays unclipped.

## Historical 0.2.0 reference-input benchmark

Refreshed 0.2.0 benchmark: `python scripts/benchmark.py`, using terrain smoothing
2 cells, line smoothing 4 cells and target spacing 8 cells. The six local
reference TIFFs remain at native 1501 × 1501 resolution. Each measurement
loads a tile, renders all four views without a warmed render cache, then
traces stream/ridge/slope-break/manual paths between normalized anchors
(row 0.35H, column 0.40W) and (row 0.65H, column 0.60W). These reproducible
locations are for timing, not labeled terrain features.

| Tile | Load, seconds | Four views total, seconds | Four traces total, seconds |
|---|---:|---:|---:|
| `private tile 1` | 0.153 | 0.527 | 0.552 |
| `private tile 2` | 1.217 | 0.669 | 0.414 |
| `private tile 3` | 0.273 | 0.702 | 0.469 |
| `private tile 4` | 0.203 | 1.239 | 0.485 |
| `private tile 5` | 0.122 | 1.186 | 0.466 |
| `private tile 6` | 0.114 | 0.808 | 0.471 |

Timing varies with disk cache, machine load, route length, corridor size and
terrain. The exact run is saved locally at
`artifacts/quality/benchmark-0.2.0.json`, including metrics and warnings;
this generated file is excluded from source control. No hand-digitized
reference lines were supplied, so positional accuracy and operator time
savings remain unmeasured.

## Historical Linux baseline and packaging checks

A Linux PyInstaller build successfully ran the frozen application's smoke test:
Qt initialization/window rendering, generated GeoTIFF creation/loading, terrain
tracing, project save/reopen, and shapefile export. The bundled GDAL/PROJ and Qt
dependencies were therefore exercised outside the source Python environment.
This first used an offscreen platform. The frozen executable subsequently also
opened a supplied TIFF and captured an inspected screenshot using native XCB,
with the source checkout's `LD_LIBRARY_PATH` removed. This confirms that the
locally needed XCB dependency was bundled for this host, but does not establish
compatibility with every Linux distribution or graphics environment.

The source application also launched in the native Linux Qt desktop after
the local XCB dependency was supplied. Its real-terrain screenshot was visually
inspected. A demonstration project contains two illustrative traces on the
provided terrain; these demonstrate the workflow and are not operator-approved
reference geometry. The generated project and screenshot remain local in
`artifacts/` and are not bundled with the application.

At the v0.1 baseline, **74 automated tests passed in 9.01 seconds**: 22 terrain/
tracing checks, 34 persistence/export checks, and 18 Qt desktop checks.
An independent GDAL `ogrinfo` read confirmed the exported
demonstration shapefile as **3D Line String**, with **two features**, source CRS
foot units, and the expected attribute fields. This provides an independent
format check but does not replace inspection in the intended GIS workflow.

The initial Linux host lacked `libxcb-cursor.so.0`, which Qt's XCB plugin needs.
A local copy extracted from the distribution's package enables this host's
desktop session; `scripts/run.py` discovers it, and the CI workflow installs
the corresponding system package. The initial offscreen smoke result did not
depend on it. At that initial baseline the CI workflow had not run remotely;
the later successful hosted source run is recorded separately above.

## Historical 0.2.0 Windows compatibility-layer build and tests

The Windows executable was built locally without uploading code or terrain.
The isolated environment runs official Windows CPython 3.13.16 and Windows
wheels through Wine 11. The first Windows source suite exposed a real
portability defect: `os.fsync` on a read-only raster handle fails because the
Windows CRT requires a writable descriptor. Opening the completed temporary
raster as `r+b` fixed that failure. A test's OS-specific path expectation was
also corrected to match the project's portable slash-separated path format.
The corrected suite passed. Final coverage reached 287 passing tests after
export-metadata, calibrated-elevation, recovery and platform-specific sidebar
regressions were added.

The actual portable executable subsequently passed the same built-in frozen
smoke scenario: create/load generated TIFF, initialize/render Qt, trace, save/
reopen a project, export vectors, and exit successfully. The inspected ZIP
contained `qwindows.dll`, `proj.db`, the CPython license, dependency notices and
build metadata, and contained no reference TIFFs or project files. This is
execution evidence for the Windows binary under Wine; it does not test Windows
Explorer, Windows graphics drivers, workplace policies or native file dialogs
on a physical Windows installation. See [WINDOWS_BUILD.md](WINDOWS_BUILD.md).

The final Windows executable also ran with `QT_QPA_PLATFORM=windows` under
Wine on the separate Xephyr desktop, exercising `qwindows.dll` beyond the
offscreen checks. It opened the private curved-levee project and rendered the
terrain and line correctly with unclipped controls. Actual mouse input selected
the line, entered Retrace, generated a preview and canceled the edit. Cancel
retained the 176-vertex line, removed draft guides and restored controls.
Screenshots `artifacts/quality/windows-visible.png`, `windows-retrace.png`,
`windows-preview.png` and `windows-cancel.png` were visually reviewed. The
application reported no errors; Wine emitted EGL driver warnings. This is
visible Windows-Qt execution under Wine, not real Windows desktop acceptance.

## Remaining acceptance work

- Review real feature geometry against operator-drawn ground truth and measure
  editing time and clicks to accepted output.
- Open exported shapefiles in QGIS and the target ArcGIS Pro environment to
  inspect CRS, geometry and source elevations independently.
- Validate the Windows portable ZIP as a standard user on a clean machine.
- Exercise longer editing sessions, failure/recovery and large raster memory
  behavior against the release gates in [ROADMAP.md](ROADMAP.md).
