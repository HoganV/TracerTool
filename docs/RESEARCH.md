# Terrain tracing: evidence and implementation decisions

Research reviewed 2026-10-14; implementation decisions revised 2026-10-16.
These sources inform the design; TracerTool is not an implementation of every
method listed below. The v0.2 goal is to reduce clicking while a person supplies
the feature's identity and reviews the line.

The first user review requested smoother levee/breakline geometry and
5–10-cell starting output spacing. A later review found that broad search and
smoothing defaults made practical results worse, and that rough guides should
be movable. The 0.2.2 decisions below supersede those initial defaults. The
historical comparisons and primary sources remain in
[LINE_QUALITY_REVIEW.md](LINE_QUALITY_REVIEW.md); neither visual comparison nor
synthetic testing establishes accuracy against surveyed ground truth.

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

## Current implementation and its baseline

Two or more guides describe the intended line. Search a corridor around their
connecting segments; ordinary assisted guides may relax toward the terrain,
while snapped connections and segment-correction boundaries remain fixed.
Construct a terrain preference from local shape with optional smoothing: low/concave terrain for streams, high/convex terrain for
ridges, and changes in slope for slope breaks. Combine that preference with a
positive travel cost and guidance toward the intended corridor. The shortest
accumulated-cost path supplies candidate cells. Invalid cells are barriers.

This is an engineering inference from the literature: human anchors address
semantic ambiguity cheaply, while the cost solver removes hundreds of manual
vertices. It is a stronger first product than a fully automatic network when
the available inputs contain no labeled reference lines. A single tile-wide
minimum/maximum elevation score would favor regional elevation trends; local
shape is the more appropriate starting signal.

In the route cost, optional Gaussian smoothing is followed by a broader
Gaussian residual (local terrain position) and the sign of the Laplacian.
Streams and ridges also use small cross-profile slope, measured normal to the
anchor chord, to favor a centerline. Streams derive this centering signal from
broader relief, reducing attraction
to concave shoreline toes on flat water. Since 0.2.2 this feature scale is
independent of search radius, so widening a corridor no longer blurs away a
narrow channel merely because the rough guide is far from it. Ridges use a
finer relief scale; signed local relief gates both so a flat neighboring field
does not win
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

Output shaping and spacing are measured in working pixels. Assisted paths can
optionally receive bounded Gaussian XY smoothing at arc-length stations and soft
cross-profile recentering against the local terrain cost. Candidate movement is
restricted by a displacement band, cost allowance and exact NoData checks.
This is bounded route refinement, not an implementation of the full
orientation-lifted curvature solver in the cited research. Smoothing defaults
to zero. Rough guide relaxation is a separate operation from line smoothing;
protected connections and correction boundaries remain fixed.

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

The original reference rasters have one-foot horizontal cells and foot
elevations; the additional lower-resolution USGS raster makes assuming that
all inputs share those units or resolution inappropriate. The conservative
0.2.2 defaults use 12 working cells of search radius, 3 cells of target spacing,
0.75 cells of bend tolerance, attraction 8, and zero for both smoothing stages.
Physical sizes derive from the loaded working grid. For example, a 10-metre
grid gives a 120-metre radius and 30-metre spacing; this conversion does not
establish corresponding positional accuracy. Units and vertical datum remain
those of the source.

These are engineering starting values responding to user-observed failures,
not literature-derived universal optima. Search radius controls where a route
may be found; terrain-feature scale controls the response used to find it;
spacing controls output samples. They must not silently substitute for one
another. There is no arbitrary maximum corridor radius, although a larger
search consumes more processing resources and can contain competing features.
The reported output spacing includes short-edge exceptions for bends,
protected nodes and NoData barriers.

Ordinary guide points now express approximate intent rather than exact
constraints. Assisted guides can move laterally across the local guide
direction toward terrain evidence within the original corridor, and output
sampling spans unfixed guides rather than restarting at every rough point.
The relaxation option is on for new drafts; snapped feature connections and
correction boundaries are protected. A flat or ambiguous cross-section does
not justify moving a rough guide merely to chase an isolated pit or an
unlocated slope response. Native wide-search inspection also found a short
shoulder bump could win at an endpoint despite a continuous crest nearby.
Guide candidates now use evidence along the local guide direction, up to
eight cells on either side and limited to one quarter of the nearest guide
separation. Averaging this support favors a continuing feature over isolated
curvature peaks while keeping the support scale independent of search radius.
Near a raster edge, available one-sided support is used. A NoData gap or
diagonal corner touch stops the support, so disconnected samples cannot affect
that guide's score.
It is a local heuristic, not a complete longitudinal landform classifier. Legacy projects without
that option keep fixed-guide behavior when explicitly retraced. Loading a
project never reruns the solver or moves accepted geometry. Project schema 1
retains optional relaxation and fixed-guide indices with strict validation.

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

## Evidence for the 0.2.2 defaults

The feedback regression cases use generated curved valleys, ridges and bank
slope breaks at one-foot and 30-metre cell sizes. With guides offset by eight
cells, the defaults produce mean feature error below 0.5 cells and maximum
error at most 1.1 cells while preserving source Z and NoData constraints.
Wide-radius tests keep 3-cell output spacing; flat and isolated-pit cases check
that ambiguity does not spuriously relocate guides. This is deterministic
synthetic evidence for the implemented behavior, not a universal accuracy bound.
Eighteen further cases put one-, two- and three-cell-long shoulder bumps/pits
beside a continuous ridge/channel at the first, middle or last guide. The
continuity correction reduced the motivating synthetic maximum deviation from
45 cells to zero and visually removed an off-crest endpoint tail in a native
48-cell-radius ridge preview. Those sampled heights and geometry measurements
are case-specific; no independent survey established the crest location.

Native Linux computer-control exercises used fine projected terrain and a
separate projected copy of the coarser geographic USGS source. Its displayed
working grid was approximately 47.4422 metres, so the 3-cell target represented
about 142.3 metres. A 500-cell search retained approximately 142-metre median
output spacing. The source was not modified. Detailed suite counts, workflow
measurements and remaining acceptance gates are in [VALIDATION.md](VALIDATION.md).
No independent labeled real-terrain geometry was available, so real feature
accuracy and time saved remain unmeasured.

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
separately. Synthetic tests demonstrate invariants and numerical behavior; visually
plausible traces on reference TIFFs do not establish real-world accuracy.
Only promote a new default after holdout results improve without degrading the
data-integrity checks.
