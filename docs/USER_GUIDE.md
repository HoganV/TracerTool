# TracerTool user guide

## First line

1. Open a terrain TIFF with **Open terrain**. The map starts with elevation
   colors and hillshade. Check resolution and units in the terrain information.
2. Explore with the mouse wheel and **Navigate**. Try Hillshade and Slope views
   to distinguish a channel bottom from a bank or ridge.
3. Choose **Stream line** for low ground, or **Breakline** and a mode: ridge
   **Ridge / embankment crest** for high ground, **Slope break / bank edge** for a bank crest/toe or another gradient
   transition. **Manual line** connects your chosen vertices.
4. Click two or more anchors along the intended feature. Use more anchors at
   sharp bends, forks, road crossings, or near competing ridges/channels.
5. Use **Trace preview**. Inspect the candidate against the terrain and the
   elevation profile, then **Accept line** to add it to the project.
6. Use **Edit vertices** to correct accepted geometry, or retrace just a poor
   portion with **Correct segment**. Review the resulting profile again. Save
   the project and export a shapefile when ready.

The candidate is guided by your anchors. It does not decide which drainage
branch, bank side, or surveyed breakline your project needs. A plausible-looking
line still needs review. Z exaggeration changes the terrain display, never the
exported elevations. Use an exaggeration of 1 when interpreting slope angles.

## Parameters

Trace distances use **working terrain cells**, with their physical size shown
below the controls. Defaults scale with the loaded grid: a 1-foot cell gives a
12-foot search radius and 3-foot target spacing; a 10-metre cell gives a
120-metre radius and 30-metre spacing. These are cell-size multiples, not fixed
feet or metres. Larger rasters may use a reduced working grid; check its
resolution before tracing. On rectangular cells the physical distance differs
by direction, so review both cell dimensions and the warning.

| Parameter | Initial value | Accepted range and adjustment |
|---|---:|---|
| Search radius | 12 cells | At least 1 cell, with no application-defined upper cap. Search around the rough guide. Widen it to include a displaced channel or bend; narrow it when a neighboring feature competes. Very large regions take more time and memory. |
| Terrain attraction | 8 | 0–1,000, dimensionless. Increase to favor strong terrain features more; reduce if the route detours toward the wrong feature. Zero removes terrain preference. |
| Target spacing | 3 cells | 0.25–2,000 cells. Target distance between output vertices, independent of search radius. Smaller values retain more samples; larger values reduce vertex count. Bends, fixed connections and NoData can require shorter edges. |
| Bend tolerance | 0.75 cells | 0–200 cells; this is a distance, not an angle. Maximum permitted chord deviation from the routed shape during simplification. Smaller values retain detail and may add short edges; larger values cut more corners. Zero keeps all route detail needed by this stage. |
| Terrain smoothing, in Advanced | 0 cells | 0–50 cells. Blurs the terrain used to find a route. Increase only to suppress known small noise; it can erase narrow ditches and sharp crests. Zero disables this preprocessing. Source elevation samples stay unchanged. |
| Line smoothing, in Advanced | 0 cells | 0–50 cells. Rounds assisted XY geometry within the terrain and obstacle constraints. Increase only when a reviewed route needs less stair stepping; it can soften real bends. Zero disables this stage. |

Hover over a label or control for a short explanation. **Advanced** starts
collapsed, and both smoothing controls start at zero. Presets provide starting
points for **Balanced**, **Levee / embankment**, **Fine ditch / crest**,
**Broad channel**, and **Noisy terrain**. All presets leave smoothing off except
**Noisy terrain**, which explicitly sets both to 1 cell and opens Advanced.
Presets do not classify the terrain or guarantee a good route.

The default first pass is deliberately modest: place rough guides, preview at
3-cell spacing with smoothing off, and inspect the intended crest or valley.
If the feature lies outside the search area, widen the radius without changing
spacing. If another feature wins, move or add a guide and narrow the search.
Increase spacing only after the route is correct; dense vertices do not
improve the source measurement accuracy. Inspect the reported actual
**minimum, median and maximum spacing**, because the target is not a strict
minimum. A wide search radius no longer changes the scale used to recognize
the terrain feature or forces a coarser output step.

Ordinary assisted guides express a rough route and may move during tracing,
including the endpoints. Precise connections snapped to saved lines and local
correction boundaries stay fixed. Turn off guide relaxation when you need all
placed guides held in place. Manual lines retain their chosen corners. Source
Z is sampled only after the output XY is determined.

Existing project geometry and settings do not change when opened. Older lines
without the guide-relaxation option retrace with fixed guides, and older lines
without line smoothing retrace with it off. Choose a current preset or change
the controls explicitly to adopt different behavior.

For a levee, choose **Breakline → Ridge / embankment crest**, then the
**Levee / embankment** preset. Place rough guides along the intended crown,
including changes in direction. Review local dips and sharp anomalies before
accepting. A crest and a bank toe are different tracing objectives.

Exported line vertices and hydraulic mesh points are separate. HEC-RAS's
**Near Spacing** controls computation points around a breakline; it is not
this editor's target vertex spacing. See the
[USACE documentation](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/latest/geometry-data/2d-flow-areas).

## Review and editing

The feature list controls visibility, selection, and which lines are exported.
Double-click a name to rename a feature. Delete unwanted lines. During draft
guide placement, **Ctrl+Z / Ctrl+Y** undo and redo draft changes. Accepted
editing operations have their own undo history; clearing or accepting a draft
clears its temporary history.

Click a numbered guide to select it, then drag to move it. **Delete** or
**Remove point** removes the selected guide; **Backspace** removes the last.
Turn on **Edit guide points** and click a rough-line edge to insert a guide,
or hold **Shift** while clicking that edge during normal drawing. **Escape**
clears the draft. These edits invalidate the old preview; preview again before
accepting. Previewing is separate from accepting so a poor candidate can be
discarded without changing saved features.

For a hand correction, select the saved line and choose **Edit vertices**.
Drag a vertex to move it; click one to select it. **Insert vertex** adds a
point near the selected line's edge. Remove the selected point with Delete or
the editing action. A line must retain at least two distinct vertices.

For a terrain-guided correction, select the line and choose **Correct segment**.
Click two existing vertices around the poor portion, then place or adjust guide
points between those fixed boundaries. Preview the replacement and apply it.
The original XYZ coordinates outside that portion and at the boundaries are
retained. **Retrace line** reloads its guide points and parameters so you can
replace the whole line instead. Canceling a correction leaves accepted geometry
unchanged; applying it is one undoable operation.

**Split here** separates a line at a selected interior vertex. Ctrl-click two
lines in the list and use **Join selected** to connect their closest endpoints
within the configured tolerance. Review the new connecting segment. **Reverse**
changes the coordinate order and profile direction. These operations validate
NoData crossings and refresh geometry diagnostics.

Snapping is enabled initially: hand-edited points use raster cell centers and
can snap to saved line vertices within 8 screen pixels. Hold Alt to bypass
feature snapping. Raster snapping is a separate preference. Join tolerance is
3 map units initially; unlike trace controls, it is not a pixel distance.

Wheel zooms; right or middle drag pans; **F** fits the terrain. With the map
focused, **Enter** traces the draft and accepts an existing preview.
**Ctrl+S** saves, **Ctrl+E** exports, and **Ctrl+Z / Ctrl+Y** undo/redo.

Use the profile to inspect unexpected uphill portions or sudden elevation
jumps. Anchor-guided stream lines are geometric valley candidates; they are
not guaranteed monotonic hydraulic flow paths. Road embankments, real pits,
flat water surfaces, DEM errors and culverts need interpretation. A terrain
raster does not reveal hidden drainage under a road.

## Display and project settings

**Settings** contains terrain/CRS details, display, editing, recovery and export
preferences. The initial display uses Earth colors, the 1st–99th percentile
elevation range, sun altitude 45 degrees, hillshade strength 0.65 and gamma 1.
Choose **RAS-inspired terrain** for teal, light green, dark green, yellow,
orange, red, gray and white from low to high elevations. **Topographic** and
**Spectral** add two further choices alongside Earth, Viridis, Grayscale,
Ocean and Inferno. The RAS-inspired palette follows the requested color
sequence; it is not a claim of an exact HEC-RAS color-table match.

Set **Elevation range → Current view minimum–maximum** in Settings, or choose
**View min–max** in the map toolbar, to remap colors to the valid terrain
visible in the map as you pan or zoom. The toolbar also offers palette choices.
The same elevation can have different colors in different views. NoData does
not contribute to the range; a view without valid terrain falls back to the
full terrain range. Choose full, percentile or custom range to keep a stable
mapping while navigating. These settings affect Terrain and Elevation colors,
never exported Z, trace parameters or accepted geometry.

Also available are multidirectional illumination and display-only contours. Contour intervals use source Z units;
the display limits the number of levels and points to avoid overwhelming the
map. Contours are visualization aids derived from the working grid.

Keep **Z units for display slopes** on source metadata unless the terrain's
vertical unit metadata is missing or wrong and you know the correct units.
This override affects hillshade/slope calculations only. It does not convert
source values or apply a vertical datum transformation.

Editing preferences include snapping, optional automatic preview, join
tolerance, and a 100-operation undo history. Recovery snapshots default to
30 seconds, with a shorter save delay after edits. The maximum working grid
side defaults to 2400 pixels and applies on the next terrain load. Increasing
it uses more memory and processing time. Preferences are saved with projects;
choose **Use these preferences as defaults for new projects** only when you
want them to carry into future projects.

Longer operations run in the background. **Cancel operation** discards a canceled
result. Cancellation is checked between numerical stages; a compiled path
search already running must finish its current call before cancellation takes
effect.

## Projects and export

Save a project to preserve features and settings. Projects refer to the terrain
file using a relative path when possible, and do not embed the TIFF. Copy the
terrain and project together while retaining their folder relationship.
Projects are versioned JSON, not executable files. Application version 0.2.2
continues to use project schema 1. Optional guide-relaxation and fixed-guide
fields preserve draft behavior without recomputing any saved coordinates.
If the source file is missing, the editor prompts to relink it and checks the
saved CRS, extent, grid metadata and recorded content fingerprint before
accepting the replacement. Keep the original file. Projects created before
content fingerprints were recorded have fewer checks available.

Explicit saves retain the previous valid project as `.bak`. **Recover work**
opens local recovery snapshots, including unfinished guide-point drafts.
Recovery is separate from your chosen project file and does not replace normal
saves or backups. Keep the terrain available when recovering a session.

**Export lines** defaults to checked features. Settings can select checked,
selected, or all lines. The shapefile is a three-dimensional polyline dataset;
the default preserves the terrain's CRS. Keep the `.shp`, `.shx`, `.dbf`, `.prj`,
and `.cpg` files together. Exported
Z values use nearest-pixel sampling of the source DEM after applying the raster
band's scale/offset encoding, with its original units and datum semantics;
view exaggeration does not alter them. Verify the result in your target GIS
before integrating it into a deliverable. Shapefile attribute names are short
because of the format's limits; the project is the richer editable record.

The export includes `smooth_ln` (global line-smoothing radius), `edited`,
`prov_cnt` (provenance entry count), and `last_op`. Different settings used for
a local correction remain in detailed project/GeoJSON provenance; one global
DBF row cannot describe every segment's editing history.

An optional output projected CRS changes XY coordinates. An explicit Z
multiplier changes the exported elevations; the default is 1. These are
separate choices. XY reprojection never transforms a vertical datum. Converted exports recalculate output geometry metrics and retain the original metrics separately. An explicit Z multiplier does not establish a new vertical unit or datum; its factor is recorded in provenance. Review
the export summary, including line count, coordinate system and Z multiplier,
before writing a transformed export. The editor retains its original geometry.

The optional projected-coordinate GeoJSON export includes CRS metadata and
uses the terrain CRS unless an output CRS is explicitly selected. It is a
local GIS interchange document, **not RFC 7946 web GeoJSON** in longitude and
latitude. Use the shapefile for the intended desktop GIS handoff.

## Current boundaries

The editor uses one raster per project. Very large rasters may use a
reduced working grid to bound memory; inspect the disclosed working resolution
before tracing. Geographic or missing-CRS inputs can be viewed but cannot be
traced as projected engineering terrain. Rotated/sheared grids are rejected
by the viewer. **File → Reproject terrain copy** creates a new north-up GeoTIFF
in a specified projected CRS while preserving the original file. Open that
copy as a separate terrain project. Its elevation samples are resampled, but
their units/datum are retained. Supply a source CRS override only when you know
the actual source definition. The editor does not infer a vertical datum,
combine tiles, fill depressions, or infer a complete stream network automatically.

If a trace fails, check that both anchors lie on valid terrain and that a
connected valid route exists inside the corridor. Do not bridge a NoData gap
by accepting a straight segment without evidence. A narrower corridor and
more anchors usually make the intended feature easier to identify.
