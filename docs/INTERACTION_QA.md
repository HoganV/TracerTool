# Interaction acceptance plan

Use this checklist on the actual packaged application. Automated Qt tests cover
many state transitions; real mouse/keyboard sessions exercise hit targets,
focus, visual feedback and window-system behavior. Neither method establishes
terrain extraction accuracy. Recorded results belong in [VALIDATION.md](VALIDATION.md),
with the exact version/source hashes, platform, dependency versions and artifact
paths. An unchecked item is planned work, not a passing result.

## Test inputs and evidence

Use synthetic curved valleys/ridges, slope transitions, NoData holes/barriers,
flat terrain and small grids for deterministic assertions. Use the six private
reference TIFFs for realistic visual exercises, without uploading or packaging
them. Include a folder with spaces and Unicode, a moved project/terrain pair,
a read-only destination and a source with changed pixels but identical grid
metadata. Avoid destructive tests on the only copy of real work.

For every task record: actions, expected outcome, observed result, geometry
counts before/after, saved/exported paths, screenshots where useful, and any
reproduction steps. When measuring operator benefit, use independently labeled
holdout lines and record elapsed time, clicks, edits, lateral error and missed
branches. Reproducible arbitrary-anchor traces are performance exercises, not
accuracy references.

## Desktop task matrix

| Task | Exercise | Required outcome |
|---|---|---|
| Launch/open | Extract portable folder; launch without a console; open each TIFF. Try missing, corrupt and unsupported inputs. | Correct metadata/rendering; clear errors; failed load retains current project. |
| Explore | Wheel zoom, pan using navigation/right/middle drag, Fit, resize, keyboard focus. | Map remains navigable; cursor coordinates/elevations agree with sample locations. |
| View controls | Four view styles, azimuth/relief, each palette/stretch, gamma/shade/altitude, multidirectional light and contours. | Visible updates; sensible range validation; source XYZ unchanged. |
| Assisted trace | Each line kind, two/multiple anchors, bend/fork constraints, all presets and individual parameters. | Preview remains separate from accepted geometry; guides and line kind agree. |
| Draft editing | Drag guide points, Backspace, Escape, optional auto-preview, switch tool, begin another operation. | Stale previews cannot be accepted; discard/cancel decisions are explicit. |
| Hand editing | Select line/vertex, drag, insert, remove, snap and Alt bypass, NoData-edge edits. | New vertices sample source Z; unchanged vertices stay exact; invalid segments are rejected. |
| Segment correction | Select two boundaries, add/drag inner guides, preview, cancel, apply, undo/redo; attempt selection/history changes mid-correction. | Outside XYZ and boundary XYZ remain exact; correction indices cannot drift to another line or history state. |
| Whole-line retrace | Reload guides/settings, move guides/change parameters, cancel/apply, save/reopen. | Stable feature identity; no duplicate line; reproducible guide restoration. |
| Topology edits | Split interior vertex, join reversed and shared-endpoint lines, reject distant/wrong-kind joins, reverse twice. | Correct orientation, distinct IDs where required, retained original endpoints and NoData-safe bridge. |
| Feature management | Rename Unicode text, checkbox visibility, multi-select, delete, undo/redo. | List/map/profile stay synchronized; selected/checked/all export scopes differ correctly. |
| Settings | Visit each tab; cancel/apply; restore defaults; new-project defaults; save/reopen. | Invalid preferences cannot replace good state; project settings persist; view-only changes do not alter geometry. |
| Project save | Save, Save As, overwrite existing project, inspect previous-good `.bak`; reopen and relocate. | Atomic writes; features/guides/preferences/view restored; relative paths work. |
| Source identity | Relink same file at a new location; try changed grid, CRS and changed content with same grid. | Valid relocation succeeds; mismatched terrain is rejected without corrupting the live project. |
| Recovery | Save draft/accepted edits to recovery; simulate unclean exit on disposable work; restore; test corrupt snapshot. | Saved project untouched; useful draft state restored; corrupt records isolated; clean sessions removable. |
| Cancellation | Cancel during trace/render/reprojection; close while busy; attempt edits while worker active. | No late result committed; controls recover; closing is orderly. Compiled path search cancellation may wait for its current call. |
| Export | Checked/selected/all; default CRS/Z; explicit projected CRS/Z scaling; overwrite and failure cases. | Correct count, XY/Z/fields/sidecars; original features unchanged; failures preserve previous output. |
| Terrain reprojection | Create separate copy with nearest/bilinear/cubic; missing-source-CRS override; cancel; overwrite output with stale sidecars. | Original untouched; valid calibrated samples/NoData retained; failed commit preserves old output/sidecars. |
| GIS handoff | Open shapefile in independent GDAL and target QGIS/ArcGIS Pro; inspect CRS, elevations and attributes. | Correct 3D geometry and projection in the receiving workflow. |
| Long session | Repeated edits/saves/recovery, large working grid, window resize/high DPI, standard-user permissions. | Bounded memory/history, readable controls, recoverable work and no accumulating state errors. |

## Automated coverage

`test_app.py`, `test_desktop_workflows.py` and `test_interaction_edges.py` exercise
Qt event handling and desktop state. `test_editing.py` checks immutable geometry
corrections and source Z. `test_project.py` and `test_recovery.py` cover durable
saves, validation, backups, exports and recovery isolation. `test_raster_ops.py`
checks coordinate conversion, masks, calibration, cancellation and output
rollback. Terrain/tracing tests cover coordinate centers, resolution, curved
features, units and NoData topology.

Run the same suite with Windows Python/Qt as well as Linux. A Windows
compatibility-layer run already caught a writable-handle requirement in raster
durability checks that Linux tests could not expose. Keep failures reproducible
and add focused regressions when they protect real behavior, rather than tests
that merely duplicate the implementation.

## Release evidence boundaries

Native Linux desktop interaction, Windows executable execution under Wine,
real Windows desktop behavior, and target-GIS interoperability are separate
rows in the acceptance record. Never infer the last two from the first two.
Likewise, a successful trace/export test does not establish surveyed positional
accuracy or a hydraulically valid stream network.
