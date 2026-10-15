"""Run Windows Python or a Windows executable in the local Wine build sandbox.

Toolchain binaries live under ignored build/windows-toolchain, never in a
release. This provides compatibility-layer validation, not Windows acceptance.
Usage: python scripts/wine_run.py -- -m pip --version
       python scripts/wine_run.py --program dist/windows/TracerTool/TracerTool.exe -- --smoke-test
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    toolchain = root / "build/windows-toolchain"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, default=toolchain / "python/python.exe")
    parser.add_argument("--log", type=Path, help="Record combined output while preserving pipe-backed Windows standard handles")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    wine_root = toolchain / "winehq/opt/wine-stable"
    wine = wine_root / "bin/wine"
    if not wine.exists() or not args.program.exists():
        parser.error("Local Wine toolchain or chosen Windows executable is missing; see docs/BUILDING.md.")
    native = toolchain / "wine/usr/lib/x86_64-linux-gnu"
    env = os.environ.copy()
    env.update(WINEPREFIX=str(toolchain / "prefix11"), WINEARCH="win64",
               WINEDEBUG=os.environ.get("WINEDEBUG", "-all"),
               WINEDLLOVERRIDES="mscoree,mshtml=;winedbg.exe=d",
               PYTHONLEGACYWINDOWSSTDIO="1", PYTHONIOENCODING="utf-8",
               WINEDLLPATH=str(wine_root / "lib/wine"),
               LD_LIBRARY_PATH=str(native) + os.pathsep + str(wine_root / "lib/wine/x86_64-unix"))
    arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    command = [str(wine), str(args.program.resolve()), *arguments]
    if args.log is None:
        return subprocess.call(command, cwd=root, env=env)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors="replace")
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
        return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
