# Third-party components and distribution review

TracerTool's original code and documentation use the [MIT license](LICENSE).
That license does not relicense Python, Qt, geospatial libraries or other
components installed from package repositories. The source checkout declares
its dependencies; portable binaries additionally redistribute those components.
This document is an inventory starting point, not completed clearance for a
public binary release.

## Principal components

The upstream links describe each project's licensing. The exact versions and
license texts shipped in an individual bundle take precedence over this short
summary, including any per-file or embedded-component exceptions.

| Component | Role | Upstream licensing reference |
|---|---|---|
| CPython | Python runtime in portable applications | [Python license and history](https://docs.python.org/3/license.html), including incorporated components |
| PySide6 / Shiboken / Qt | Desktop interface and Qt runtime | [Qt for Python licenses](https://doc.qt.io/qtforpython-6/licenses.html) and [Qt licensing](https://doc.qt.io/qt-6/licensing.html); LGPL/GPL/commercial choices vary by component |
| NumPy | Numerical arrays | [BSD-style license](https://numpy.org/doc/stable/license.html) |
| SciPy | Filtering and numerical routines | [BSD license and component notices](https://github.com/scipy/scipy/blob/main/LICENSE.txt) |
| Rasterio | Raster access | [BSD license](https://github.com/rasterio/rasterio/blob/main/LICENSE.txt) |
| GDAL | Native geospatial raster backend | [GDAL license collection](https://github.com/OSGeo/gdal/blob/master/LICENSE.TXT), with embedded-component notices |
| PROJ | Coordinate reference systems and transforms | [PROJ copying terms](https://github.com/OSGeo/PROJ/blob/master/COPYING) |
| scikit-image | Least-cost paths and image operations | [License collection](https://github.com/scikit-image/scikit-image/blob/main/LICENSE.txt) |
| PyShp | Shapefile read/write | [MIT license](https://github.com/GeospatialPython/pyshp/blob/master/LICENSE.TXT) |
| PyInstaller | Packaging and frozen bootloader | [License and distribution exception](https://pyinstaller.org/en/stable/license.html) |

Transitive Python packages, numerical runtimes, image codecs, compression
libraries, platform runtimes and Qt's own third-party components also need
review. The table is not a complete list of the DLLs/shared libraries in a
portable folder, and does not assert that every listed native component is
bundled on every platform.

## Existing build records

The portable builder collects discoverable original license/notice files into
`third-party-licenses/`, records the installed build environment in
`dependency-manifest.json` and `build-environment.txt`, and records application
source hashes and build details in `build-info.json`. These records include
build/test tooling as well as runtime dependencies; they are not an audited
software bill of materials. Automatically finding license-named files does not
prove that every native dependency or required source material is covered.

The recorded local Windows build used Windows CPython 3.13.16 and Qt/PySide6
6.9.3 through Wine. Linux used Python 3.12.3 and Qt/PySide6 6.12.0. Version-specific
notices must be checked against the actual new build rather than copied from
these historical examples. Wine was a local build/test host and is not part of
the application bundle.

## Before public binary distribution

- Inventory the actual packaged Python modules and native binaries, including
  their versions, provenance and transitive licensing. Reconcile this with the
  collected notices and include missing texts/materials.
- For Qt/PySide components distributed under LGPL, document the exact applicable
  terms, preserve notices and license texts, provide the required corresponding
  source/access mechanism, and ensure the recipient can replace/relink the
  library as required. Inspect the selected modules for different terms;
  dynamic packaging alone is not a compliance determination. Qt describes
  these obligations in its [LGPL distribution guidance](https://www.qt.io/development/open-source-lgpl-obligations).
- Review Python, GDAL/PROJ, numerical libraries and platform runtimes in the
  actual bundle. Preserve their copyright and attribution requirements and
  any applicable source/distribution conditions.
- Retain the matching TracerTool source snapshot, dependency versions, build
  configuration, checksums and a completed component review with the release.
  Remove all private data and internal development paths before distribution.

These public-binary checks are still open. A passing functional smoke test does
not complete them. Publishing the reviewed, sanitized original source is a
separate task; see [PUBLISHING.md](docs/PUBLISHING.md). No upstream project is
represented as endorsing TracerTool.
