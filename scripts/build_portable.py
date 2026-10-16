"""Build a native portable folder, provenance manifest, notices and ZIP.

Run on Windows for Windows binaries. Does not install packages or publish.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tomllib


def collect_notices(destination: Path) -> None:
    notices = destination / "third-party-licenses"
    notices.mkdir(exist_ok=True)
    manifest = []
    # Record the full build environment, including development/build tooling.
    # Keep original filenames/text; do not substitute our own license summaries.
    for dist in sorted(metadata.distributions(), key=lambda item: item.metadata.get("Name", "").lower()):
        name = dist.metadata.get("Name", "unknown")
        entry = {"name": name, "version": dist.version, "license_expression": dist.metadata.get("License-Expression"),
                 "homepage": dist.metadata.get("Home-page"), "license_files": []}
        for item in dist.files or []:
            lowered = str(item).lower()
            if any(part in lowered for part in ("license", "licence", "copying", "copyright", "notice")):
                source = Path(dist.locate_file(item))
                if source.is_file() and source.suffix.lower() not in (".pyc", ".so", ".dll", ".pyd", ".py"):
                    relative = Path(*[part for part in Path(str(item)).parts if part not in ("..", ".")])
                    target = notices / name / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    entry["license_files"].append(str(target.relative_to(destination)))
        manifest.append(entry)
    (destination / "dependency-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, notices / "CPython-LICENSE.txt")


def source_hashes(root: Path) -> dict[str, str]:
    return {source.relative_to(root).as_posix(): hashlib.sha256(source.read_bytes()).hexdigest()
            for source in sorted((root / "src").rglob("*.py"))}


def release_snapshot(root: Path) -> dict:
    """Attribute all tracked build inputs without recording machine paths."""
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
    files = git('ls-files').splitlines()
    return {'git_commit': git('rev-parse', 'HEAD'),
            'git_tree': git('rev-parse', 'HEAD^{tree}'),
            'files': {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                      for name in files if (root / name).is_file()},
            'workflow_run_id': os.environ.get('GITHUB_RUN_ID')}


def require_clean_source(root: Path) -> None:
    state = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'],
                                    cwd=root, text=True)
    if state.strip():
        raise ValueError('Release builds require a clean committed source checkout.')
    # Untracked Python can enter PyInstaller discovery even though absent from Git.
    untracked = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard',
                                        '--', 'src', 'scripts'], cwd=root, text=True)
    if untracked.strip():
        raise ValueError('Release builds require clean source/build inputs without untracked files.')


def collect_documentation(root: Path, destination: Path, *, tracked=None) -> None:
    for name in ("LICENSE", "README.md", "CHANGELOG.md", "AI_DISCLOSURE.md",
                 "CONTRIBUTING.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(root / name, destination / name)
    if tracked is None:
        tracked = subprocess.check_output(['git', 'ls-files', '--', 'docs'], cwd=root,
                                          text=True).splitlines()
    for name in sorted(tracked):
        if not name.startswith('docs/') or name.endswith('input-inventory.json'):
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-smoke", action="store_true", help="Build only; resulting ZIP is not smoke-tested")
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"), help="Output directory relative to the checkout")
    parser.add_argument("--work-dir", type=Path, default=Path("build"), help="Temporary PyInstaller directory relative to the checkout")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    require_clean_source(root)
    snapshot = source_hashes(root)
    release_inputs = release_snapshot(root)
    dist_dir = (root / args.dist_dir).resolve()
    work_dir = (root / args.work_dir).resolve()
    build_env = os.environ.copy()
    native = root / ".venv/native/usr/lib/x86_64-linux-gnu"
    if sys.platform.startswith("linux") and native.is_dir():
        build_env["LD_LIBRARY_PATH"] = str(native) + os.pathsep + build_env.get("LD_LIBRARY_PATH", "")
    subprocess.run([sys.executable, "-m", "PyInstaller", str(root / "scripts/tracertool.spec"),
                    "--clean", "--noconfirm", "--distpath", str(dist_dir),
                    "--workpath", str(work_dir)], cwd=root, env=build_env, check=True)
    folder = dist_dir / "TracerTool"
    collect_documentation(root, folder)
    collect_notices(folder)
    local_notices = root / ".venv/native/usr/share/doc"
    if sys.platform.startswith("linux") and local_notices.is_dir():
        shutil.copytree(local_notices, folder / "third-party-licenses/native-system-packages", dirs_exist_ok=True)
    versions = "\n".join(sorted(f"{dist.metadata.get('Name', 'unknown')}=={dist.version}"
                                  for dist in metadata.distributions())) + "\n"
    (folder / "build-environment.txt").write_text(versions, encoding="utf-8")
    executable = folder / ("TracerTool.exe" if os.name == "nt" else "TracerTool")
    if not args.skip_smoke:
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        subprocess.run([str(executable), "--smoke-test"], cwd=folder, env=env, check=True, timeout=120)
    with (root / "pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    if snapshot != source_hashes(root):
        raise RuntimeError("Application source changed during packaging. Rebuild a stable snapshot before creating a release ZIP.")
    if release_inputs != release_snapshot(root):
        raise RuntimeError('Tracked build inputs changed during packaging. Rebuild a stable snapshot.')
    require_clean_source(root)
    info = {"application_version": version, "built_utc": datetime.now(timezone.utc).isoformat(),
            "python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
            "wine_build_environment": bool(os.environ.get("WINEPREFIX")),
            "frozen_smoke_passed": not args.skip_smoke, "source_sha256": snapshot,
            "release_snapshot": release_inputs}
    (folder / "build-info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    name = f"TracerTool-{version}-{platform.system().lower()}-{platform.machine().lower()}-portable"
    archive = Path(shutil.make_archive(str(dist_dir / name), "zip", root_dir=dist_dir, base_dir="TracerTool"))
    with archive.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"Portable archive: {archive}")
    print(f"Packaged smoke test: {'SKIPPED' if args.skip_smoke else 'passed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
