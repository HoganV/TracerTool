# Line quality review: smooth feature geometry and useful spacing

This document records the original 0.2.0 smoothing comparison and the later
0.2.2 feedback revision, completed 2026-10-16. The 0.2.0 preference for
5–10-cell output spacing and smoothing is historical. Current defaults and
new acceptance evidence are described first; the earlier case comparisons
remain below so their scope is explicit.

## Later feedback: 0.2.2

The 2026-10-15 user review found the earlier smoothing and search defaults
unhelpful on some traces. The current defaults therefore use terrain smoothing
0, line smoothing 0, search radius 12 cells, target spacing 3 cells and bend
tolerance 0.75 cells. Smoothing remains an opt-in advanced option. Ordinary
rough guides can move; exact snapped connections and correction boundaries
remain fixed. Terrain-response scale and output spacing no longer grow with
search radius. This section supersedes the default recommendations and
all-guides-fixed description in the historical 0.2.0 comparison below.

Generated curved valleys, ridges and bank breaks with guides displaced by
eight cells were checked at one-foot and 30-metre horizontal resolutions.
Current defaults achieve mean feature error below 0.5 cells and maximum error
at most 1.1 cells in those cases. Tests also cover flat/pit ambiguity, protected
connections, NoData and wide-radius searches with 3-cell target spacing. These
synthetic bounds do not establish positional accuracy on real terrain.

Native Linux interaction checks included a coarser geographic USGS raster
through an explicitly projected copy and its disclosed approximately
47.4422-metre working grid. A 500-cell search with 3-cell spacing produced 136
vertices along 19,036.8 metres, with measured median spacing 142.0 metres and
range 131.5–142.0 metres. This case illustrates independent search and output
spacing; it is not an accuracy comparison against ground truth.

The public synthetic demo intentionally retains explicit historical smoothing
parameters so that it still demonstrates that optional behavior. It is not a
new-default benchmark. The earlier favorable examples are retained as
case-specific evidence, not proof that their settings suit every dataset. Current guidance is in the
[USER_GUIDE.md](USER_GUIDE.md), and current verification is recorded separately
in [VALIDATION.md](VALIDATION.md).

## Historical 0.2.0 failure and research rationale

The initial output stage limits maximum edge length but retains raw raster-path
bends. Increasing its spacing parameter alone cannot remove the many short
zigzag edges. Terrain smoothing, line-shape regularization and final vertex
spacing are separate operations and need separate controls and checks.

First-order geodesic costs do not explicitly penalize turning. Chen, Mirebeau
and Cohen add orientation and curvature to the path state, using an elastica
energy to favor smooth paths while retaining feature attraction. Their image
experiments support investigating directional regularization; they are not a
DEM-levee validation. A full orientation-lifted solver is a larger change than
bounded postprocessing of the current route. [Primary paper](https://arxiv.org/html/1612.00343)

Jing, Zhang and Zhou describe neighbor-based smoothing of extracted ridge/
valley lines and graph-based removal of noise on 3D meshes. This supports
separating feature detection from line cleanup, while the mesh setting limits
direct transfer of their method to this DEM editor. [Author-hosted paper](https://www.wict.pku.edu.cn/GraphicsLab/docs/20200427021436620272.pdf)

## Recommendations used for the 0.2.0 revision

1. Retain a dense terrain route as evidence, then regularize its XY shape within
   a narrow lateral trust band. Fix user anchors and correction boundaries.
   Prefer a bounded smoothing fit or cross-section optimization with a turning
   penalty; an unconstrained spline can cut corners or leave a levee crest.
2. Use a local feature response to constrain the fit. At coarse longitudinal
   stations, sample across the provisional tangent, seek the intended crest/
   valley response, and regularize the sequence of lateral offsets. On a flat
   levee crown, use the center of the high plateau with opposite downslope
   flanks; chasing the highest noisy pixel can make a worse engineering line.
3. Sample the accepted smooth shape afresh by arc length. Do not reinsert every
   raster corner. Start at 5–10 cells as requested, preserving deliberate hard
   turns and protected anchors. Distribute spacing across each anchor span so
   the final interval does not become a tiny leftover edge.
4. Validate every final chord for NoData, corridor/feature adherence, loops and
   excessive displacement. If protected points are closer than the requested
   minimum, retain them and report the exception. Never conceal it by labeling
   the control as a strict minimum when the output violates it.
5. Sample source Z only after the final XY shape is accepted. Keep vertical
   smoothing separate and off by default; clean plan geometry is not permission
   to change the source elevations or erase real crest lows.

These are engineering recommendations inferred from the sources and observed
failure mode, not copied algorithms or established optimal parameter values.

## Historical 0.2.0 implementation and observed results

The engine now uses bounded Gaussian XY smoothing along arc-length stations,
then soft cross-profile recentering against local terrain cost. A displacement
band, cost allowance and NoData tests limit movement. It resamples the shaped
route afresh rather than retaining every raw raster corner. Final chord tests
retain detail needed by bend tolerance or obstacles. User guides and segment
correction boundaries remain hard constraints. This implements the practical
refinement route above, not the full Finsler/elastica optimizer.

The defaults are terrain smoothing **2 cells**, line smoothing **4 cells**,
target arc spacing **8 cells**, and bend tolerance **1 cell**. A dedicated
**Levee / embankment** preset uses these values with a 25-cell search radius.
Manual lines keep their chosen corners. Output Z is sampled from the original
DEM after final XY placement; no vertical smoothing is applied. Short-edge
exceptions remain possible around guides, real bends and obstacles, and the
UI reports minimum/median/maximum spacing rather than promising a strict
minimum everywhere.

The integrator compared the old committed implementation and revised output
using identical guides on two supplied one-foot tiles. The overview and zoomed
comparison were visually inspected with output vertices shown. Local evidence:
`artifacts/quality/levee-comparison.png` and `artifacts/quality/metrics.json`.

| Case | Tile | Vertices, old → new | Median spacing, old → new | Revised minimum–maximum spacing | Revised edges ≥5 cells |
|---|---|---:|---:|---:|---:|
| Straight levee | `private tile 3` | 620 → 203 | 2.83 → 7.97 | 7.66–7.98 | 100% |
| Curved levee | `private tile 5` | 580 → 174 | 2.50 → 7.88 | 7.59–7.97 | 100% |

Distances in this table are cells and also feet for these native-resolution
inputs. Maximum successive-edge turning angles fell from 46.97° to 10.13° and
45.00° to 14.06° respectively. These observations support reduced staircase
noise and useful spacing on the two reviewed cases; they do not establish
surveyed crest accuracy or universal minimum spacing.

The first six focused quality tests passed: flat-crowned oblique levee, curved
levee, bank slope break, meaningful anomaly/bend, NoData/fixed corner, and
fresh station spacing. Broader integration and stream regression results are
recorded separately in [VALIDATION.md](VALIDATION.md).

The revised saved stream on `private tile 6` was also compared visually with the
previous implementation using the same guides. Vertex count fell from 696 to
205; spacing was 7.93 cells median, 2.43 minimum and 7.97 maximum. One short
edge exception remained, illustrating why target spacing is not a strict
minimum. The engine's checks confirmed exact source-Z sampling and NoData-safe
segments. Local evidence is `artifacts/quality/stream-comparison.png` and
`artifacts/quality/stream-metrics.json`. The profile still reports uphill
segments, so this remains a reviewed geometric trace rather than an enforced
hydraulic flow path. The final engine-focused suite passed 59 tests.

## Levee-specific evidence

Sasaki et al. examine levee detection from high-resolution DEMs in the Kinu
basin. Their follow-up combines relative elevation, slope, aspect difference
and curvature. This favors a cross-sectional levee shape test over treating
every local high point as a levee. Their regional 5–10 m study resolutions and
reported errors should not be transplanted into the supplied one-foot terrain.
[2023 study](https://www.jstage.jst.go.jp/article/hrl/17/1/17_9/_article),
[2024 follow-up](https://www.jstage.jst.go.jp/article/jscejj/80/16/80_23-16130/_article/-char/en)

Mitasova et al. extract coastal dune crests with an elevation-dependent
least-cost path between endpoints. Their dune-toe construction uses a different
cost surface derived from departure from a reference sheet. The useful design
lesson is to distinguish crest and toe objectives and keep continuity in the
optimization; absolute elevation alone is a poor default where regional relief
dominates a narrow levee. [Primary proceedings paper](https://www.geomorphometry.org/uploads/pdf/pdf2011/Mitasova2011geomorphometry.pdf)

## Downstream mesh constraints

HEC-RAS uses breaklines to align cell faces and has separate near/far spacing
properties governing mesh computation points. Therefore exported line-vertex
spacing and hydraulic mesh spacing must not be presented as the same control.
The user's 5–10-cell preference is a geometry/workflow constraint, not a
universal HEC-RAS rule. [USACE documentation](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/latest/geometry-data/2d-flow-areas)

## Acceptance criteria used for the 0.2.0 cycle

- Oblique straight ridge/valley: no repeated one-pixel stair steps in the output.
- Curved synthetic crest and flat-topped levee: bound centerline error while
  reducing turning noise; include asymmetric flanks and isolated height spikes.
- Real levee/embankment, broad channel and sharp bend on supplied TIFFs: compare
  old/new geometry at the same anchors and map scale with vertex markers shown.
- Record vertex count, minimum/median/maximum edge length, protected-spacing
  exceptions, turning-angle variation, maximum lateral deviation, source-Z
  agreement and NoData safety. Fewer vertices alone is insufficient evidence.
- Preserve deliberate corners, exact user guides/correction boundaries, project
  round trips, undo/redo and manual edits. Existing projects retain their saved
  parameters; new defaults must not silently reinterpret accepted old geometry.
- Rebuild and rerun Windows/Linux frozen and desktop checks only after geometry
  review accepts the new snapshot. Retain the interim package checks as build
  infrastructure evidence, not proof that the rejected line quality was good.
