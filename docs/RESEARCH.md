# Terrain tracing: evidence and implementation decisions

Research reviewed 2026-10-14. These sources inform the design; TracerTool is not
an implementation of every method listed below. The initial and v0.2 goal is to reduce
clicking while a person supplies the feature's identity and reviews the line.

The subsequent user review requested smoother levee/breakline geometry and
5–10-cell starting output spacing. The design update and additional primary
sources are in [LINE_QUALITY_REVIEW.md](LINE_QUALITY_REVIEW.md); the original
route cost remains the baseline while the output shaping and defaults below
reflect the accepted quality revision.

## What the tools mean

A stream centerline follows a terrain valley or channel thalweg. A ridge
breakline follows a local crest. A slope break follows a transition in surface
gradient, such as the crest or toe of a bank. These are different objectives:
following high ground alone will not locate every topographic breakline.
Hydro-enforced banks, surveyed hard breaklines, and water-surface edges require
additional semantics and evidence that a bare-earth raster may not contain.

## Primary sources and decisions

| Source | What it contributes | Decision for TracerTool |
|---|---|---|
| [Passalacqua et al. (2010), GeoNet](https://doi.org/10.1029/2009JF001254) | Combines nonlinear diffusion, contributing area, contour curvature, and geodesic paths for channel extraction from high-resolution terrain. | Adopt the concept of a terrain-dependent path cost. Begin with user-constrained paths. Full GeoNet conditioning, accumulation, and network extraction remain future work. |
| [Tarboton (1997), D-infinity](https://hydrology.usu.edu/dtarb/96wr03137.pdf) | Computes a continuous downslope angle on triangular facets and apportions upslope area to two neighbors, addressing limitations of eight-direction routing. | Evaluate D-infinity as a future accumulation signal; do not label current valley tracing D-infinity. A continuous flow angle alone does not resolve which feature a person intends. |
| [TauDEM, D8 flow directions](https://hydrology.usu.edu/taudem/taudem5/help/d8flowdirections.html) | Steepest descent to one of eight neighbors; flats and pits need explicit handling. | Useful simple downstream baseline. It can stall in pits and flats and can follow a side channel; it is not sufficient as the primary two-anchor editor. |
| [Barnes, Lehman & Mulla (2014), Priority-Flood](https://rbarnes.org/sci/2014_depressions.pdf) | Efficient depression filling and watershed labeling using an inward flood from boundary cells. | Add opt-in hydrologic conditioning in a later phase, with fill-depth diagnostics and separate source/conditioned surfaces. Real depressions should not be silently removed or reflected in exported elevations. |
| [Steger (1998), curvilinear structure detection](https://doi.org/10.1109/34.659930) | An explicit line-profile model and scale-space analysis address localization bias in asymmetric lines and estimate position/width. | Supports evaluating multiscale directional curvature and subpixel localization later. Current raster tracing makes no subpixel accuracy claim and does not implement Steger's detector. |
| [Even & Ngo (2020), live curvilinear extraction](https://doi.org/10.5194/isprs-annals-V-2-2020-211-2020) | Demonstrates supervised, responsive extraction of roads and ridges directly from classified LiDAR points. | Supports the interaction choice: the user indicates the intended feature and the tool does repetitive tracing. Their raw-point algorithm is not directly applicable to the supplied TIFFs. |
| [scikit-image, minimum-cost paths](https://scikit-image.org/docs/stable/api/skimage.graph.html) | Provides grid minimum-cost routing, including geometric step lengths. | Reuse a maintained solver; keep cost construction and coordinate conversion in independently tested modules. |

## Chosen first implementation

Two or more anchors describe the intended line. Between adjacent anchors, search
a corridor around their connecting segment. Construct a terrain preference from
smoothed local shape: low/concave terrain for streams, high/convex terrain for
ridges, and changes in slope for slope breaks. Combine that preference with a
positive travel cost and guidance toward the intended corridor. The shortest
accumulated-cost path supplies candidate cells. Invalid cells are barriers.

This is an engineering inference from the literature: human anchors address
semantic ambiguity cheaply, while the cost solver removes hundreds of manual
vertices. It is a stronger first product than a fully automatic network when
the available inputs contain no labeled reference lines. A single tile-wide
minimum/maximum elevation score would favor regional elevation trends; local
shape is the more appropriate starting signal.

In the actual v0.2 cost (retained from the first release), Gaussian smoothing is followed by a broader Gaussian
residual (local terrain position) and the sign of the Laplacian. Streams and
ridges also use small cross-profile slope, measured normal to the anchor
chord, to favor a centerline. Streams derive this centering signal from broader
relief at a scale of at least half the search radius, reducing attraction to
concave shoreline toes on flat water. Ridges use the finer terrain smoothing
scale; signed local relief gates both so a flat neighboring field does not win
merely because its cross-slope is zero. That term matters because an ideal parabolic
valley can have constant curvature and local-position residual away from its
edges. Slope-break mode uses the magnitude of the gradient of slope magnitude.
The cost is positive, with terrain weight controlling the preference and a
weak squared-distance guidance term. `MCP_Geometric` accounts for diagonal and
rectangular-cell travel distances; a four-neighbor fallback prevents diagonal
corner cutting around invalid terrain.

These are local heuristic signals, not full directional multiscale landform
classification. The editor does **not** reproduce GeoNet's nonlinear diffusion,
flow accumulation, or channel-head inference. Its slope-break mode is a
heuristic candidate generator, not a certified hard-breakline detector. An
anchor pair with a broad corridor can select a nearby competing feature.
Additional anchors or a narrower corridor express the intended route.

Output shaping and spacing are measured in working pixels. Assisted paths now
receive bounded Gaussian XY smoothing at arc-length stations and soft
cross-profile recentering against the local terrain cost. Candidate movement is
restricted by a displacement band, cost allowance and exact NoData checks.
This is bounded route refinement, not an implementation of the full
orientation-lifted curvature solver in the cited research. Guides remain fixed.

Fresh arc-length sampling no longer preserves every tiny raster-path corner.
The final chord checks reinsert necessary bends where the selected bend
tolerance or obstacle safety requires them. Shorter edges can remain around
hard guides, real bends and NoData; the UI reports actual spacing. Setting line
smoothing to zero retains the barrier-aware simplification route. Output elevations
are sampled from the nearest source DEM pixels, not interpolated display values.
Raster band scale/offset encoding is decoded before using elevations. For
non-square cells, the route cost uses map-distance edge lengths, but smoothing,
search radius, and spacing controls remain pixel-based and have different
physical extents along the two axes; the engine reports this limitation.
An optional engine-only D8 downhill walk stops at pits/flat areas or boundaries;
it does not fill depressions or provide the primary editor interaction.
Review longitudinal profile and
uphill portions; uphill segments in an anchor-guided stream are warnings to
inspect, not automatic proof that either the terrain or the trace is wrong.

## Scale and parameter rationale

The supplied rasters have one-foot horizontal cells and foot elevations. Start
with 2-cell terrain smoothing, a 30-cell search radius, 4-cell line smoothing,
8-cell target arc spacing and 1-cell bend tolerance. The user selected a
5–10-cell starting spacing range for this workflow; these are engineering
defaults, not literature-derived universal optima. On the supplied native
one-foot data, cell distances correspond to feet. At a different working
resolution the physical distances change. Neither interpolated XY coordinates
nor extra vertices establish subcell positional accuracy.

For later adaptive spacing, estimate plan curvature kappa and choose a step
that keeps chord deviation below an explicit tolerance epsilon, using the
small-angle relationship epsilon approximately kappa * step^2 / 8. Bound the
step by raster resolution and feature width, retain anchors and junctions, and
revalidate all resulting segments. This is a proposed extension, not current
behavior.

Version 0.2 adds explicit local and whole-line correction workflows around
this same solver. Correcting a segment retains its original boundary XYZ and
all geometry outside it. Hand edits sample source elevations for new/moved
points, validate the resulting segments against NoData, refresh diagnostics
and retain provenance. These controls make the heuristic useful in an editing
workflow without treating its first candidate as ground truth.

## How to decide whether an improved algorithm is better

Build a fixed benchmark of hand-reviewed lines across each tile: broad and
narrow channels, oblique ridges, bank crests/toes, shallow drainage, pits, and
roads/culverts. Record feature type, uncertainty, source resolution, and operator
intent. Separate development and holdout lines by geographic area. Compare
manual lines, straight-anchor baselines, current assisted paths, D8, and
conditioned/accumulation variants under the same anchor budget.

Measure median and 95th-percentile perpendicular error in cells and map units,
endpoint displacement, time and clicks to accepted output, NoData crossings,
junction gaps, profile reversals, and rework rate. Report ambiguous segments
separately. Synthetic tests prove invariants and numerical behavior; visually
plausible traces on the six supplied TIFFs do not establish real-world accuracy.
Only promote a new default after holdout results improve without degrading the
data-integrity checks.
