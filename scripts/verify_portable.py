"""Extract a portable ZIP into a fresh Unicode/spaced path and smoke-test it.

Run with the target platform's Python. Windows execution through Wine remains
compatibility-layer evidence, not clean Windows acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from zipfile import ZipFile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    checksum = args.archive.with_suffix(".zip.sha256")
    expected = checksum.read_text(encoding="utf-8").split()[0]
    with args.archive.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if expected != actual:
        raise ValueError("Portable archive checksum does not match.")
    with tempfile.TemporaryDirectory(prefix="TracerTool portable Ω ") as temporary:
        base = Path(temporary)
        with ZipFile(args.archive) as archive:
            if archive.testzip() is not None:
                raise ValueError("Portable archive contains a damaged entry.")
            for item in archive.infolist():
                target = (base / item.filename).resolve()
                if not target.is_relative_to(base.resolve()):
                    raise ValueError("Portable archive contains an unsafe path.")
                if item.filename.lower().endswith((".tif", ".tiff", ".tracer.json")):
                    raise ValueError("Portable archive must not contain terrain or project data.")
            archive.extractall(base)
        folder = base / "TracerTool"
        executable = folder / ("TracerTool.exe" if os.name == "nt" else "TracerTool")
        if os.name != "nt":
            executable.chmod(executable.stat().st_mode | 0o111)
        env = os.environ.copy()
        for key in ("PYTHONPATH", "PYTHONHOME", "GDAL_DATA", "PROJ_DATA", "PROJ_LIB"):
            env.pop(key, None)
        if os.name != "nt":
            env.pop("LD_LIBRARY_PATH", None)
        env["QT_QPA_PLATFORM"] = "offscreen"
        subprocess.run([str(executable), "--smoke-test"], cwd=folder, env=env,
                       check=True, timeout=120)
        info = json.loads((folder / "build-info.json").read_text(encoding="utf-8"))
        print(f"Extracted portable {info['application_version']} smoke passed in Unicode/spaced path.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
