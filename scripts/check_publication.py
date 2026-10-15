"""Check tracked public source, local documentation links, and optional Git history.

This is a project-specific guard, not a comprehensive secret or license audit.
Diagnostics name files and rules without echoing potentially sensitive values.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path, PurePosixPath
import re
import subprocess
import tomllib
from urllib.parse import unquote, urlsplit


REQUIRED = (
    "README.md", "LICENSE", "AI_DISCLOSURE.md", "CONTRIBUTING.md", "SECURITY.md",
    "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "docs/USER_GUIDE.md",
    "docs/BUILDING.md", "docs/PUBLISHING.md", ".github/workflows/ci.yml",
)
PRIVATE_DIRS = {"referencetiles", "artifacts", "build", "dist", ".venv", "__pycache__"}
PRIVATE_SUFFIXES = (
    ".tif", ".tiff", ".tracer.json", ".tracer.json.bak", ".shp", ".shx", ".dbf",
    ".prj", ".cpg", ".gpkg", ".las", ".laz", ".zip", ".exe", ".dll", ".so",
    ".dylib", ".pyc", ".log", ".bak", ".pem", ".key", ".geojson", ".ovr",
    ".msk", ".aux.xml", ".tfw", ".tfwx", ".wld", ".qix", ".sbn", ".sbx",
)
PATTERNS = {
    "private-key material": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub credential pattern": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})"),
    "cloud credential pattern": re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    "API credential pattern": re.compile(rb"sk-(?:proj-|svcacct-)[A-Za-z0-9_-]{35,}"),
    "personal absolute path": re.compile(rb"(?:/home/|/Users/)[A-Za-z0-9_.-]+/|[A-Za-z]:[\\/]Users[\\/][A-Za-z0-9_.-]+[\\/]"),
    "private reference tile identifier": re.compile(rb"\b[0-9]{6}_[0-9]{5}\b"),
}
LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)")


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


def inspect_payload(name: str, payload: bytes) -> list[str]:
    path = PurePosixPath(name)
    low = name.lower()
    issues = []
    if (any(part.lower() in PRIVATE_DIRS for part in path.parts)
            or low.endswith(PRIVATE_SUFFIXES)
            or path.name.lower() in {"input-inventory.json", "id_rsa", "id_ed25519"}
            or (path.name.startswith(".env") and path.name != ".env.example")):
        issues.append(f"{name}: private/generated file type or location")
    if len(payload) > 10 * 1024 * 1024:
        issues.append(f"{name}: tracked file exceeds the project's 10 MiB source limit")
    # Binary images are inspected for signatures as well; this cannot establish
    # that their pixels are public, which still requires visual/provenance review.
    for description, pattern in PATTERNS.items():
        if pattern.search(name.encode("utf-8")) or pattern.search(payload):
            issues.append(f"{name}: {description}")
    return issues


def check_links(root: Path, name: str, payload: bytes, tracked: set[str]) -> list[str]:
    if not name.endswith(".md"):
        return []
    # Literal example links inside fenced code blocks are not document links.
    content = re.sub(r"(?ms)^```.*?^```[^\n]*$", "", payload.decode("utf-8"))
    issues = []
    for match in LINK.finditer(content):
        target = match.group(1).strip("<>")
        parts = urlsplit(target)
        if parts.scheme or target.startswith(("#", "//")):
            continue
        location = (root / name).parent / unquote(parts.path)
        resolved = location.resolve()
        if not resolved.is_relative_to(root):
            issues.append(f"{name}: local documentation link leaves the public repository")
        elif not resolved.exists():
            issues.append(f"{name}: missing local link target {parts.path}")
        elif resolved.is_file() and resolved.relative_to(root).as_posix() not in tracked:
            issues.append(f"{name}: link target is not tracked: {parts.path}")
    return issues


def audit(root: Path, *, history: bool = False) -> list[str]:
    root = root.resolve()
    names = {p.decode("utf-8") for p in git(root, "ls-files", "-z").split(b"\0") if p}
    issues = [f"Missing required public file: {name}" for name in REQUIRED if name not in names]
    for name in sorted(names):
        path = root / name
        if path.is_symlink():
            issues.append(f"{name}: tracked symlink requires manual publication review")
            continue
        if not path.is_file():
            issues.append(f"{name}: tracked file is missing from checkout")
            continue
        payload = path.read_bytes()
        issues.extend(inspect_payload(name, payload))
        issues.extend(check_links(root, name, payload, names))
    try:
        version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        tree = ast.parse((root / "src/tracertool/__init__.py").read_text(encoding="utf-8"))
        app_version = next(ast.literal_eval(node.value) for node in tree.body
                           if isinstance(node, ast.Assign) and any(
                               isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets))
        if version != app_version:
            issues.append("Application version differs between package metadata and source")
    except (OSError, ValueError, KeyError, StopIteration, SyntaxError) as exc:
        issues.append(f"Cannot verify application version: {type(exc).__name__}")
    if history:
        for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
            state = subprocess.run(["git", "-C", str(root), *arguments],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if state.returncode == 1:
                issues.append("History publication check requires no staged or unstaged tracked changes")
            elif state.returncode != 0:
                raise subprocess.CalledProcessError(state.returncode, state.args)
        if git(root, "rev-parse", "--is-shallow-repository").strip() == b"true":
            issues.append("History check requires a full clone; fetch all history first")
        # Inspect each unique path/blob pair from every reachable commit, even
        # if a sensitive file was deleted later. Never print blob contents.
        seen = set()
        commits = git(root, "rev-list", "--all").splitlines()
        if not commits:
            issues.append("History check requires at least one committed public snapshot")
        for commit in commits:
            commit_id = commit.decode()
            issues.extend(inspect_payload(f"commit:{commit_id}", git(root, "cat-file", "commit", commit_id)))
            for entry in git(root, "ls-tree", "-rz", commit.decode()).split(b"\0"):
                if not entry:
                    continue
                metadata, filename = entry.split(b"\t", 1)
                mode, kind, oid = metadata.split()
                name = filename.decode("utf-8")
                pair = (name, oid)
                if pair in seen:
                    continue
                seen.add(pair)
                if kind != b"blob" or mode == b"120000":
                    issues.append(f"history:{name}: linked repository or symlink requires review")
                    continue
                payload = git(root, "cat-file", "blob", oid.decode())
                issues.extend("history:" + issue for issue in inspect_payload(name, payload))
        # Annotated tag messages are public metadata too; lightweight tags are
        # covered by commit traversal. Ref names may also contain private labels.
        for ref in git(root, "for-each-ref", "--format=%(objecttype) %(objectname) %(refname)").splitlines():
            kind, oid, name = ref.split(b" ", 2)
            issues.extend(inspect_payload(f"ref:{oid.decode()}", name))
            if kind == b"tag":
                issues.extend(inspect_payload(f"tag:{oid.decode()}", git(root, "cat-file", "tag", oid.decode())))
    return sorted(set(issues))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--history", action="store_true", help="Inspect all reachable Git history as well as tracked files")
    args = parser.parse_args()
    try:
        issues = audit(args.root, history=args.history)
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        print(f"Publication check could not run: {type(exc).__name__}")
        return 2
    if issues:
        print("Publication check failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("Publication checks passed: tracked files, local links, versions" +
          (", and all reachable Git history." if args.history else "."))
    print("This guard does not replace a secret scan, image/data provenance review, or license audit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
