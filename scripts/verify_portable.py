"""Extract a portable ZIP into a fresh Unicode/spaced path and smoke-test it.

Run with the target platform's Python. Windows execution through Wine remains
compatibility-layer evidence, not clean Windows acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tempfile
from zipfile import ZipFile


def validate_inventory(archive, *, max_bytes=4 * 1024 ** 3, max_members=50000):
    """Bound and validate trusted build artifacts before extracting/executing.

    This does not authenticate downloads. Only use exact-run trusted artifacts.
    """
    members = archive.infolist()
    if len(members) > max_members or sum(item.file_size for item in members) > max_bytes:
        raise ValueError('Portable archive exceeds size/member limits.')
    seen = set()
    forbidden = ('.tif', '.tiff', '.tracer.json', '.shp', '.shx', '.dbf', '.gpkg',
                 '.geojson', '.las', '.laz', '.env', '.pem', '.key')
    for item in members:
        path = PurePosixPath(item.filename)
        raw_parts = item.filename.rstrip('/').split('/')
        reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{p}{i}' for p in ('COM', 'LPT') for i in range(1, 10)}
        if (any(part in ('', '.', '..') or part.endswith((' ', '.')) or
                part.split('.')[0].upper() in reserved for part in raw_parts)):
            raise ValueError('Portable archive contains a noncanonical extraction path.')
        key = item.filename.casefold().rstrip('/')
        if key in seen:
            raise ValueError('Portable archive contains a duplicate member.')
        seen.add(key)
        if (path.is_absolute() or '..' in path.parts or '\\' in item.filename
                or ':' in item.filename or not path.parts or path.parts[0] != 'TracerTool'):
            raise ValueError('Portable archive contains an unsafe path.')
        if stat.S_ISLNK(item.external_attr >> 16):
            raise ValueError('Portable archive contains a symlink.')
        if item.filename.lower().endswith(forbidden):
            raise ValueError('Portable archive contains terrain, project or credential data.')


def validate_provenance(info, expected_commit=None):
    if not isinstance(info, dict) or info.get('frozen_smoke_passed') is not True:
        raise ValueError('Portable build lacks a boolean passing frozen smoke test.')
    snapshot = info.get('release_snapshot')
    if not isinstance(snapshot, dict):
        raise ValueError('Portable build lacks release provenance.')
    for key in ('git_commit', 'git_tree'):
        if not isinstance(snapshot.get(key), str) or not re.fullmatch('[0-9a-f]{40}', snapshot[key]):
            raise ValueError('Portable build lacks valid commit/tree provenance.')
    files = snapshot.get('files')
    if (not isinstance(files, dict) or not files or any(
            not isinstance(k, str) or not isinstance(v, str) or not re.fullmatch('[0-9a-f]{64}', v)
            for k, v in files.items())):
        raise ValueError('Portable build lacks input file hashes.')
    if expected_commit and snapshot['git_commit'] != expected_commit:
        raise ValueError('Portable build commit does not match expected trusted commit.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument('--expected-commit', help='Require trusted build commit identity')
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
            validate_inventory(archive)
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
        info = json.loads((folder / 'build-info.json').read_text(encoding='utf-8'))
        validate_provenance(info, args.expected_commit)
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
