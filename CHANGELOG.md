# Changelog

## 0.3.0 — experimental Auto stream source prerelease

- Added explicit opt-in source-native Auto stream proposals with directional
  channel and drainage evidence, bounded domains and structured uncertainty.
  Legacy remains the default pending independent qualification.
- Added paired-stream evaluation tooling with bidirectional arc-length metrics
  and explicit failed/unresolved-case accounting; no trained model is bundled.
- Added schema-2 engine provenance, schema-1 migration without geometry changes,
  diagnostic-evidence preservation and protected-junction edit safeguards.
- Hardened portable archive bounds/path checks, clean-source provenance and
  tracked-document packaging. Public binary distribution remains uncleared.
- This is an experimental source release, not completed hydrologic validation,
  independent operator productivity evidence or native Windows desktop acceptance.

## 0.2.2 — terrain display and draft tracing, 2026-10-16

- Added RAS-inspired terrain, Topographic and Spectral elevation palettes, plus
  a current-view minimum–maximum color range that updates after pan and zoom.
- Reined in new trace defaults to a 12-cell search radius, 3-cell target
  spacing and 0.75-cell bend tolerance. Physical sizes follow the working
  terrain resolution. Both smoothing stages default to zero in collapsed
  advanced controls; hover help explains settings, effects and accepted ranges.
- Removed the arbitrary search-radius ceiling and separated terrain-response
  scale from corridor width so a broad search can retain close output spacing.
- Allowed ordinary rough guides to move toward the terrain while preserving
  snapped connections and local-correction boundaries. Added draft guide
  move/insert/delete and undo/redo while developing a trace, including rapid
  insertion followed by a drag without duplicate points.
- Corrected rough guides being drawn toward isolated shoulder bumps or pits,
  especially at endpoints, by checking continuity along the local guide
  direction. This retains the continuous crest/channel without coupling the
  support scale to search radius or enabling smoothing. Available one-sided
  evidence supports guides near raster edges; NoData gaps stop that evidence.
- Kept project schema 1 compatible: optional guide-relaxation and fixed-guide
  fields are validated; old saved geometry is never recomputed on open, and
  explicit legacy retracing retains fixed guides when the option is absent.
- Preserved snapped-guide constraints through retracing and reversal, and
  invalidated stale constraints after geometry edits.
- Stabilized view-dependent rendering and automatic previews, and kept prior
  display settings intact when a custom color range is invalid. Display-only
  palette/range changes preserve an unaccepted preview.
- Added synthetic checks for rough-guide relaxation on curved valleys, ridges
  and banks at fine/coarse cell sizes, wide-search spacing, flats, pits and
  NoData barriers; exercised draft editing and save/reopen/export through
  native Linux mouse and keyboard control.

Verification and remaining limits are recorded in [docs/VALIDATION.md](docs/VALIDATION.md).
No 0.2.2 portable package or interactive Windows acceptance is claimed.

## 0.2.1 — Windows Python 3.14 installation, 2026-10-15

- Fixed the Windows constraints to select PySide6, Addons, Essentials and
  Shiboken 6.10.3 for Python 3.14, preserving the recorded Python 3.13 pins.
- Added Windows Python 3.14 to the automated installation, dependency,
  integration and startup checks, with explicit runtime version reporting.
- Updated Windows instructions to reuse an existing Python 3.14 environment
  after the failed install. Terrain algorithms and project schema are unchanged.

## 0.2.0 — local desktop build, 2026-10-15

- Prepared a sanitized public source snapshot, explicit AI development disclosure,
  contributor/security guidance, issue/PR templates and prerelease notes.
- Added a reproducible synthetic levee/stream demonstration and screenshot,
  a tracked-file/full-history publication audit, and bounded CI with reviewed
  action pins and dependency updates. Binary distribution remains a separate gate.
- Replaced dense raster-corner output with bounded feature-aware line smoothing
  and fresh arc-length sampling. New defaults use 2-cell terrain smoothing,
  4-cell line smoothing, 8-cell target spacing and 1-cell bend tolerance.
- Added a levee/embankment preset and actual spacing statistics. Fixed guides,
  real bends and NoData safety take precedence over regular spacing; legacy
  projects retain their saved settings.
- Added local segment corrections and full retracing from retained guide points,
  with preview/apply/cancel and preserved geometry outside corrections.
- Added vertex insertion/deletion, split, join, reverse, feature/raster snapping,
  refreshed geometry diagnostics and undoable editing operations.
- Added project settings for palettes, elevation stretch, gamma, illumination,
  contours, snapping, history, working resolution and export options.
- Added recovery snapshots including unfinished drafts, previous-save backups,
  source-content fingerprints, safer relinking and background cancellation.
- Added separate reprojected terrain copies and optional projected XY export
  with an explicit Z multiplier; source terrain and vertical datum are preserved.
- Corrected transformed-export metadata: output metrics describe converted
  coordinates, original metrics remain available, and explicit Z scaling does
  not infer a vertical unit or datum.
- Preserved calibrated integer-raster source elevations by decoding before
  float32 working-grid conversion; hardened recovery-folder probing and the
  native sidebar layout.
- Built an actual Windows x64 portable executable with Windows CPython and
  PyInstaller through Wine 11, with pinned Windows build dependencies, license
  notices, source hashes and a successful frozen smoke test.
- Expanded interaction, persistence, raster and editing tests. The Windows
  test run found and fixed a Windows writable-descriptor requirement for
  durable raster output commits.

This is a usable local desktop build with recorded validation boundaries.
Windows compatibility-layer checks do not replace clean Windows acceptance;
target-GIS acceptance and operator-reviewed geometry accuracy remain open.

## 0.1.0 — prototype, 2026-10-14

- Established a native desktop terrain viewer and assisted line-editing workflow.
- Added anchor-guided stream, ridge and slope-break tracing, manual lines,
  configurable cell-based parameters and explicit preview/accept interaction.
- Added feature management, profile review and geometry correction.
- Added versioned JSON projects and native-CRS three-dimensional vector export.
- Added synthetic spatial/persistence tests and local real-TIFF verification.
- Documented primary research, input metadata, phased roadmap and agent ownership.
- Added native portable build tooling and Windows/Linux CI configuration.

This is a development prototype, not a published production release. Windows
packaging configuration is not a claim of a completed Windows acceptance run.
Complete hydrologic networks, mosaics, large-area full-resolution processing,
and calibrated extraction accuracy remain future work.
