# Build with: python -m PyInstaller scripts/tracertool.spec --clean --noconfirm
from pathlib import Path
from PyInstaller.compat import is_win
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata, collect_delvewheel_libs_directory

root = Path(SPECPATH).parent
data, binaries, hidden = collect_all("rasterio")
if is_win:
    data, binaries = collect_delvewheel_libs_directory("rasterio", datas=data, binaries=binaries)
hidden += collect_submodules("skimage.graph")
hidden += ["scipy.ndimage"]
for name in ("rasterio", "scikit-image", "numpy", "scipy", "PySide6", "pyshp"):
    data += copy_metadata(name)
data += [(str(root / "LICENSE"), ".")]

a = Analysis(
    [str(root / "scripts" / "frozen_entry.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=data,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[str(root / "scripts" / "rasterio_runtime.py")],
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="TracerTool",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TracerTool")
