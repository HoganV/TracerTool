# Running and building TracerTool

## Source checkout

The package minimum is Python 3.11. The CI matrix covers Python 3.11/3.12 on
Linux and 3.13/3.14 on Windows; see [recorded results](VALIDATION.md). This is
not a claim of compatibility with every newer Python release. The historical
0.2.0 portable environments used Python 3.12 on Linux and 3.13 on Windows.
For Windows source use, **64-bit Python 3.14 or 3.13** is supported. For a new
3.14 environment ([Python downloads](https://www.python.org/downloads/windows/)):

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python --version
.venv\Scripts\python -m pip install -c scripts/windows-build-constraints.txt -e ".[dev]"
.venv\Scripts\python -m tracertool
```

For 3.13, replace `py -3.14` with `py -3.13`. The constraint file automatically
selects Qt/PySide6 6.10.3 on Python 3.14 and 6.9.3 on Python 3.13. All four Qt
packages use matching versions. Python 3.15 and free-threaded Python builds
have not been tested. These commands target standard x64 CPython.
Use Python **3.14.2 or newer** when choosing a 3.14 patch release. NetworkX
excludes 3.14.1 because of an upstream CPython dataclasses regression, fixed
in 3.14.2; see [NetworkX's compatibility note](https://github.com/networkx/networkx/pull/8372).
Do not bypass that restriction by forcing an older NetworkX package.

On Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m tracertool
```

For subsequent `python` commands, use that installed environment's interpreter:
`.venv/bin/python` on Linux or `.venv\Scripts\python` on Windows, or activate
the environment first.

`python scripts/run.py` uses the checkout's environment if present. An optional
TIFF or project path opens that file at startup. For a public example, run
`python scripts/create_demo.py --output artifacts/demo`, then open
`artifacts/demo/demo.tracer.json`. The older `--demo` switch expects local
private reference tiles and is not the public demo generator.
Installation requires downloaded dependencies; normal use of a
completed installation is local and offline.

The launcher also detects an optional locally extracted Linux Qt dependency
directory at `.venv/native/usr/lib/x86_64-linux-gnu` and starts a new Python
process with that library path. This supports the local desktop without
requiring a system package installation. The portable builder uses the same
path during dependency discovery; it is not expected on recipient computers.

### Windows Python version mismatch

If pip downloads `cp314` wheels but reports that `PySide6==6.9.3` has no
matching distribution, the checkout still has the old Python 3.13-only
constraint. [PySide6 6.10.3 supports Python 3.14](https://pypi.org/project/PySide6/6.10.3/).
Version 0.2.1 fixes selection without changing Python or deleting the existing
environment. Close TracerTool, then run from the cloned repository folder:

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install --upgrade -c scripts/windows-build-constraints.txt -e .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m tracertool
```

The version check should report 3.14.x (3.13.x is also supported). If `.venv`
does not exist, create it with `py -3.14 -m venv .venv` first. No environment
activation or PowerShell execution-policy change is needed. The final command
is all that is needed for later launches. `.[dev]` is optional for testing and
packaging, rather than normal use. Keep terrain and projects outside `.venv`.

## Verification

```sh
python -m pytest -q
python -m tracertool --smoke-test
python scripts/check_publication.py --history
```

Set `QT_QPA_PLATFORM=offscreen` when running UI checks on a machine without a
display. The smoke test creates temporary terrain rather than relying on the
user's data. A smoke test is a dependency and startup check, not a complete
usability or terrain-accuracy evaluation.

Run the history audit in the sanitized public checkout described in
[PUBLISHING.md](PUBLISHING.md). The original private development checkout
deliberately retains its earlier history and will fail that public-history check.

`python scripts/benchmark.py` times the six local reference files and writes
`artifacts/benchmark.json`. See [VALIDATION.md](VALIDATION.md) for the measured
baseline and its limits; the reference TIFFs are not needed by public CI.

## Portable folder and ZIP

From the installed development environment:

```sh
python scripts/build_portable.py
```

The script builds `dist/TracerTool/`, runs the frozen application's smoke test,
and creates a versioned ZIP plus SHA-256 checksum in `dist/`. On Windows the
entry point is `TracerTool.exe`. Extract the whole ZIP and keep its internal
files together. A recipient should not need Python, ArcGIS, an installer, or
administrator access to run it. That expectation still requires the clean
Windows validation listed in [ROADMAP.md](ROADMAP.md).

Verify the extracted archive independently with
`python scripts/verify_portable.py path/to/TracerTool-version-platform-portable.zip`.
This checks its checksum/CRC, excludes terrain/project payloads, extracts into
a fresh path containing spaces and Unicode, removes Python/GDAL/PROJ overrides,
and runs the frozen smoke test there. The corresponding `.zip.sha256` must be
beside the archive. Run this with the target platform's Python.

Build Windows binaries with **Windows Python and Windows PyInstaller**.
PyInstaller is not a cross-compiler. A native Windows host is preferred; this
development process also produced an actual PE executable with those Windows
tools under Wine, with provenance and commands in [WINDOWS_BUILD.md](WINDOWS_BUILD.md).
That local executable is excluded from the public source checkout.
Wine checks are separate from clean Windows acceptance. The included
GitHub Actions workflow runs Windows/Linux source checks and creates native
portable builds only on manual dispatch. Binary artifact upload is a separate,
default-off choice after distribution review; see [PUBLISHING.md](PUBLISHING.md).
It does not publish a release. The first hosted source checks passed on Windows
and Linux; see [VALIDATION.md](VALIDATION.md). Interactive Windows and frozen
Windows package acceptance remain separate checks.
[PyInstaller documentation](https://pyinstaller.org/en/latest/)

`scripts/tracertool.spec` collects Rasterio resources and extension modules,
including sibling DLL directories from Windows delvewheel builds, the required
scikit-image graph modules, and Qt's normal platform hooks. A
runtime hook selects the bundled GDAL and PROJ data directories. Rasterio
wheels contain native GDAL dependencies; packages must therefore be tested as
frozen applications, not only as imports in a development environment.
[Rasterio installation documentation](https://rasterio.readthedocs.io/en/stable/installation.html)

The ZIP includes the original project license, guides, dependency versions,
source hashes, build-platform details and discoverable dependency license files.
The builder refuses a ZIP if application source changes during packaging.
Use `--dist-dir` and `--work-dir` to isolate simultaneous platform outputs.
The manifest describes the complete
build environment, including tooling; it is not an audited software bill of
materials. A release maintainer must inspect bundled native-library notices
and supply any required corresponding-source/relinking materials before public
distribution. Qt/PySide components keep their own licenses. Keep bundled Qt
libraries replaceable and document their exact upstream versions. Do not
describe the whole bundle as MIT-only. [Qt licensing](https://doc.qt.io/qt-6/licensing.html)

## Shareable source archive

After the reviewed changes are committed, run
`python scripts/build_source.py --commit COMMIT_SHA`.
This uses the exact Git snapshot, adds its commit identity, and creates a
versioned source ZIP/checksum. It refuses a snapshot containing private terrain,
generated outputs or detected sensitive metadata. The public data guide and
synthetic demo remain included. Uncommitted edits are intentionally not included. Build the
portable executables from that same reviewed source snapshot before delivery.

## Troubleshooting

- **No Qt platform plugin:** use the complete extracted folder. On Linux,
  distribution graphics libraries may still be required; `offscreen` is for
  automated checks, not normal interactive use. In particular, Qt's XCB plugin
  requires the `libxcb-cursor0` system package on Debian/Ubuntu. The CI workflow
  installs this plus EGL/OpenGL runtime libraries. Linux bundles inherit the
  build system's glibc compatibility boundary and are not universal binaries.
- **Missing `proj.db` or GDAL resources:** inspect the frozen bundle's
  `rasterio/proj_data` and `rasterio/gdal_data`. Rebuild with the supplied spec;
  do not mix ArcGIS/QGIS Python environments into this application.
- **Missing terrain after moving a project:** preserve the relative project/
  TIFF layout, restore the source file to its recorded location, or use the
  relink prompt. The editor checks recorded terrain metadata and available
  content fingerprint before accepting
  a replacement so line coordinates are not silently applied to another grid.
- **Workplace application policy:** use the organization's normal executable
  review process. A portable folder avoids installation but does not bypass
  operating-system or employer application controls.
