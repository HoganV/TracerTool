# Windows portable build on the local Linux host

The Windows build uses **Windows CPython, Windows binary wheels, and the Windows
PyInstaller bootloader**, executed through Wine. It produces a Windows PE
executable. It does not turn the Linux executable into a Windows executable,
and Wine results do not count as clean Windows acceptance. Prefer the included
Windows CI job or a real Windows development host for regular releases.

## Recorded toolchain

- Official [CPython 3.13.16 Windows embeddable x64 ZIP](https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip).
- Official WineHQ 11.0 packages for Ubuntu Noble, `wine-stable` and
  `wine-stable-amd64`, extracted locally without installing system packages.
  Package SHA-256 values were verified against the downloaded
  [WineHQ repository metadata](https://dl.winehq.org/wine-builds/ubuntu/dists/noble/main/binary-amd64/Packages.gz).
- Windows wheels downloaded from PyPI. The resolved environment is recorded in
  [windows-build-constraints.txt](../scripts/windows-build-constraints.txt).
  The build uses Qt/PySide 6.9.3; the 6.12 Windows wheel requires an OS ICU DLL
  absent from this Wine environment. This is an explicit build constraint,
  not a claim that Qt 6.12 is defective on supported Windows installations.

All tools, wheels, Wine prefixes and diagnostic logs are under ignored
`build/windows-toolchain/`. No Wine component is shipped in the application.
No reference TIFF is uploaded or included in a portable ZIP.

## Local layout and reproduction

Extract the CPython ZIP into `build/windows-toolchain/python`. In its
`python313._pth`, retain the ZIP and current-directory entries, add
`Lib/site-packages`, and enable `import site`. Extract the official `pip` wheel
into `Lib/site-packages` to bootstrap the embeddable environment. Ordinary
Windows installations can use a normal virtual environment instead.

Extract WineHQ packages with `dpkg-deb -x` into
`build/windows-toolchain/winehq`; the executable should be
`winehq/opt/wine-stable/bin/wine`. Optional Ubuntu runtime dependencies are
extracted under `build/windows-toolchain/wine`. The checked-in launcher sets
the local library path, Wine prefix and Windows DLL search paths. The prefix
is dedicated to this build, not an existing user Wine installation.

Download Windows wheels with the native host pip using
`--only-binary=:all: --platform win_amd64 --python-version 3.13 --implementation
cp --abi cp313`, then install them using Windows pip through the launcher.
When cross-downloading, include `pefile`, `pywin32-ctypes` and `colorama`
explicitly because host environment-marker evaluation can omit Windows-only
requirements. Apply the recorded constraints and remove incompatible leftover
Qt distributions before installing the selected Qt version.

```sh
python scripts/wine_run.py -- -m pip install --no-index --find-links build/windows-toolchain/wheels -c scripts/windows-build-constraints.txt -e '.[dev]' --no-build-isolation
QT_QPA_PLATFORM=offscreen python scripts/wine_run.py --log build/windows-toolchain/tests.log -- -m pytest -q
QT_QPA_PLATFORM=offscreen python scripts/wine_run.py --log build/windows-toolchain/build.log -- scripts/build_portable.py --dist-dir dist/windows --work-dir build/windows
QT_QPA_PLATFORM=offscreen python scripts/wine_run.py --program dist/windows/TracerTool/TracerTool.exe -- --smoke-test
QT_QPA_PLATFORM=offscreen python scripts/wine_run.py -- scripts/verify_portable.py dist/windows/TracerTool-0.2.0-windows-amd64-portable.zip
```

The `--log` option preserves pipe-backed Windows standard handles while saving
output; direct file redirection exposed standard-handle failures in the older
Wine 9 environment. Wine 9 also lacked `CopyFile2` needed by current CPython.
Wine 11 resolved that toolchain limitation. Avoid copying DLLs from unrelated
Windows installations or downloading unofficial runtime bundles.

The portable builder uses separate Windows output/work directories, includes
the CPython license, dependency notices, exact installed versions and source
hashes, and runs the frozen smoke test before creating its ZIP and checksum.
The embedded build manifest labels the Wine build environment. Inspect the
current [validation record](VALIDATION.md) for actual results and outstanding
real Windows checks.
