# Changelog

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
