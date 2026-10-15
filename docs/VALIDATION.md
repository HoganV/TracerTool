# Validation record

**Version 0.2.0 desktop snapshot:** the source suite passed 287 tests on Linux and
287 tests with Windows Python/Qt under Wine. The line-quality comparisons and
native desktop exercises are recorded below. Archives labeled `interim` are
superseded snapshots, not the final delivery.
See [LINE_QUALITY_REVIEW.md](LINE_QUALITY_REVIEW.md) for the before/after record.

Local measurements: 2026-10-14–15, Linux x86_64, Python 3.12.3, Intel Core
i5-12600K. Windows checks use official Windows CPython 3.13.16, Qt 6.9.3 and
Wine 11 on this same host. These are functional checks and a reproducible
processing benchmark, not independent validation of line accuracy.

## Public repository preparation

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

## First GitHub-hosted source verification

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

## Evidence categories

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

## Final portable-package checks

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

## Native mouse/keyboard acceptance

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

## Final review corrections

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

## Reference-input benchmark

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

## Linux baseline and packaging checks

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

## Windows compatibility-layer build and tests

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
