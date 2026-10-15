# Working on TracerTool

Build a local, independent terrain editing application for Windows and Linux.
The user has authorized parallel agent work and routine implementation choices.
Prioritize usable, reviewable desktop workflows; distinguish tested behavior from
future plans. Never call the output survey-grade or hydrologically validated
without evidence from independent ground truth.

## Coordinate and data rules

- Read `docs/INTERFACES.md` before changing module boundaries.
- Editable XY stays in the source projected CRS. Explicit export reprojection
  transforms a copy only. Raster arrays use row/column; Qt scenes
  use column/row. Cell centers, not corners, represent sampled anchors.
- Decode band scale/offset and retain source elevation units; display exaggeration must never affect
  exported Z. Never silently infer a vertical datum or convert feet to meters.
- NoData is impassable, including straight segments after simplification.
- Larger DEMs currently use a disclosed working grid. Do not equate display
  resolution or dense vertex spacing with measurement accuracy.
- Treat reference inputs as user data. Do not modify, commit, upload, or bundle
  them. Public tests use generated synthetic data.

## Parallel ownership

Before delegation, assign disjoint files and record interface changes in the
contract. Default lanes: terrain/tracing; project/export; UI/integration;
research/docs/packaging. A single integrator owns shared configuration and
accepts boundary changes. Agents report changed files, checks, remaining risks,
and actual completion status. Do not overwrite a teammate's unfinished work.

## Review and verification

- Use deterministic synthetic valleys, ridges, slope breaks, flats, pits, and
  NoData barriers for algorithm changes; test coordinate transforms and units.
- Persistence changes need round-trip, invalid-schema, moved-source, and export
  read-back checks. Never deserialize executable project content.
- UI changes need an offscreen smoke test plus visible inspection of the real
  workflow when a desktop session is available.
- Run focused tests, then the suite at integration. Do not claim Windows support
  from a Linux build. Distinguish Windows PE tests under Wine from native Windows
  acceptance. Frozen GDAL/PROJ/Qt resources require a packaged smoke test.
- Update user guide, research decisions, and changelog when behavior changes.
- No remote publication, credentials, telemetry, or automatic updates are needed
  for normal operation. Do not add them as prerequisites.

## Versioning and completion

Use SemVer for the application; projects have a separate schema version. Add
migrations before changing existing project interpretation. Keep source-version
constants consistent. Follow `docs/ROADMAP.md` release gates and
`docs/BUILDING.md` portable-app checks. Report limitations honestly rather than
marking roadmap work complete because a stub or CI recipe exists.
