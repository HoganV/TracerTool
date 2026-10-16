import copy
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tracertool import project, recovery
from tracertool.project import load_project, new_feature, save_project
from tracertool.recovery import RecoveryStore
from tracertool.tracing import TraceParams


@pytest.fixture
def state(tmp_path):
    terrain = tmp_path / "terrain.tif"
    terrain.write_bytes(b"persistence fixture")
    result = SimpleNamespace(coordinates=[[1, 2, 3], [4, 5, 6]], metrics={"length": 4.2}, warnings=[], anchors=[[1, 2], [4, 5]])
    feature = new_feature("Creek α", "stream", result, TraceParams())
    settings = {"draft": {"kind": "stream", "coordinate_space": "native", "anchors": [[3, 4]],
                          "parameters": asdict(TraceParams()), "edit_target": feature["id"], "segment_range": [0, 1]}}
    return terrain, [feature], settings


@pytest.mark.parametrize("failure", ["open", "flush"])
def test_existing_unwritable_recovery_folder_is_rejected_without_residue(tmp_path, monkeypatch, failure):
    directory = tmp_path / "existing-recovery"
    directory.mkdir()
    saved = directory / "existing-record.json"
    saved.write_bytes(b"existing recovery content")

    def denied(*args, **kwargs):
        raise PermissionError("Recovery folder is not writable")

    if failure == "open":
        monkeypatch.setattr(recovery.tempfile, "NamedTemporaryFile", denied)
    else:
        monkeypatch.setattr(recovery.os, "fsync", denied)
    with pytest.raises(ValueError, match="Cannot write recovery folder"):
        RecoveryStore(directory)
    assert saved.read_bytes() == b"existing recovery content"
    assert sorted(path.name for path in directory.iterdir()) == [saved.name]


def test_recovery_write_probe_is_removed_after_success(tmp_path):
    directory = tmp_path / "sessions"
    store = RecoveryStore(directory)
    assert store.directory == directory
    assert list(directory.iterdir()) == []


def test_recovery_preserves_junctions_and_rejects_bad_evidence_atomically(tmp_path, state):
    terrain, features, settings = state
    features[0]['protected_junctions'] = [[1, 2]]
    store = RecoveryStore(tmp_path / 'sessions')
    session = str(uuid4())
    path = store.save(session, terrain, features, settings)
    before = path.read_bytes()
    terrain.unlink()
    assert store.load(path)['features'] == features
    malformed = copy.deepcopy(features)
    malformed[0]['engine_evidence'] = []
    with pytest.raises(ValueError, match='engine_evidence'):
        store.save(session, terrain, malformed, settings)
    assert path.read_bytes() == before
    document = json.loads(before)
    document['features'] = malformed
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='engine_evidence'):
        store.load(path)
    assert store.list_entries() == []


def test_schema2_recovery_keeps_engine_diagnostics_and_draft_selection(tmp_path, state):
    terrain, features, settings = state
    features[0].update(engine='stream_auto', engine_version=1)
    features[0]['metrics'].update(engine='stream_auto', engine_version=1, status='stale',
                                  evidence_stale=True, diagnostics=[{'code': 'fork', 'message': 'Inspect fork'}])
    features[0]['engine_evidence'] = {'engine': 'stream_auto', 'engine_version': 1, 'stale': True,
                                    'metrics': {'status': 'ambiguous', 'effective_config': {'scale': 12}}}
    settings['stream_engine'] = 'stream_auto'
    settings['draft'].update(engine='stream_auto', engine_version=1)
    before = copy.deepcopy((features, settings))
    store = RecoveryStore(tmp_path / 'sessions')
    path = store.save(str(uuid4()), terrain, features, settings)
    assert json.loads(path.read_text())['version'] == 2
    recovered = store.load(path)
    assert (recovered['features'], recovered['settings']) == before
    assert (features, settings) == before


def test_schema1_recovery_migrates_engine_without_changing_xyz(tmp_path, state):
    store = RecoveryStore(tmp_path / 'sessions')
    path = store.save(str(uuid4()), *state)
    document = json.loads(path.read_text())
    document['version'] = 1
    for line in document['features']:
        line.pop('engine', None)
        line.pop('engine_version', None)
    path.write_text(json.dumps(document))
    original = path.read_bytes()
    recovered = store.load(path)
    assert recovered['version'] == 2
    assert recovered['features'][0]['engine'] == 'legacy'
    assert recovered['features'][0]['engine_version'] == 1
    assert recovered['features'][0]['coordinates'] == state[1][0]['coordinates']
    assert path.read_bytes() == original
    assert len(store.list_entries()) == 1


def test_recovery_roundtrip_with_draft_and_missing_source(tmp_path, state):
    terrain, features, settings = state
    store = RecoveryStore(tmp_path / "sessions")
    session = str(uuid4())
    saved = tmp_path / "explicit.tracer.json"
    path = store.save(session, terrain, features, settings, saved)
    terrain.unlink()
    recovered = store.load(path)
    assert recovered["features"] == features
    assert recovered["settings"] == settings
    assert recovered["project_path"] == str(saved)
    assert recovered["terrain_path"] == str(terrain)
    assert recovered["missing_terrain"] is True
    assert recovered["recovery"]["session_id"] == session
    assert store.list_entries()[0]["draft_anchor_count"] == 1
    assert store.list_entries()[0]["feature_count"] == 1


@pytest.mark.parametrize("line_smoothing", [None, 4.5])
def test_recovery_preserves_legacy_and_new_line_smoothing(tmp_path, state, line_smoothing):
    terrain, features, settings = state
    for parameters in (features[0]["parameters"], settings["draft"]["parameters"]):
        if line_smoothing is None:
            parameters.pop("line_smoothing", None)
        else:
            parameters["line_smoothing"] = line_smoothing
    before_features, before_settings = copy.deepcopy(features), copy.deepcopy(settings)
    store = RecoveryStore(tmp_path / "sessions")
    path = store.save(str(uuid4()), terrain, features, settings)
    recovered = store.load(path)
    assert recovered["features"] == before_features
    assert recovered["settings"] == before_settings
    assert recovered["features"][0]["parameters"].get("line_smoothing", 0) == (line_smoothing or 0)


def test_autosave_never_modifies_saved_project_or_creates_project_backup(tmp_path, state):
    terrain, features, settings = state
    saved = tmp_path / "explicit.tracer.json"
    save_project(saved, terrain, features, {})
    original = saved.read_bytes()
    store = RecoveryStore(tmp_path / "sessions")
    session = str(uuid4())
    store.save(session, terrain, features, settings, saved)
    features[0]["name"] = "Unsaved edits"
    store.save(session, terrain, features, settings, saved)
    assert saved.read_bytes() == original
    assert not saved.with_name(saved.name + ".bak").exists()
    assert len(store.list_entries()) == 1


def test_atomic_autosave_failure_keeps_previous_snapshot(tmp_path, state, monkeypatch):
    store = RecoveryStore(tmp_path / "sessions")
    session = str(uuid4())
    path = store.save(session, *state)
    original = path.read_bytes()
    real_replace = project.os.replace

    def fail_commit(source, target):
        if Path(target) == path:
            raise PermissionError("recovery file locked")
        return real_replace(source, target)

    monkeypatch.setattr(project.os, "replace", fail_commit)
    with pytest.raises(ValueError, match="locked"):
        store.save(session, state[0], [], {})
    assert path.read_bytes() == original
    assert not list(store.directory.glob("*.tmp"))


def test_invalid_state_cannot_replace_recovery(tmp_path, state):
    store = RecoveryStore(tmp_path / "sessions")
    session = str(uuid4())
    path = store.save(session, *state)
    original = path.read_bytes()
    bad = copy.deepcopy(state[2])
    bad["draft"]["anchors"][0][0] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        store.save(session, state[0], state[1], bad)
    assert path.read_bytes() == original


def test_listing_ignores_corrupt_and_incomplete_records(tmp_path, state):
    store = RecoveryStore(tmp_path / "sessions")
    valid = store.save(str(uuid4()), *state)
    (store.directory / (str(uuid4()) + ".recovery.json")).write_text("{interrupted")
    malformed = json.loads(valid.read_text())
    malformed["recovery"]["updated_at"] = "not a timestamp"
    (store.directory / (str(uuid4()) + ".recovery.json")).write_text(json.dumps(malformed))
    (store.directory / "not-a-session.recovery.json").write_bytes(valid.read_bytes())
    (store.directory / ".incomplete.tmp").write_text("partial")
    assert [entry["path"] for entry in store.list_entries()] == [str(valid)]


def test_sessions_are_sorted_and_discard_is_isolated(tmp_path, state):
    store = RecoveryStore(tmp_path / "sessions")
    first, second = str(uuid4()), str(uuid4())
    first_path = store.save(first, *state)
    second_path = store.save(second, *state)
    assert [entry["session_id"] for entry in store.list_entries()] == [second, first]
    store.discard(first)
    store.discard(first)  # Discard is idempotent.
    assert not first_path.exists() and second_path.exists()
    assert [entry["session_id"] for entry in store.list_entries()] == [second]


@pytest.mark.parametrize("session", ["../elsewhere", "bad", "", "00000000000000000000000000000000", None])
def test_session_names_cannot_escape_store(tmp_path, state, session):
    store = RecoveryStore(tmp_path / "sessions")
    with pytest.raises(ValueError, match="UUID"):
        store.save(session, *state)
    with pytest.raises(ValueError, match="UUID"):
        store.discard(session)
    assert not list(store.directory.iterdir())


def test_recovery_cannot_load_an_outside_file(tmp_path, state):
    store = RecoveryStore(tmp_path / "sessions")
    other = RecoveryStore(tmp_path / "other")
    path = other.save(str(uuid4()), *state)
    with pytest.raises(ValueError, match="inside this recovery folder"):
        store.load(path)


def test_saved_project_at_recovery_filename_is_not_overwritten_or_deleted(tmp_path, state):
    store = RecoveryStore(tmp_path / "sessions")
    session = str(uuid4())
    path = store.directory / (session + ".recovery.json")
    save_project(path, *state)
    original = path.read_bytes()
    with pytest.raises(ValueError, match="another project"):
        store.save(session, *state)
    with pytest.raises(ValueError, match="saved project"):
        store.discard(session)
    assert path.read_bytes() == original
    assert store.list_entries() == []


def test_recovery_rejects_symlink_entries(tmp_path, state):
    store = RecoveryStore(tmp_path / "sessions")
    outside = tmp_path / "saved.tracer.json"
    save_project(outside, *state)
    original = outside.read_bytes()
    session = str(uuid4())
    link = store.directory / (session + ".recovery.json")
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("This platform does not permit creating test symlinks")
    for action in (lambda: store.load(link), lambda: store.discard(session), lambda: store.save(session, *state)):
        with pytest.raises(ValueError, match="symbolic link"):
            action()
    assert store.list_entries() == []
    assert outside.read_bytes() == original


def test_recovery_can_save_when_terrain_moved_during_session(tmp_path, state):
    store = RecoveryStore(tmp_path / "sessions")
    state[0].unlink()
    path = store.save(str(uuid4()), *state)
    assert store.load(path)["missing_terrain"] is True
