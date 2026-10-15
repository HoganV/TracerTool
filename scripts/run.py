"""Start the source checkout, using its virtual environment when available."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    interpreter = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not interpreter.exists():
        interpreter = Path(sys.executable)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    native = root / ".venv/native/usr/lib/x86_64-linux-gnu"
    if sys.platform.startswith("linux") and native.is_dir():
        env["LD_LIBRARY_PATH"] = str(native) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    # A child interpreter starts the dynamic loader with the native-library
    # path already set, before PySide6 imports any Qt components.
    return subprocess.call([str(interpreter), "-m", "tracertool", *sys.argv[1:]], cwd=root, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
