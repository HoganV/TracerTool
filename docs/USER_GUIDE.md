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

Distances below are working raster pixels. On the supplied one-foot tiles,
one pixel is one foot; the files are small enough to remain at native
resolution. Other datasets can have different units and cell sizes.
On rectangular cells, pixel-based controls represent different map distances
along the two axes; review the warning and both cell dimensions.

| Parameter | Initial value | Meaning and adjustment |
|---|---:|---|
| Search radius | 30 px | Corridor distance around each anchor segment. Narrow it to avoid a neighboring feature; widen it when the intended curve is outside the search region. |
| Terrain smoothing | 2 px | Scale used to suppress tiny terrain fluctuations before measuring shape. Increase for noisy terrain; reduce if narrow ditches or sharp crests disappear. |
| Line smoothing | 4 px | Smooths the assisted line's XY shape within a bounded terrain-following neighborhood. Increase to reduce small stair steps; reduce around real anomalies or sharp bends. Zero disables this stage. |
| Terrain attraction | 8 | Strength of terrain preference in the path cost. Increase if a path cuts across the feature; reduce if it detours to an unintended strong feature. |
| Target spacing | 8 px | Starting arc-length spacing along the smoothed shape, redistributed between fixed guides. Closely placed anchors, meaningful bends and obstacles can require shorter edges. |
| Bend tolerance | 1 px | Allowed plan-view chord deviation from the shaped route. Reduce to retain sharper detail; increase carefully to avoid unnecessary vertices. |

These are starting defaults, not calibrated accuracy settings. Add an anchor
before making large parameter changes. Treat a slope-break preview especially
carefully where both crest and toe fit inside the corridor.

Presets provide starting points for **Balanced**, **Levee / embankment**,
**Fine ditch / crest**, **Broad channel**, and **Noisy terrain**. They change the six trace controls;
they do not classify the terrain or guarantee a better route.

Start with output spacing of **5–10 terrain cells**, as requested for this
workflow: 5–10 feet on the supplied native one-foot tiles. The default is 8.
This is a practical starting preference, not a universal rule or an accuracy
claim. Larger reduced working cells imply larger physical spacing. Inspect the
actual **minimum, median and maximum spacing** shown with the line's metrics;
the target is not a strict minimum. Short-edge exceptions preserve fixed
anchors, real bends and obstacle safety rather than silently moving guides or
bridging NoData.

Terrain smoothing changes the guidance surface; line smoothing changes the
assisted XY geometry; target spacing controls output sampling. All user guides
remain fixed, manual lines retain their chosen corners, and final Z samples
still come from the original DEM. Existing projects retain their saved
parameters. Older lines without a line-smoothing setting reopen with that
setting at zero; choose a current preset to opt into the new defaults.

For a levee, choose **Breakline → Ridge / embankment crest**, then the
**Levee / embankment** preset. Place guides on the intended crown, including
changes in direction. Review local dips and sharp anomalies before accepting;
a smooth-looking crest must still follow the feature you intend. A crest and
a bank toe are different tracing objectives.

Exported line vertices and hydraulic mesh points are separate. HEC-RAS's
**Near Spacing** controls computation points around a breakline; it is not
this editor's target vertex spacing. See the
[USACE documentation](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/latest/geometry-data/2d-flow-areas).

## Review and editing

The feature list controls visibility, selection, and which lines are exported.
Double-click a name to rename a feature. Delete unwanted lines. Undo/redo applies to accepted editing
operations. During anchor placement, Backspace removes the last anchor and
Escape clears the current draft. Previewing is separate from accepting so a
poor candidate can be discarded without changing saved features.

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
Choose a full or custom elevation range, another palette, multidirectional
illumination, or display-only contours. Contour intervals use source Z units;
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
Projects are versioned JSON, not executable files.
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
