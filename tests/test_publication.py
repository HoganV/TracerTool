"""Public-source checks must catch material removed only from the latest commit."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_publication.py"
spec = importlib.util.spec_from_file_location("publication_script", SCRIPT)
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


def command(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          text=True, capture_output=True).stdout


@pytest.fixture
def repository(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("Git executable is required for repository publication checks")
    root = tmp_path / "public"
    root.mkdir()
    command(root, "init", "-b", "main")
    # Use only local test-repository identity; never change the developer's Git settings.
    command(root, "config", "user.name", "Publication test")
    command(root, "config", "user.email", "test@example.invalid")
    command(root, "config", "commit.gpgsign", "false")
    for name in publication.REQUIRED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Public documentation\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nversion = "0.2.0"\n')
    package = root / "src/tracertool/__init__.py"
    package.parent.mkdir(parents=True)
    package.write_text('__version__ = "0.2.0"\n')
    command(root, "add", ".")
    command(root, "commit", "-m", "Public snapshot")
    return root


def test_clean_snapshot_and_complete_history_pass(repository):
    assert publication.audit(repository, history=True) == []


def test_deleted_private_data_is_still_rejected_in_history(repository):
    inventory = repository / "docs/input-inventory.json"
    inventory.write_text("{}\n")
    command(repository, "add", ".")
    command(repository, "commit", "-m", "Accidental inventory")
    command(repository, "rm", "docs/input-inventory.json")
    command(repository, "commit", "-m", "Remove current inventory")
    assert publication.audit(repository) == []
    assert publication.audit(repository, history=True) == [
        "history:docs/input-inventory.json: private/generated file type or location"]


def test_credential_diagnostics_do_not_echo_values(repository):
    credential = "ghp_" + "X" * 40
    (repository / "README.md").write_text(credential)
    issues = publication.audit(repository)
    assert issues == ["README.md: GitHub credential pattern"]
    assert credential not in "\n".join(issues)


def test_local_links_and_version_mismatch_are_checked(repository):
    (repository / "README.md").write_text(
        "[Missing](missing.md)\n[Private](../outside.md)\n"
        "[Web](https://example.invalid/anything)\n"
        "```md\n[An example](not-a-real-file.md)\n```\n")
    (repository / "src/tracertool/__init__.py").write_text('__version__ = "0.3.0"\n')
    issues = publication.audit(repository)
    assert len(issues) == 3
    assert any("missing local link target missing.md" in issue for issue in issues)
    assert any("link leaves" in issue for issue in issues)
    assert any("version differs" in issue for issue in issues)


def test_existing_untracked_link_is_not_considered_public(repository):
    (repository / "local.md").write_text("Not committed\n")
    (repository / "README.md").write_text("[Local](local.md)\n")
    assert publication.audit(repository) == ["README.md: link target is not tracked: local.md"]


@pytest.mark.parametrize("name", ["terrain.TIF", "line.shp", "referenceTiles/note.txt",
                                   "artifacts/demo.png", "data.tracer.json", ".env.local",
                                   "dem.tif.ovr", "dem.tif.msk", "dem.tif.aux.xml",
                                   "export.geojson", "dem.tfw"])
def test_private_files_cannot_be_tracked(name):
    assert publication.inspect_payload(name, b"") == [f"{name}: private/generated file type or location"]


def test_personal_paths_and_tile_identifiers_are_reported_without_values():
    path = "/".join(("", "home", "someone", "terrain"))
    tile = "123456" + "_" + "12345"
    issues = publication.inspect_payload("notes.md", f"{path}\n{tile}".encode())
    assert issues == ["notes.md: personal absolute path", "notes.md: private reference tile identifier"]


def test_private_identifiers_in_filenames_are_detected():
    name = "docs/images/" + "123456" + "_" + "12345" + ".png"
    assert publication.inspect_payload(name, b"public pixels") == [
        f"{name}: private reference tile identifier"]


def test_commit_tag_and_ref_metadata_are_checked(repository):
    credential = "ghp_" + "Y" * 40
    command(repository, "commit", "--allow-empty", "-m", credential)
    home = "/".join(("", "home", "someone", "private"))
    command(repository, "tag", "-a", "review", "-m", home)
    tile = "123456" + "_" + "12345"
    command(repository, "branch", tile)
    issues = publication.audit(repository, history=True)
    assert len(issues) == 3
    assert any(issue.startswith("commit:") and "credential" in issue for issue in issues)
    assert any(issue.startswith("tag:") and "personal absolute path" in issue for issue in issues)
    assert any(issue.startswith("ref:") and "tile identifier" in issue for issue in issues)
    assert credential not in "\n".join(issues) and home not in "\n".join(issues)


def test_history_requires_committed_tracked_changes(repository):
    (repository / "README.md").write_text("A changed document\n")
    assert publication.audit(repository, history=True) == [
        "History publication check requires no staged or unstaged tracked changes"]


def test_shallow_repository_cannot_claim_complete_history(repository, tmp_path):
    clone = tmp_path / "shallow"
    subprocess.run(["git", "clone", "--depth", "1", repository.as_uri(), str(clone)],
                   check=True, capture_output=True)
    assert publication.audit(clone, history=True) == [
        "History check requires a full clone; fetch all history first"]
