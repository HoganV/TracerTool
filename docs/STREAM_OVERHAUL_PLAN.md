# Stream tracing overhaul: evidence, data and implementation plan

Status: proposed architecture and delivery plan, not an implemented replacement.
Reviewed source: `5e411efe91a63589b643b99f8d19e22b41f60cc9` (0.2.2).
Review date: 2026-10-16.

## Recommendation

Replace stream-mode's local, guide-chord shortest path with **a drainage-aware,
multiscale candidate network plus constrained reach selection**. Keep the useful
editor, preview/apply, undo, local corrections, source-Z sampling and exports.
Do not spend another release adjusting the same handful of heuristic constants.
Do not make deep learning a prerequisite: first build a real paired-data benchmark,
compare deterministic approaches, and train a lightweight scoring model only if
it earns its place on geographically held-out data.

The normal workflow should be: open terrain, allow background preparation, click
an approximate upstream point and downstream destination, inspect the proposed
reach, accept. A single seed can follow downstream once outlet/edge behavior is
implemented. Extra clicks specify intent at genuinely ambiguous branches, not
compensate for an arbitrarily narrow search radius. Numerical controls move to
Advanced; ordinary users choose intent, not attraction/smoothing constants.

**This cannot promise zero review.** An absent culvert, real closed basin,
flat water surface or competing distributary may not be resolvable from the TIFF.
Return a localized uncertainty/stop condition rather than inventing certainty.

## 1. Scope of the review and checks performed

The review covered all 12 application Python modules (5,125 lines), all tracked
Python tests, scripts, configuration, CI and text documentation. UI/integration
and persistence/build files were reviewed in two disjoint read-only lanes;
terrain, tracing and their tests were reviewed directly. No private reference
raster was read, modified, uploaded or bundled. The documentation screenshot
was not used as algorithm evidence.

Actual execution in the repository's `.venv`:

- `QT_QPA_PLATFORM=offscreen pytest -q`: **457 passed in 46.94 s**.
- Additional synthetic characterization: a gently curving channel worked, a
  larger meander was missed with defaults, and flat terrain produced an
  unqualified stream candidate. Detailed results below.
- Downloaded and opened an actual small public GeoTIFF and matching stream
  vectors; verified CRS, pixel spacing, complete vector coverage and valid data.
- Ran current default tracing against all three downloaded stream features at
  both default display-grid and native pilot resolution. This is a preliminary
  discrepancy check, not validated accuracy or a trained model.

No application algorithm, project interpretation or dependencies were changed
for this plan. Existing passing tests establish existing behavior, not adequate
real-stream performance.

## 2. Why the present approach struggles

| Finding | Source evidence | Consequence |
|---|---|---|
| Stream cost is normalized local terrain position, Laplacian and cross-slope relative to a guide chord. | `src/tracertool/tracing.py:118–174` | A local valley response is not evidence of a connected draining channel; orientation changes along bends are not modeled locally. |
| Every guide pair gets its own positive-cost shortest path inside a hard chord corridor. | `tracing.py:510–561,663–673` | A real meander outside the corridor is impossible; positive travel cost favors shortcuts when terrain evidence is insufficient. More guides/radius changes become the user's responsibility. |
| Guide relaxation is local cross-section selection with short longitudinal support, not joint reach/network optimization. | `tracing.py:432–507` | It cannot resolve arbitrary branch choices or recover a complete meander by itself. |
| No contributing area, conditioned routing surface, outlet graph or reach topology exists in primary stream routing. | `tracing.py:118–174,510–561` | Low spots, tributaries, flats, crossings and true outlets cannot be distinguished reliably with the present inputs to the solver. |
| Optional D8 is a separate engine-only downhill walk that stops at pits/flats. | `tracing.py:710–755`; `app.py:1078–1094` | It is neither the primary stream tool nor a ready replacement. |
| Analysis uses the bounded display/working raster. | `terrain.py:70–113`; `app.py:616–628` | Enlarging the file can erase narrow channels and change physical defaults; zoom does not restore routing detail. |
| `default_params` validates terrain/kind but always returns the same constants. | `tracing.py:32–44` | Defaults are cell-relative, not adaptive to channel width, noise, relief or drainage structure. |
| The UI tells users to widen search; presets are fixed numeric bundles. | `app.py:243–293,931–937`; `desktop_actions.py:420–433` | The current workflow externalizes model selection to the operator. |
| Flat/ambiguous routes lack a dedicated ambiguity result; uphill is largely a global post-hoc warning. | `tracing.py:564–599`; `app.py:1118–1134` | Plausible geometry can appear more trustworthy than the evidence supports. |
| Snapping fixes coordinates but does not create persistent network-node identities. | `desktop_actions.py:86–107`; `app.py:1006–1010` | Moving one line can disconnect a nominal junction on another. |
| Engine identity and derived evidence are not feature-level durable records; edits replace metrics and filter warning text. | `project.py:220–243`; `editing.py:87–122,143–155,269–275` | New confidence/conditioning diagnostics would be lost or become stale unless their lifecycle is redesigned. |
| Existing benchmark uses arbitrary proportional anchors and measures timing, not reference error. | `scripts/benchmark.py:24–51` | Hundreds of green tests do not tell us which default finds actual streams. |

### Executed synthetic probe

Generated a 240 × 220, 1 m projected raster with a Gaussian channel depression,
4-cell width parameter, 35-cell sinusoidal meander amplitude and 0.02 source-Z
units of longitudinal decline per row. Used only two end guides and otherwise
unchanged defaults. Reported deviation is **column error against the generating
curve**, not perpendicular ground-truth error or survey accuracy.

| Search radius | Mean column error | 95th percentile | Maximum |
|---|---:|---:|---:|
| Default 12 cells | 10.37 cells | 22.75 cells | 22.96 cells |
| 45 cells | 0.68 cells | 1.98 cells | 2.41 cells |
| 90 cells | 0.74 cells | 2.10 cells | 2.37 cells |

A flat 80 × 80 raster returned a 21-vertex stream with **no warnings**, despite
containing no channel evidence. This is an uncertainty-reporting failure for the
proposed product, not a crash in the current guided cartographic tool.

These probes isolate limitations, not the exact cause of every user-observed
real-terrain failure. Widening the radius fixes this generated case but is not
the proposed overhaul; a wider corridor can also admit competing valleys.

## 3. Public paired data: found and partly exercised

Reference data should have explicit roles: **derived training labels**, **independent
cartographic checks**, and **reviewed acceptance labels**. Do not call them all
truth. A mapped stream centerline, a water-surface centerline, a DEM flow path and
a bed thalweg are different targets. Hydro-flattened topographic DEMs are not the
same thing as hydro-enforced/conditioned hydrologic surfaces.[5]

### A. Minnesota: real small pilot already downloaded

Use the unsmoothed layer 1 of Minnesota DNR's lidar-derived hydrography service.
Its metadata describes 2011 lidar, hydrologic modification including culvert
breaching, accumulation-based extraction and visual/manual QA. These are useful
reference labels, **not independently surveyed thalwegs**.[7]

- Vector service: `https://enterprise.gisdata.mn.gov/aghost/rest/services/us_mn_state_dnr/water_dnr_hydrography_from_lidar/FeatureServer/1`
- Query rectangle, WGS84: `-91.260,47.424,-91.254,47.429`.
- Actual returned feature IDs: **7672, 7767, 7829**; no transfer-limit truncation.
- Vector output: EPSG:26915. Full geometry bounds:
  `631173.5,5252668.5,632597.5,5254166.5`.
- DEM service: `https://enterprise.gisdata.mn.gov/agsimg/rest/services/MnTopo/2nd_Generation_Seamless_Lidar_DEM/ImageServer`.
- Exported rectangle: `631000,5252000,633000,5254500`, EPSG:26915,
  **2,000 × 2,500 Float32 pixels at 1 m**; all **5,000,000 cells valid**.
- Actual TIFF bytes: **20,975,257**. All returned vector geometry lies inside.
- Elevation range read from the TIFF: **388.5400–474.8000** in decoded stored Z.
  Band units were absent; retain external metadata rather than silently assigning
  a unit. Source program documentation describes the second-generation lidar.[8]

**Important mismatch:** the service reports newer 2021–2023 terrain, while these
stream labels derive from 2011 lidar. This is a cross-vintage integration and
robustness pilot, not acquisition-matched training truth. Minnesota license
metadata points to DNR's geographic-data agreement; retain it and review terms
before redistributing anything.[13]

Reproducible requests, vector attributes, raster hash and read-back details are
in `artifacts/stream-overhaul/public-pilot/verification.json`. Downloaded data and
probes are ignored local artifacts, not public source or release contents.

Current **native 1 m** default two-endpoint traces produced these exploratory
prediction-to-reference discrepancies:

| Public feature | Median distance | 95th percentile distance |
|---|---:|---:|
| 7672 | 2.49 m | 7.88 m |
| 7767 | 6.60 m | 21.02 m |
| 7829 | 119.18 m | 260.70 m |

Distances are from output vertices to a reference line densified at approximately
1 m spacing, using nearest sampled points. They are not exact continuous-line
metrics; endpoint-only intent, reference vintage and reference validity have not
been independently reviewed. All three produced uphill warnings. Changing only
the pilot analysis grid from default 1.04167 m to native 1 m did not resolve the
large discrepancy on feature 7829. Do not extrapolate three reaches to general
accuracy. Raw results for both resolutions are in `public-pilot/baseline.json`.

### B. Massachusetts: independently sourced regional check

MassDEP hydrography includes older map/orthophoto production and field-verified
Wachusett streams; source and resolution attributes allow better lineage
filtering. Its cartographic origin is distinct from newer lidar, but individual
features can have mixed lineage and variable precision.[9]

- Pilot WGS84 rectangle: `-71.85,42.395,-71.84,42.405`.
- Service: `https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/1_25_000_USGS_MassDEP_Hydrography/FeatureServer/0`.
- Filter `ARC_CODE IN (4,5)`, not shoreline/dam/closure arcs; request EPSG:26986.
  Research query returned 18 features, with LOCAL and DEP/DCR source values.
- Matching 1 m USGS tile identified:
  `https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/MA_CentralEastern_2021_B21/TIFF/USGS_1M_19_x26y470_MA_CentralEastern_2021_B21.tif`.
  It covers the query AOI; listed size is about 345 MB. Metadata/availability was
  checked, not the full TIFF downloaded. MassGIS also provides lidar access.[10]

Use this for independent-source network/centerline checks with documented
uncertainty, not a demand for metre-level agreement with historical mapping.
Review small reaches against imagery and terrain; field checks remain stronger.

### C. Sonoma County: promising acquisition-matched training corpus

The producer describes 2013-lidar stream centerlines/confluences, hydroenforcement
locations, 1 m enforced DEM and flow products, with a stream criterion combining
more than five acres accumulation and a clearly defined channel. It also warns
against engineering/fine-scale use without validation.[11]

Acquire the original bare-earth raster, matching vectors and enforcement records
as separate inputs. **Never score against labels burned into the same evaluation
DEM.** Do not substitute the program's newer 2022 terrain without labeling the
vintage change. Metadata/download inventory was researched; individual watershed
TIFF/vector packages have not yet been downloaded/read back here.[11]

### D. USGS 3DHP/3DEP: expand after the pilot

3DHP provides services and downloadable snapshots, with new elevation-derived
hydrography added to a dataset that also includes legacy hydrography.[4]
The inspected service exposes flowlines (50), EDH workunits (90), elevation
provenance (92) and DEM limitations (94); use those records to identify actual
source elevation rather than pairing arbitrary nearby files.[12]

Use AOI queries, not a national archive. Separate EDH from inherited NHD, exclude
artificial waterbody paths from physical-channel localization labels, and retain
label lineage. USGS one-metre DEM collection metadata describes lidar source,
project coverage and public-domain status.[6] Geographic match is necessary but
not sufficient: acquisition, conditioning and label target must also match.

## 4. Proposed engine architecture

### 4.1 Separate source, analysis, display and sampled elevations

Introduce a raster-source/window abstraction and an explicit `AnalysisGrid`.
Display overviews remain bounded; analysis operates on native-resolution windows
or explicitly disclosed analysis levels. Return map-space coordinates and grid
transforms rather than assuming trace cells are canvas cells.

Keep four distinct products:

1. Immutable decoded source raster, mask and metadata.
2. Display pyramids, with no role in setting analysis accuracy.
3. Derived analysis/conditioning surfaces and masks, fully versioned.
4. Output XYZ, whose Z is always sampled from the source, never a filled/breached
   analysis surface or display exaggeration.

All distances/derivative scales need physical XY units and anisotropic-cell
handling. Known unit conversions can be used in derived analysis while preserving
source values; unknown vertical units must not silently become metres. Preserve
NoData barriers throughout, including final simplified chords.

**Hydrology cannot be made correct by independent small tiles alone.** Accumulation
needs upstream context. Use a sufficiently large connected domain/mosaic or
explicit inflow boundary information; flag clipped/unknown contributing area.
An ordinary derivative halo is not sufficient for catchment accumulation.

### 4.2 Build drainage evidence once, not per guide segment

Prepare a cacheable, bounded analysis domain with:

- noise/quantization estimates and multiscale directional valley/channel response;
- inferred local tangent and width/scale response, not a fixed guide-chord normal;
- depression depth/spill diagnostics and stable flat handling;
- flow direction and contributing area, in physical area units;
- boundary/NoData/cropped-catchment uncertainty masks;
- candidate channel segments and junctions at multiple evidence levels.

Benchmark raw/flat-resolved D8 first as a transparent baseline, then D-infinity
or multiple-flow accumulation for evidence if they improve holdouts. Do not
pretend accumulation alone identifies channels; drainage area thresholds vary
and a runoff path need not be an incised stream.

Compare edge-preserving filtering and multiscale curvature/accumulation ideas
inspired by GeoNet. GeoNet explicitly combines filtering, flow accumulation,
curvature and geodesic selection, and still exposes a contributing-area cleanup
parameter—not a universal parameter-free solution.[1] Its public implementation
has additional runtime dependencies and GPL-3.0 licensing; use it as a research
comparator, not copied MIT application code without a licensing decision.[2]

### 4.3 Conditioning: conservative, explicit and inspectable

Create an analysis-only raw-versus-conditioned comparison. Resolve numerical
flats without silently forcing every real depression to drain. Evaluate bounded
breaching/filling candidates with changed-area/depth/length diagnostics and
source-unit-aware limits. Least-cost breaching is an established alternative to
filling, but it too has distance/cost controls and can create inappropriate cuts
through real terrain.[3]

For normal Auto mode, numerical artifact handling must follow a documented
policy. Material fill/breach or inferred crossing requires visible disclosure and
confirmation, or leaves the reach unresolved. Without known vertical units,
physical-depth limits require metadata/user confirmation, not a guessed scale.
Known culvert/road information is optional evidence, not a fabricated tunnel.
NoData stays impassable; external tools' missing-data interpolation defaults must
not leak into this policy. No universal global fill or stream burning by default.

### 4.4 Select a connected reach, then refine geometry

1. Snap approximate user seeds to several plausible candidate reaches using
   evidence, direction and intent; keep protected vector connections exact.
2. Solve across the candidate graph/domain using channel likelihood,
   connectivity, drainage evidence, local orientation and bounded shape cost.
3. Treat normal guides as soft observations of one reach, optimized jointly;
   keep explicit fixed nodes and correction endpoints hard constraints.
4. Expand the search adaptively when evidence reaches the domain edge or no
   credible connected route exists, subject to explicit memory/time limits.
   Do not endlessly broaden until any route can be returned.
5. Offer meaningfully different branch alternatives where scores are close.
   Prefer one branch-choice click to seven numerical adjustments.
6. Refine the chosen geometry locally at analysis resolution, constrain it to
   channel evidence and preserve junctions. Shape smoothing must not shortcut
   meanders, go through banks or cross NoData.
7. Sample final source Z and recompute profile/geometry QA separately from
   analysis-surface drainage diagnostics. Raw sampled Z need not be perfectly
   monotonic even when the analysis route drains.

Separate hydro-flattened wide-water centerlines from incised-channel/thalweg
claims; evaluate waterbody masks/centerline handling as an explicit case.
Start/end reach selection is the first product. Whole-network extraction,
channel-head inference and distributary handling are later gates, not assumed
consequences of a new solver.

### 4.5 Automatic settings and honest confidence

Auto mode selects evidence scales, search/domain expansion and output detail
using observed terrain and development-set calibration. It records resolved
values for reproducibility. Search extent, feature scale and output spacing
remain independent. A fixed universal accumulation threshold is not Auto.

Return structured diagnostics with map geometry: weak channel evidence,
competing branch, pit/closed basin, inferred crossing, clipped upstream area,
source change, unsupported units and unresolved flat/waterbody. Confidence starts
as a relative evidence/ambiguity score; only call it a probability after held-out
calibration supports that interpretation. Evaluate coverage versus error when
abstaining, so a method cannot win merely by refusing hard cases.

## 5. Reference/training strategy

1. **Freeze the current baseline first.** Each case specifies source identity,
   label role/uncertainty, acquisition lineage, start/end intent, permissible
   guides, conditioning policy and expected junctions.
2. Initial proposed corpus: 12 catchments across at least four contrasting
   settings, about 20 reviewed reaches each. Reserve catchments for development,
   validation and blind acceptance before tuning; final counts depend on usable
   licensing and label review, not download volume. Keep the current three-line
   pilot in development permanently.
3. Include steep headwaters, broad/shallow meanders, agricultural ditches, road
   crossings, confluences, wetlands, waterbodies, closed basins, DEM seams and
   cropped outlets. Unmapped headwaters are unknown, not automatic negatives.
4. Compare straight guides, current defaults, current development-tuned defaults,
   conditioned D8, and multiscale drainage/geodesic candidates at the **same
   guide budget**. Hand-tuned per-case results are oracle diagnostics, not the
   primary product score.
5. Split by catchment/acquisition region, with buffers preventing adjacent-patch
   leakage. Keep DEM-derived-label tests separate from independent-source and
   manually adjudicated acceptance tests. Record where labels contributed to
   DEM enforcement; exclude that circular configuration from discovery claims.
6. First train only bounded parameter selection or a channel-likelihood ranker
   over terrain/flow features, if it beats the deterministic baseline. Add a
   neural segmentation model only after sufficient diverse labels and a verified
   CPU/offline packaging route exist. Local labels may be collected by explicit
   opt-in; no telemetry, uploads or automatic retraining.
7. Version model/configuration/data manifests and use non-executable artifacts.
   No untrusted pickle/joblib project or downloaded model deserialization.
   A model proposes likelihood; graph constraints and integrity checks still
   determine whether a route is admissible.

## 6. Integration contracts to agree before implementation

These are **new proposed interfaces**, not symbols already present in the repo.
Record accepted definitions in `docs/INTERFACES.md` first.

- `RasterSource` / `AnalysisGrid`: immutable source identity, window reads,
  validity, transform, XY units, vertical metadata and analysis-level identity.
- `StreamAnalysis`: versioned derived surfaces/evidence/network, boundary
  uncertainty, effective preparation configuration and cache identity.
- `StreamRequest`: terrain/analysis identity, seed/destination, soft guides,
  hard nodes, intent and conditioning permissions; immutable worker snapshot.
- `StreamResult`: proposed XYZ, alternatives, structured located diagnostics,
  relative confidence, resolved config and provenance. Retain a compatibility
  adapter to current preview/editing for staged rollout.
- Cache key: source identity + actual analysis domain/grid + algorithm/model
  version + relevant units and conditioning configuration. Commit atomically;
  cancelled/incomplete cache entries are never accepted as valid.
- Persistent engine identity per feature/correction, reference layers outside
  accepted feature collections, and an explicit diagnostic stale/recompute policy.
- Persistent junction IDs if network editing is enabled; specify propagation,
  split/join/reverse/delete and undo behavior before promising connectivity.

`install_preview` currently duplicates QA and hardcodes uphill warning text
(`app.py:1096–1134`); centralize common QA so the adapter does not overwrite new
diagnostics. `editing.py` imports private trace helpers and replaces metrics;
separate shared geometry integrity from engine evidence before routing changes.

Use an explicit schema migration for changed project interpretation. Keep old
coordinates untouched on load; legacy explicit retrace must disclose engine
selection rather than silently substitute a new algorithm. Old cell-based
parameters are not reinterpreted as new physical-unit parameters. Project,
draft, recovery, local correction and export round trips all need fixtures.

Background analysis needs phase progress, bounded cancel checkpoints and request
generation IDs. The current single worker locks the workbench, and compiled MCP
cannot be cancelled mid-solve (`app.py:488–549`; `tracing.py:527–534`). Keep pan/zoom
and accepted geometry usable while preparing a new candidate; expensive analysis
must not move into main-thread terrain-install callbacks. Isolate noninterruptible
external workloads if needed, with safe cache/output cleanup.

## 7. Ordered implementation packages and ownership

No dates are promised; each gate decides whether the next package is justified.
One integrator owns shared manifests/configuration and accepts boundary changes.
Use disjoint files/worktrees and no blind overwrite of teammate changes.

| Package | Owner / proposed files | Dependency | Exit evidence |
|---|---|---|---|
| A. Reproducible corpus and baseline | Research/evaluation: new `evaluation/` manifest/harness and `scripts/evaluate_streams.py`; public metadata only in source | None | Small real pairs read back; reviewed label definitions/splits; exact baseline metrics, failure counts and source/config manifests. Large/private data external and ignored. |
| B. Contracts and provenance | Integrator: `docs/INTERFACES.md`, shared config; project lane: `project.py`, `recovery.py`, round-trip tests | A's case schema | Agreed request/result/grid definitions; legacy/migration tests; old XYZ unchanged; unknown versions handled safely. |
| C. Native-resolution analysis access | Terrain lane: new window/grid module, `terrain.py`, terrain tests | B | Display-independent results, rectangular-cell transforms, conservative source NoData, bounded memory and cache invalidation. |
| D. Drainage preprocessing | Hydrology lane: new stream-analysis module and synthetic tests | C | Flats, pits, real depressions, masked islands, clipped catchments and conditioning diagnostics pass; source raster/Z unchanged. |
| E. Candidate graph and reach solver | Tracing lane: new stream solver, narrow `tracing.py` dispatch, algorithm tests | D | Default-only holdout comparison; meanders/branches improve; ambiguity/abstention is measured; manual/ridge/slope-break do not regress. |
| F. Auto workflow and review layers | UI lane: `app.py`, `canvas.py`, `desktop_actions.py`, `preferences.py`, UI tests | Stable B/E result contract | Start/end Auto, optional downstream, branch-choice click, located diagnostics, responsive navigation/cancel, explicit preview/accept and local correction. |
| G. Editing/network integration | Editing/project lane: `editing.py`, project tests and topology module if approved | B/E; coordinate with F | Fixed connections and outside-segment XYZ retained; diagnostics lifecycle and junction undo semantics proven. |
| H. Optional learned ranking | Evaluation/model lane: new calibration modules and safe artifacts | A/E benchmark plateaus | Beats deterministic method on untouched regions, calibrated abstention, CPU/offline inference and provenance; otherwise omit. |
| I. Acceptance and packaging | Integrator/release lane: guide/research/changelog, CI and packaging | E/F/G | Full suite, real visible workflow, independent export read-back and fresh frozen smoke; native Windows explicitly separate. |

Deliver a working reach-level vertical slice through A–F before expanding to an
entire automated network or a large learned model. Do not wait for every future
network feature to make stream tracing useful.

## 8. Proposed promotion gates

The following are **targets to validate**, not achieved guarantees. Freeze their
precise denominators/tolerances after label review and before blind evaluation.

- Default-only Auto on reviewed, resolvable single-channel reaches: target at
  least **90% accepted without numerical setting changes**, with median no more
  than one additional intent/correction guide beyond start/end. Report failures
  and abstentions in the denominator; report difficult strata separately.
- Relative to current defaults, target at least **50% reduction in median
  operator time to accepted reach** in a counterbalanced user exercise. Record
  clicks, corrections and wrong-branch acceptance, not just preview speed.
- Held-out localization: target at least **30% lower paired reach-level p95
  distance** than current defaults, using uniformly arc-length-sampled,
  bidirectional distances and label uncertainty. Report reach distributions,
  catchment-clustered uncertainty and per-stratum regressions; do not pool all
  vertices so long/easy reaches dominate. Set absolute tolerances by source and
  target, not one claimed universal metre accuracy.
- Network cases: measure correct branch/outlet selection, reachable connectivity,
  junction displacement, missing/spurious reaches and edge-truncation awareness.
  Geometric similarity alone does not pass wrong-basin routes.
- Integrity: **zero NoData crossings**, exact protected-node/correction-boundary
  preservation, source sampled Z unchanged, display settings cannot affect route,
  deterministic versioned results and unchanged legacy saved coordinates.
- Confidence: flat/no-channel and unresolved material-crossing cases must flag
  ambiguity or abstain. Report error-versus-coverage curves and false-confidence
  rate on the deliberately hard set.
- Performance: target warm short-reach preview p95 under **1 s** and cancellation
  response under **250 ms**, with hardware/input/domain stated. Separately measure
  cold preparation time and peak memory on native 1 m data. No blanket latency
  promise before profiling; external noninterruptible stages need isolation.
- Integration: focused tests then suite; invalid/moved/missing reference sources;
  save/recovery/migration/correction/export read-back; offscreen UI smoke and
  visible open/trace/branch-choice/correct/save/reopen/export exercise.
- Packaging: qualify chosen dependencies on native Windows/Linux and frozen
  resources. Wine/hosted offscreen success is not native interactive Windows
  acceptance. Training remains a development task, not an end-user installation
  requirement; runtime works offline without credentials or GIS software.

## 9. Remaining evidence gaps and immediate next implementation

The full-code review, green baseline, executed synthetic failures, genuine public
pair download/read-back and preliminary default-route discrepancy checks are
complete. A replacement solver, reviewed real labels, training, blind evaluation
and user productivity study are **not** complete.

Implement **Package A plus the B contract** first: turn the local pilot into a
repeatable paired-data harness, add acquisition-matched Sonoma/EDH examples and
independent-source Massachusetts cases, adjudicate representative reaches and
freeze development/holdouts. Then prototype C–E against those same frozen cases.
Do not claim a method wins from the three unreviewed Minnesota lines or promise
that learned labels will solve missing culverts/bathymetry.

Local evidence is under `artifacts/stream-overhaul/`; downloaded source data are
not redistributed with this document. Some USGS HTML requests were blocked and
`web_extract` was unavailable in this session; primary service/API retrieval and
research-lane official HTTP reads supplied the data evidence. Public source links
below identify what was actually researched; access and licensing must be pinned
again when constructing a redistributable corpus.

## Sources

[1] https://sites.google.com/site/geonethome
[2] https://github.com/passaH2O/GeoNet
[3] https://www.whiteboxgeo.com/manuals/qgis/hydrology-depressions-storage.html
[4] https://www.usgs.gov/3d-hydrography-program/access-3dhp-data-products
[5] https://www.usgs.gov/ngp-standards-and-specifications/lidar-base-specification-appendix-2-hydro-flattening-reference
[6] https://catalog.data.gov/dataset/1-meter-digital-elevation-models-dems-usgs-national-map-3dep-downloadable-data-collection
[7] https://www.arcgis.com/sharing/rest/content/items/49babc6c5052422499fa5c996a3ddd39/info/metadata/metadata.xml
[8] https://mn.gov/mngeo/gis-data-and-maps/info-by-topic/elevation/lidar/lidar-gen2.jsp
[9] https://www.mass.gov/info-details/massgis-data-massdep-hydrography-125000
[10] https://www.mass.gov/info-details/massgis-data-lidar-terrain-data
[11] https://sonomavegmap.org/blog/2016/03/03/hydrologic-data-products-now-available
[12] https://3dhp.nationalmap.gov/arcgis/rest/services/usgs_3dhp_all/FeatureServer
[13] https://www.dnr.state.mn.us/sitetools/data_software_license.html
