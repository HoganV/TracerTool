# Contributing to TracerTool

Useful contributions include reproducible bug reports, workflow improvements,
documentation, and tests of terrain tracing and GIS interchange. For substantial
algorithm, file-format, or dependency changes, describe the problem and proposed
approach in an issue before investing in a large implementation.

Read [AGENTS.md](AGENTS.md) and the [module contracts](docs/INTERFACES.md) before
changing code. The [user guide](docs/USER_GUIDE.md), [research notes](docs/RESEARCH.md),
and [roadmap](docs/ROADMAP.md) explain the current behavior and its limits.

## Development and validation

Use Python 3.11 or later in a separate virtual environment. Follow the platform
setup and dependency instructions in [BUILDING.md](docs/BUILDING.md), including
the Windows dependency constraints when working on Windows. After installation:

```sh
python -m pytest -q
python -m tracertool --smoke-test
```

Set `QT_QPA_PLATFORM=offscreen` when running Qt checks without a desktop. Run
focused tests while developing and the full suite before submitting code changes.
Documentation-only changes need link and example checks rather than application
tests. Describe any checks you could not run.

- Terrain changes need deterministic synthetic cases, including bends, levees,
  channels, flats, and NoData barriers. Measure geometry and elevation behavior;
  an attractive screenshot alone does not establish accuracy.
- Persistence and export changes need round trips, legacy-project compatibility,
  failed-write preservation, and independent export read-back checks.
- UI changes need offscreen interaction checks and a visible workflow check when
  a desktop is available. State which environments you actually used.
- Packaging changes need a frozen-app smoke test with bundled GDAL, PROJ, and Qt
  resources. Linux, Wine, native Windows, and target-GIS checks are separate claims.

## Data and coordinate rules

Use generated synthetic terrain in public tests. Do not commit or attach the
private reference TIFFs, employer/client datasets, project files, recovery files,
or derived exports. Screenshots and logs can reveal locations, client names, and
local paths; redact them before sharing. A small synthetic reproduction is
usually more useful than a large real dataset. Include third-party data only
when redistribution is permitted and its origin and license are documented.

Editable XY stays in the source projected CRS; reprojection transforms an
explicit copy. Decode band scale/offset before reducing precision, and preserve
source Z when sampling, editing, and exporting. Display exaggeration and unit
overrides must not alter geometry. Do not silently convert vertical units or
infer a vertical datum. Validate entire segments against NoData, including after
smoothing and simplification. Loading a saved project must preserve its stored
coordinates and the meaning of legacy parameters.

## Pull requests and AI assistance

Keep each PR focused. Explain the user-visible problem, resulting behavior,
validation results, and remaining limitations. Update relevant documentation and
the changelog when behavior changes. Follow the repository's versioned project
contract; do not reinterpret older files without an explicit migration.

Disclose AI assistance in the PR: name the tools used, describe what they helped
produce or review, and state what you personally inspected and tested. If none
was used, say so. Private prompts, chat transcripts, credentials, and proprietary
data are not required and should not be pasted into the PR. The contributor
remains responsible for correctness, licensing, privacy, and the accuracy of
validation claims; AI output is not evidence that a check passed.

Contribute only material you have permission to share under the project's
[MIT license](LICENSE), and retain applicable third-party notices. For suspected
security vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of posting
technical details in a public issue.
