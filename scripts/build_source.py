"""Archive an exact Git commit without private terrain or generated files."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tomllib
from zipfile import ZipFile, ZIP_DEFLATED

from check_publication import inspect_payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="HEAD")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{args.commit}^{{commit}}"], cwd=root, text=True
    ).strip()
    config = subprocess.check_output(["git", "show", f"{commit}:pyproject.toml"], cwd=root)
    version = tomllib.loads(config.decode("utf-8"))["project"]["version"]
    prefix = f"TracerTool-{version}/"
    raw = subprocess.check_output(["git", "archive", "--format=zip", commit], cwd=root)
    output = root / "dist" / f"TracerTool-{version}-source.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(io.BytesIO(raw)) as source:
        problems = [problem for entry in source.infolist() if not entry.is_dir()
                    for problem in inspect_payload(entry.filename, source.read(entry))]
    if problems:
        raise ValueError("Source snapshot is not cleared for sharing:\n" + "\n".join(problems))
    with ZipFile(io.BytesIO(raw)) as source, ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for entry in source.infolist():
            name = entry.filename
            payload = source.read(name)
            entry.filename = prefix + name
            archive.writestr(entry, payload)
        archive.writestr(prefix + "source-build-info.json", json.dumps({
            "application_version": version, "git_commit": commit,
            "built_utc": datetime.now(timezone.utc).isoformat(),
            "private_reference_inventory_omitted": True,
        }, indent=2) + "\n")
    with output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(f"Source archive: {output}\nGit commit: {commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
