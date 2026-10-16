import copy
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from rasterio.crs import CRS
import shapefile

from tracertool import project


@dataclass
class Params:
    corridor: float = 30
    smoothing: float = 1.2
    terrain_weight: float = 8
    spacing: float = 3
    simplify: float = 0.5


@dataclass
class SmoothParams(Params):
    line_smoothing: float = 4


@dataclass
class RelaxedParams(Params):
    line_smoothing: float = 0
    relax_anchors: bool = True


@pytest.fixture
def feature():
    result = SimpleNamespace(
        coordinates=[[500000.0, 4500000.0, 212.4], [500003.0, 4500004.0, 211.7], [500006.0, 4500008.0, 211.0]],
        metrics={"length": 10.0, "nested": {"source": "test terrain"}},
        warnings=["Check the road crossing."],
    )
    return project.new_feature("Creek α", "stream", result, Params())


@pytest.fixture
def terrain_file(tmp_path):
    terrain = tmp_path / "terrain" / "sample.tif"
    terrain.parent.mkdir()
    terrain.write_bytes(b"fixture: persistence does not read raster contents")
    return terrain


@pytest.mark.parametrize('field,value', [
    ('engine_evidence', []), ('engine_evidence', {'metrics': []}),
    ('engine_evidence', {'warnings': 'bad'}),
    ('engine_evidence', {'stale': 'yes'}),
    ('engine_evidence', {'engine': 'stream_auto', 'engine_version': 1}),
    ('metrics', {'engine': 'stream_auto'}),
    ('metrics', {'engine_version': 2}),
    ('metrics', {'diagnostics': {}}),
    ('metrics', {'diagnostics': ['bad']}),
    ('metrics', {'diagnostics': [{'code': 3, 'message': 'bad'}]}),
    ('metrics', {'diagnostics': [{'code': 'bad', 'message': 'bad', 'location': [1]}]}),
    ('engine_evidence', {'metrics': {'diagnostics': [None]}}),
    ('protected_junctions', [[1, 2]]),
    ('protected_junctions', 'bad'),
])
def test_invalid_engine_and_junction_metadata_rejected_on_save_and_load(tmp_path, terrain_file, feature, field, value):
    path = tmp_path / 'invalid-metadata.json'
    project.save_project(path, terrain_file, [feature], {})
    document = json.loads(path.read_text())
    feature[field] = value
    with pytest.raises(ValueError, match='engine|diagnostic|protected'):
        project.save_project(path, terrain_file, [feature], {})
    document['features'][0][field] = value
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='engine|diagnostic|protected'):
        project.load_project(path)


def test_project_round_trip_relative_path(tmp_path, terrain_file, feature):
    destination = tmp_path / "example.tracer.json"
    feature["visible"] = False
    settings = {"style": "Hillshade", "opacity": 0.4, "camera": [1, 2, 3]}
    project.save_project(destination, terrain_file, [feature], settings)
    saved = json.loads(destination.read_text())
    assert saved["version"] == 2
    assert saved["terrain_path"] == (Path("terrain") / "sample.tif").as_posix()
    loaded = project.load_project(destination)
    assert loaded["terrain_path"] == str(terrain_file.resolve())
    assert loaded["features"] == [feature]
    assert loaded["settings"] == settings
    assert not list(tmp_path.glob("*.tmp"))


def test_schema1_migrates_legacy_identity_without_retracing(tmp_path, terrain_file, feature):
    path = tmp_path / "legacy.json"
    old = copy.deepcopy(feature)
    old.pop("engine", None)
    old.pop("engine_version", None)
    document = {"format": project.PROJECT_FORMAT, "version": 1,
                "terrain_path": str(terrain_file), "features": [old], "settings": {}}
    path.write_text(json.dumps(document))
    original = path.read_bytes()
    loaded = project.load_project(path)
    assert loaded["version"] == 2
    assert loaded["features"][0] == {**old, "engine": "legacy", "engine_version": 1}
    assert path.read_bytes() == original
    project.save_project(path, terrain_file, loaded["features"], loaded["settings"])
    assert json.loads(path.read_text())["version"] == 2
    assert project.load_project(path)["features"][0]["coordinates"] == old["coordinates"]


def test_schema1_explicit_unknown_engine_is_not_downgraded(tmp_path, terrain_file, feature):
    feature.update(engine='future', engine_version=42)
    path = tmp_path / 'future-v1.json'
    path.write_text(json.dumps({'format': project.PROJECT_FORMAT, 'version': 1,
                               'terrain_path': str(terrain_file), 'features': [feature], 'settings': {}}))
    loaded = project.load_project(path)['features'][0]
    assert loaded['engine'] == 'future'
    assert loaded['engine_version'] == 42
    with pytest.raises(ValueError, match='Unsupported.*engine'):
        project.require_supported_engine(loaded)


def test_project_moves_with_terrain(tmp_path, terrain_file, feature):
    destination = tmp_path / "example.tracer.json"
    project.save_project(destination, terrain_file, [feature], {})
    moved = tmp_path / "moved"
    moved.mkdir()
    terrain_file.parent.rename(moved / "terrain")
    destination.rename(moved / destination.name)
    loaded = project.load_project(moved / destination.name)
    assert loaded["terrain_path"] == str(moved / "terrain" / "sample.tif")


def test_empty_project_can_be_saved(tmp_path, terrain_file):
    destination = tmp_path / "empty.json"
    project.save_project(destination, terrain_file, [], {})
    assert project.load_project(destination)["features"] == []


@pytest.mark.parametrize("engine,version", [("stream_auto", 1), ("legacy", 1)])
def test_new_feature_derives_engine_from_result(engine, version):
    result = SimpleNamespace(coordinates=[[0, 0, 2], [1, 1, 1]],
                             metrics={"engine": engine, "engine_version": version}, warnings=[])
    line = project.new_feature("Engine", "stream", result, Params())
    assert (line["engine"], line["engine_version"]) == (engine, version)
    result.metrics.clear()
    assert line["metrics"]["engine"] == engine


def test_new_feature_defaults_to_legacy(feature):
    assert (feature["engine"], feature["engine_version"]) == ("legacy", 1)


def test_new_feature_detaches_result_data():
    result = SimpleNamespace(coordinates=[(0.0, 0.0, 1.0), (1.0, 2.0, 3.0)], metrics={"a": [1]}, warnings=["a"])
    feature = project.new_feature("test", "manual", result, Params())
    result.metrics["a"].append(2)
    result.warnings.append("b")
    assert feature["metrics"] == {"a": [1]}
    assert feature["warnings"] == ["a"]
    assert feature["coordinates"][0] == [0.0, 0.0, 1.0]


@pytest.mark.parametrize("kind", ["ridge", "stream", "slope_break", "manual"])
def test_line_smoothing_roundtrip_in_feature_and_draft(tmp_path, terrain_file, kind):
    params = SmoothParams(spacing=8, line_smoothing=4.5)
    result = SimpleNamespace(coordinates=[[1, 2, 3], [4, 5, 6]], metrics={}, warnings=[],
                             anchors=[[1, 2], [4, 5]])
    line = project.new_feature("Smooth line", kind, result, params)
    settings = {"draft": {"kind": kind, "anchors": [[2, 3]], "parameters": asdict(params)}}
    destination = tmp_path / "smooth.tracer.json"
    project.save_project(destination, terrain_file, [line], settings)
    loaded = project.load_project(destination)
    assert loaded["version"] == 2
    assert loaded["features"] == [line]
    assert loaded["features"][0]["parameters"]["line_smoothing"] == 4.5
    assert loaded["settings"] == settings


def test_legacy_parameters_stay_absent_without_new_defaults(tmp_path, terrain_file, feature):
    assert "line_smoothing" not in feature["parameters"]
    settings = {"draft": {"kind": "stream", "anchors": [[2, 3]], "parameters": asdict(Params())}}
    destination = tmp_path / "legacy.tracer.json"
    project.save_project(destination, terrain_file, [feature], settings)
    loaded = project.load_project(destination)
    assert loaded["features"][0]["parameters"] == asdict(Params())
    assert loaded["settings"]["draft"]["parameters"] == asdict(Params())
    assert loaded["features"][0]["parameters"].get("line_smoothing", 0) == 0
    assert "relax_anchors" not in loaded["features"][0]["parameters"]
    assert "relax_anchors" not in loaded["settings"]["draft"]["parameters"]
    assert "fixed_anchor_indices" not in loaded["settings"]["draft"]
    assert loaded["features"][0]["coordinates"] == feature["coordinates"]


@pytest.mark.parametrize("relaxed", [True, False])
def test_relaxed_draft_roundtrip_moves_with_source_and_exports(tmp_path, terrain_file, relaxed):
    params = RelaxedParams(corridor=100_000_000, relax_anchors=relaxed)
    result = SimpleNamespace(coordinates=[[500000, 4500000, 10], [500005, 4500005, 9]],
                             anchors=[[500001, 4500001], [500006, 4500006]], fixed_anchor_indices=[1],
                             metrics={}, warnings=[])
    line = project.new_feature("Rough guides", "stream", result, params)
    original = copy.deepcopy(line)
    settings = {"draft": {"kind": "stream", "anchors": result.anchors,
                           "fixed_anchor_indices": [1], "parameters": asdict(params)}}
    path = tmp_path / "rough.tracer.json"
    project.save_project(path, terrain_file, [line], settings)
    moved = tmp_path / "moved"
    moved.mkdir()
    terrain_file.parent.rename(moved / "terrain")
    path.rename(moved / path.name)
    loaded = project.load_project(moved / path.name)
    assert loaded["version"] == 2
    assert loaded["terrain_path"] == str(moved / "terrain" / "sample.tif")
    assert loaded["features"] == [original]
    assert loaded["settings"] == settings
    project.export_geojson(moved / "rough.geojson", loaded["features"], "EPSG:26915")
    exported = json.loads((moved / "rough.geojson").read_text())["features"][0]
    assert exported["geometry"]["coordinates"] == original["coordinates"]
    assert exported["properties"]["parameters"] == asdict(params)
    assert exported["properties"]["fixed_anchor_indices"] == [1]
    project.export_shapefile(moved / "rough.shp", loaded["features"], "EPSG:26915")
    with shapefile.Reader(str(moved / "rough.shp")) as reader:
        shape = reader.shape(0)
        assert [list(xy) + [z] for xy, z in zip(shape.points, shape.z)] == original["coordinates"]
        assert reader.record(0).as_dict()["corr_px"] == params.corridor


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}, float("nan")])
@pytest.mark.parametrize("location", ["feature", "draft"])
def test_invalid_relax_anchors_rejected_on_save_and_load(tmp_path, terrain_file, feature, value, location):
    path = tmp_path / "good.tracer.json"
    project.save_project(path, terrain_file, [feature], {})
    original = path.read_bytes()
    settings = {}
    if location == "feature":
        feature["parameters"]["relax_anchors"] = value
    else:
        settings["draft"] = {"kind": "stream", "anchors": [[2, 3]],
                             "parameters": {**asdict(Params()), "relax_anchors": value}}
    with pytest.raises(ValueError, match="relax_anchors"):
        project.save_project(path, terrain_file, [feature], settings)
    assert path.read_bytes() == original
    document = json.loads(original)
    document.update(features=[feature], settings=settings)
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="relax_anchors"):
        project.load_project(path)


@pytest.mark.parametrize("indices", [[], [0], [1], [1, 0]])
def test_valid_fixed_anchor_indices_roundtrip(tmp_path, terrain_file, indices):
    settings = {"draft": {"kind": "stream", "anchors": [[2, 3], [4, 5]],
                           "fixed_anchor_indices": indices}}
    path = tmp_path / "draft.tracer.json"
    project.save_project(path, terrain_file, [], settings)
    assert project.load_project(path)["settings"] == settings


@pytest.mark.parametrize("indices", [None, "0", 0, [True], [0.0], [-1], [2], [0, 0], [[0]], [{}]])
def test_invalid_fixed_anchor_indices_cannot_replace_project(tmp_path, terrain_file, indices):
    path = tmp_path / "draft.tracer.json"
    project.save_project(path, terrain_file, [], {})
    original = path.read_bytes()
    settings = {"draft": {"kind": "stream", "anchors": [[2, 3], [4, 5]],
                           "fixed_anchor_indices": indices}}
    with pytest.raises(ValueError, match="fixed_anchor_indices"):
        project.save_project(path, terrain_file, [], settings)
    assert path.read_bytes() == original
    document = json.loads(original)
    document["settings"] = settings
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="fixed_anchor_indices"):
        project.load_project(path)


@pytest.mark.parametrize("indices", [None, [True], [0.0], [-1], [2], [0, 0], [[0]]])
def test_invalid_feature_fixed_anchor_indices_rejected(tmp_path, terrain_file, feature, indices):
    feature["anchors"] = [point[:2] for point in feature["coordinates"][:2]]
    feature["fixed_anchor_indices"] = indices
    with pytest.raises(ValueError, match="fixed_anchor_indices"):
        project.save_project(tmp_path / "draft.tracer.json", terrain_file, [feature], {})


def test_fixed_feature_indices_require_existing_guides(tmp_path, terrain_file, feature):
    feature["fixed_anchor_indices"] = [0]
    with pytest.raises(ValueError, match="fixed_anchor_indices"):
        project.save_project(tmp_path / "draft.tracer.json", terrain_file, [feature], {})


@pytest.mark.parametrize("radius", [1, 10_000, 1e200])
def test_search_radius_has_no_artificial_project_cap(tmp_path, terrain_file, feature, radius):
    feature["parameters"]["corridor"] = radius
    path = tmp_path / "radius.tracer.json"
    project.save_project(path, terrain_file, [feature], {})
    assert project.load_project(path)["features"] == [feature]


@pytest.mark.parametrize("radius", [0.5, 0, -1, True, float("inf"), float("nan")])
def test_invalid_search_radius_rejected(tmp_path, terrain_file, feature, radius):
    feature["parameters"]["corridor"] = radius
    with pytest.raises(ValueError, match="corridor"):
        project.save_project(tmp_path / "radius.tracer.json", terrain_file, [feature], {})


@pytest.mark.parametrize("value", [-1, 51, True, "4", None, float("nan"), float("inf"), 10 ** 1000])
@pytest.mark.parametrize("location", ["feature", "draft"])
def test_invalid_line_smoothing_preserves_saved_project(tmp_path, terrain_file, feature, value, location):
    destination = tmp_path / "good.tracer.json"
    project.save_project(destination, terrain_file, [feature], {})
    original = destination.read_bytes()
    settings = {}
    if location == "feature":
        feature["parameters"]["line_smoothing"] = value
    else:
        settings["draft"] = {"kind": "stream", "anchors": [[2, 3]],
                             "parameters": {**asdict(Params()), "line_smoothing": value}}
    with pytest.raises(ValueError, match="line_smoothing"):
        project.save_project(destination, terrain_file, [feature], settings)
    assert destination.read_bytes() == original


@pytest.mark.parametrize("modify, message", [
    (lambda f: f.update(coordinates=[]), "two XYZ"),
    (lambda f: f["coordinates"][0].__setitem__(2, float("nan")), "non-finite"),
    (lambda f: f["coordinates"][0].__setitem__(0, True), "finite number"),
    (lambda f: f.update(coordinates=[[0, 0, 1], [0, 0, 2]]), "zero horizontal"),
    (lambda f: f.update(kind="unknown"), "unknown kind"),
    (lambda f: f.update(visible="yes"), "true or false"),
    (lambda f: f.update(warnings="warning"), "list of text"),
    (lambda f: f["parameters"].update(spacing=0), "positive"),
])
def test_invalid_features_cannot_replace_project(tmp_path, terrain_file, feature, modify, message):
    destination = tmp_path / "good.json"
    project.save_project(destination, terrain_file, [feature], {})
    before = destination.read_bytes()
    modify(feature)
    with pytest.raises(ValueError, match=message):
        project.save_project(destination, terrain_file, [feature], {})
    assert destination.read_bytes() == before


@pytest.mark.parametrize("fields", [{"engine": ""}, {"engine": None}, {"engine": 1},
    {"engine_version": True}, {"engine_version": 0}, {"engine_version": 1.5},
    {"engine_version": "1"}, {"engine": "legacy", "engine_version": None}])
def test_invalid_engine_metadata_rejected_on_save_and_load(tmp_path, terrain_file, feature, fields):
    path = tmp_path / "engine.json"
    project.save_project(path, terrain_file, [feature], {})
    document = json.loads(path.read_text())
    feature.update(fields)
    with pytest.raises(ValueError, match="engine"):
        project.save_project(path, terrain_file, [feature], {})
    document["features"] = [feature]
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="engine"):
        project.load_project(path)


@pytest.mark.parametrize("engine,version", [("future", 1), ("stream_auto", 2), ("legacy", 2)])
def test_unknown_engine_roundtrips_but_cannot_execute(tmp_path, terrain_file, feature, engine, version):
    feature.update(engine=engine, engine_version=version)
    path = tmp_path / "future.json"
    project.save_project(path, terrain_file, [feature], {})
    loaded = project.load_project(path)["features"][0]
    assert loaded == feature
    with pytest.raises(ValueError, match="Unsupported.*engine"):
        project.require_supported_engine(loaded)


@pytest.mark.parametrize("fields,expected", [({}, "legacy"), ({"engine": "legacy", "engine_version": 1}, "legacy"),
    ({"engine": "stream_auto", "engine_version": 1}, "stream_auto")])
def test_supported_engine_dispatch_is_explicit(fields, expected):
    assert project.require_supported_engine(fields) == expected


def test_adjacent_duplicate_xy_rejected_even_when_line_has_nonzero_length(tmp_path, terrain_file, feature):
    feature['coordinates'].insert(1, [*feature['coordinates'][0][:2], 999])
    with pytest.raises(ValueError, match='zero-length edge'):
        project.save_project(tmp_path / 'duplicate-edge.json', terrain_file, [feature], {})


def test_duplicate_feature_ids_rejected(tmp_path, terrain_file, feature):
    with pytest.raises(ValueError, match="Duplicate line id"):
        project.save_project(tmp_path / "duplicate.json", terrain_file, [feature, feature], {})


def test_project_replace_failure_preserves_original(tmp_path, terrain_file, feature, monkeypatch):
    destination = tmp_path / "example.json"
    project.save_project(destination, terrain_file, [feature], {})
    original = destination.read_bytes()

    def fail(*args):
        raise PermissionError("destination locked")

    monkeypatch.setattr(project.os, "replace", fail)
    with pytest.raises(ValueError, match="destination locked"):
        project.save_project(destination, terrain_file, [], {})
    assert destination.read_bytes() == original
    assert not list(tmp_path.glob(".*.tmp"))


def test_project_cannot_overwrite_terrain(terrain_file):
    original = terrain_file.read_bytes()
    with pytest.raises(ValueError, match="separate project filename"):
        project.save_project(terrain_file, terrain_file, [], {})
    assert terrain_file.read_bytes() == original


def test_missing_terrain_is_actionable(tmp_path, terrain_file, feature):
    destination = tmp_path / "example.json"
    project.save_project(destination, terrain_file, [feature], {})
    terrain_file.unlink()
    with pytest.raises(ValueError, match="Project terrain file not found"):
        project.load_project(destination)


def test_missing_terrain_can_be_loaded_for_relinking(tmp_path, terrain_file, feature):
    destination = tmp_path / "example.json"
    project.save_project(destination, terrain_file, [feature], {"style": "Terrain"})
    terrain_file.unlink()
    loaded = project.load_project(destination, allow_missing_terrain=True)
    assert loaded["terrain_path"] == str(terrain_file.resolve())
    assert loaded["features"] == [feature]
    assert loaded["settings"] == {"style": "Terrain"}


def test_relink_option_does_not_bypass_feature_validation(tmp_path, terrain_file, feature):
    destination = tmp_path / "example.json"
    project.save_project(destination, terrain_file, [feature], {})
    document = json.loads(destination.read_text())
    document["features"][0]["coordinates"] = []
    destination.write_text(json.dumps(document))
    terrain_file.unlink()
    with pytest.raises(ValueError, match="two XYZ"):
        project.load_project(destination, allow_missing_terrain=True)


@pytest.mark.parametrize("contents, message", [
    ("not json", "Could not read project"),
    ('{"format":"x"}', "not a TracerTool"),
    ('{"format":"tracertool-project","version":999}', "Unsupported project version"),
    ('{"format":"tracertool-project","version":true}', "Unsupported project version"),
    ('{"version":1,"version":2}', "duplicate object key"),
])
def test_malformed_projects_rejected(tmp_path, contents, message):
    destination = tmp_path / "invalid.json"
    destination.write_text(contents)
    with pytest.raises(ValueError, match=message):
        project.load_project(destination)


def test_geojson_retains_native_xyz_and_full_metadata(tmp_path, feature):
    destination = tmp_path / "lines.geojson"
    project.export_geojson(destination, [feature], CRS.from_epsg(26915))
    document = json.loads(destination.read_text())
    assert document["crs"]["properties"]["name"] == "urn:ogc:def:crs:EPSG::26915"
    assert "not an RFC 7946" in document["tracertool"]["format_note"]
    line = document["features"][0]
    assert line["geometry"]["coordinates"] == feature["coordinates"]
    assert line["properties"]["metrics"] == feature["metrics"]
    assert line["properties"]["parameters"] == feature["parameters"]
    assert line["properties"]["warnings"] == feature["warnings"]


def test_shapefile_round_trip_xyz_crs_and_parameters(tmp_path, feature):
    destination = tmp_path / "lines.shp"
    paths = project.export_shapefile(destination, [feature], CRS.from_epsg(26915))
    assert {Path(p).suffix for p in paths} == {".shp", ".shx", ".dbf", ".prj", ".cpg"}
    assert all(Path(p).is_file() for p in paths)
    with shapefile.Reader(str(destination), encoding="utf-8") as reader:
        assert reader.shapeType == shapefile.POLYLINEZ
        shape = reader.shape(0)
        assert [list(p) for p in shape.points] == [p[:2] for p in feature["coordinates"]]
        assert list(shape.z) == [p[2] for p in feature["coordinates"]]
        record = reader.record(0).as_dict()
        assert record["line_id"] == feature["id"]
        assert record["name"] == "Creek α"
        assert record["kind"] == "stream"
        assert record["vertices"] == 3
        assert record["len_xy"] == 10
        assert record["corr_px"] == 30
        assert record["smooth_px"] == 1.2
        assert record["terr_wt"] == 8
        assert record["step_px"] == 3
        assert record["simp_px"] == 0.5
        assert record["smooth_ln"] == 0  # Historical schema-1 feature.
        assert record["edited"] is False
        assert record["prov_cnt"] == 0
        assert record["last_op"] == ""
        assert record["warn_cnt"] == 1
    assert CRS.from_wkt(destination.with_suffix(".prj").read_text()).to_epsg() == 26915
    assert destination.with_suffix(".cpg").read_text().strip() == "UTF-8"


@pytest.mark.parametrize("operation", ["move_vertex", "replace_segment"])
def test_edited_line_provenance_and_smoothing_survive_project_and_exports(tmp_path, terrain_file, feature, operation):
    feature["parameters"]["line_smoothing"] = 4.25
    feature["metrics"].update(geometry_edited=True, manually_edited=True)
    feature["provenance"] = [
        {"operation": "reverse_feature", "time": "2026-10-15T10:00:00Z", "details": {}},
        {"operation": operation, "time": "2026-10-15T10:01:00Z",
         "details": {"parameters": {**feature["parameters"], "line_smoothing": 7},
                     "boundary_xyz_preserved": True, "start": 0, "end": 2}},
    ]
    original = copy.deepcopy(feature)
    project_path = tmp_path / "edited.tracer.json"
    geojson_path = tmp_path / "edited.geojson"
    shape_path = tmp_path / "edited.shp"
    project.save_project(project_path, terrain_file, [feature], {})
    project.export_geojson(geojson_path, [feature], "EPSG:26915")
    project.export_shapefile(shape_path, [feature], "EPSG:26915")
    assert project.load_project(project_path)["features"] == [original]
    properties = json.loads(geojson_path.read_text())["features"][0]["properties"]
    assert properties["provenance"] == original["provenance"]
    assert properties["parameters"] == original["parameters"]
    with shapefile.Reader(str(shape_path), encoding="utf-8") as reader:
        record = reader.record(0).as_dict()
        assert record["smooth_ln"] == 4.25
        assert record["edited"] is True
        assert record["prov_cnt"] == 2
        assert record["last_op"] == operation
        assert list(reader.shape(0).z) == [point[2] for point in original["coordinates"]]
    assert feature == original


def test_shapefile_utf8_warning_clipping_preserves_encoding(tmp_path, feature):
    feature["warnings"] = ["é" * 300]
    project.export_shapefile(tmp_path / "lines.shp", [feature], "EPSG:26915")
    with shapefile.Reader(str(tmp_path / "lines.shp"), encoding="utf-8") as reader:
        warning = reader.record(0).as_dict()["warnings"]
        assert warning.endswith("...")
        assert len(warning.encode("utf-8")) <= 254


@pytest.mark.parametrize("export", [project.export_geojson, project.export_shapefile])
def test_empty_export_is_rejected(tmp_path, export):
    with pytest.raises(ValueError, match="no lines to export"):
        export(tmp_path / "empty", [], "EPSG:26915")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("export", [project.export_geojson, project.export_shapefile])
def test_missing_crs_is_rejected(tmp_path, feature, export):
    with pytest.raises(ValueError, match="no CRS"):
        export(tmp_path / "lines", [feature], None)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("export", [project.export_geojson, project.export_shapefile])
def test_invalid_crs_is_actionable(tmp_path, feature, export):
    with pytest.raises(ValueError, match="export CRS is invalid"):
        export(tmp_path / "lines", [feature], "not a coordinate system")
    assert not list(tmp_path.iterdir())


def test_shapefile_commit_failure_restores_all_previous_sidecars(tmp_path, feature, monkeypatch):
    destination = tmp_path / "lines.shp"
    paths = project.export_shapefile(destination, [feature], "EPSG:26915")
    originals = {Path(path): Path(path).read_bytes() for path in paths}
    real_replace = project.os.replace
    failed = False

    def fail_once(source, target):
        nonlocal failed
        if Path(source).suffix == ".dbf" and Path(source).parent != tmp_path and not failed:
            failed = True
            raise PermissionError("simulated disk error")
        return real_replace(source, target)

    monkeypatch.setattr(project.os, "replace", fail_once)
    feature["name"] = "Changed"
    with pytest.raises(ValueError, match="previous export was restored"):
        project.export_shapefile(destination, [feature], "EPSG:26915")
    assert failed
    assert {path: path.read_bytes() for path in originals} == originals
    assert not list(tmp_path.glob(".lines.export-*"))


def test_failed_rollback_keeps_recoverable_original_files(tmp_path, feature, monkeypatch):
    destination = tmp_path / "lines.shp"
    paths = project.export_shapefile(destination, [feature], "EPSG:26915")
    originals = {Path(path): Path(path).read_bytes() for path in paths}
    real_replace = project.os.replace

    def fail_dbf_install_and_restore(source, target):
        if Path(target) == destination.with_suffix(".dbf"):
            raise PermissionError("destination still locked")
        return real_replace(source, target)

    monkeypatch.setattr(project.os, "replace", fail_dbf_install_and_restore)
    with pytest.raises(ValueError, match="Recovery files are in"):
        project.export_shapefile(destination, [feature], "EPSG:26915")
    recovery_dirs = list(tmp_path.glob(".lines.export-*"))
    assert len(recovery_dirs) == 1
    for path, original in originals.items():
        recoverable_path = path if path.exists() else recovery_dirs[0] / (path.name + ".backup")
        assert recoverable_path.read_bytes() == original


def test_project_backup_keeps_previous_valid_version(tmp_path, terrain_file, feature):
    path = tmp_path / "session.tracer.json"
    backup = path.with_name(path.name + ".bak")
    project.save_project(path, terrain_file, [feature], {})
    original = path.read_bytes()
    assert not backup.exists()
    feature["name"] = "Edited creek"
    project.save_project(path, terrain_file, [feature], {})
    assert backup.read_bytes() == original
    assert project.load_project(backup)["features"][0]["name"] == "Creek α"
    assert project.load_project(path)["features"][0]["name"] == "Edited creek"


def test_corrupted_project_does_not_replace_good_backup(tmp_path, terrain_file, feature):
    path = tmp_path / "session.tracer.json"
    project.save_project(path, terrain_file, [feature], {})
    project.save_project(path, terrain_file, [], {})
    backup = path.with_name(path.name + ".bak")
    good_backup = backup.read_bytes()
    path.write_text("{interrupted external write")
    project.save_project(path, terrain_file, [feature], {})
    assert backup.read_bytes() == good_backup
    assert project.load_project(path)["features"] == [feature]


@pytest.mark.parametrize("previous_backup", [False, True])
def test_failed_project_commit_restores_backup_too(tmp_path, terrain_file, feature, monkeypatch, previous_backup):
    path = tmp_path / "session.tracer.json"
    backup = path.with_name(path.name + ".bak")
    project.save_project(path, terrain_file, [feature], {})
    if previous_backup:
        feature["name"] = "Version 2"
        project.save_project(path, terrain_file, [feature], {})
    before_project = path.read_bytes()
    before_backup = backup.read_bytes() if backup.exists() else None
    replace = project.os.replace

    def fail_final_commit(source, target):
        if Path(target) == path:
            raise PermissionError("project commit locked")
        return replace(source, target)

    monkeypatch.setattr(project.os, "replace", fail_final_commit)
    with pytest.raises(ValueError, match="previous project and backup are unchanged"):
        project.save_project(path, terrain_file, [], {})
    assert path.read_bytes() == before_project
    assert (backup.read_bytes() if backup.exists() else None) == before_backup
    assert not list(tmp_path.glob(".session.tracer.json.save-*"))


def test_feature_guides_and_edit_provenance_roundtrip(tmp_path, terrain_file, feature):
    result = SimpleNamespace(coordinates=feature["coordinates"], metrics={}, warnings=[], anchors=[(500000, 4500000), (500006, 4500008)])
    guided = project.new_feature("Guided", "stream", result, Params())
    assert guided["anchors"] == [[500000, 4500000], [500006, 4500008]]
    guided["provenance"] = [{"operation": "move_vertex", "time": "2026-10-15T00:00:00+00:00", "details": {"index": 1}}]
    path = tmp_path / "guides.json"
    project.save_project(path, terrain_file, [guided], {})
    assert project.load_project(path)["features"] == [guided]


@pytest.mark.parametrize("anchors", [[[1, 2]], [[1, 2, 3], [4, 5, 6]], [[1, True], [3, 4]], "not anchors"])
def test_invalid_feature_guides_rejected(tmp_path, terrain_file, feature, anchors):
    feature["anchors"] = anchors
    with pytest.raises(ValueError, match="anchor"):
        project.save_project(tmp_path / "bad.json", terrain_file, [feature], {})


@pytest.mark.parametrize("draft", [
    [], {"kind": "stream", "anchors": [[1, 2, 3]]},
    {"kind": [], "anchors": []}, {"kind": "stream", "anchors": [], "coordinate_space": "working_pixels"},
    {"kind": "stream", "anchors": [], "segment_range": [3, 2]},
    {"kind": "stream", "anchors": [], "edit_target": 123},
])
def test_invalid_saved_drafts_rejected(tmp_path, terrain_file, draft):
    with pytest.raises(ValueError):
        project.save_project(tmp_path / "bad.json", terrain_file, [], {"draft": draft})


@pytest.mark.parametrize('settings', [{'stream_engine': ''}, {'stream_engine': 3},
    {'draft': {'kind': 'stream', 'anchors': [], 'engine': None}},
    {'draft': {'kind': 'stream', 'anchors': [], 'engine_version': True}}])
def test_invalid_saved_engine_selection_rejected(tmp_path, terrain_file, settings):
    with pytest.raises(ValueError, match='engine'):
        project.save_project(tmp_path / 'engine.json', terrain_file, [], settings)


def test_valid_source_identity_roundtrips_without_changing_version(tmp_path, terrain_file):
    settings = {"terrain_reference": {"sha256": "ab" * 32}}
    path = tmp_path / "identity.json"
    project.save_project(path, terrain_file, [], settings)
    loaded = project.load_project(path)
    assert loaded["version"] == 2
    assert loaded["settings"] == settings


@pytest.mark.parametrize("key", ["sha256", "source_sha256"])
def test_source_identity_allows_none_but_rejects_malformed_digest(tmp_path, terrain_file, key):
    path = tmp_path / "identity.json"
    project.save_project(path, terrain_file, [], {"terrain_reference": {key: None}})
    assert project.load_project(path)["settings"]["terrain_reference"][key] is None
    with pytest.raises(ValueError, match="SHA256"):
        project.save_project(path, terrain_file, [], {"terrain_reference": {key: "bad"}})


def test_saved_draft_target_and_segment_must_exist(tmp_path, terrain_file, feature):
    draft = {"kind": "stream", "anchors": [[1, 2], [3, 4]], "edit_target": "missing", "segment_range": [0, 1]}
    with pytest.raises(ValueError, match="missing from the project"):
        project.save_project(tmp_path / "draft.json", terrain_file, [feature], {"draft": draft})
    draft["edit_target"] = feature["id"]
    draft["segment_range"] = [0, len(feature["coordinates"])]
    with pytest.raises(ValueError, match="beyond"):
        project.save_project(tmp_path / "draft.json", terrain_file, [feature], {"draft": draft})


def test_shapefile_preserves_double_precision_xyz_and_multibyte_name(tmp_path, feature):
    feature["coordinates"] = [[500000.1234567891, 4500000.987654321, 200.123456789123],
                              [500003.1234567891, 4500004.987654321, 199.987654321987]]
    feature["name"] = "河" * 84  # 252 UTF-8 bytes, below DBF's 254-byte limit.
    path = tmp_path / "precision.shp"
    project.export_shapefile(path, [feature], "EPSG:26915")
    with shapefile.Reader(str(path), encoding="utf-8") as reader:
        shape = reader.shape(0)
        assert [list(point) + [z] for point, z in zip(shape.points, shape.z)] == feature["coordinates"]
        assert reader.record(0).as_dict()["name"] == feature["name"]


def test_replacing_shapefile_removes_stale_indexes_but_keeps_metadata(tmp_path, feature):
    path = tmp_path / "lines.shp"
    project.export_shapefile(path, [feature], "EPSG:26915")
    indexes = [tmp_path / name for name in ("lines.qix", "lines.SBN", "lines.name.atx")]
    for index in indexes:
        index.write_bytes(b"old index")
    metadata = tmp_path / "lines.shp.xml"
    metadata.write_text("user metadata")
    unrelated = tmp_path / "other.qix"
    unrelated.write_bytes(b"unrelated index")
    feature["coordinates"].append([500009, 4500012, 210])
    project.export_shapefile(path, [feature], "EPSG:26915")
    assert not any(index.exists() for index in indexes)
    assert metadata.read_text() == "user metadata"
    assert unrelated.read_bytes() == b"unrelated index"


def test_failed_shapefile_replacement_restores_existing_indexes(tmp_path, feature, monkeypatch):
    path = tmp_path / "lines.shp"
    project.export_shapefile(path, [feature], "EPSG:26915")
    index = tmp_path / "lines.qix"
    index.write_bytes(b"old index")
    replace = project.os.replace

    def fail_install(source, target):
        if Path(source).suffix == ".dbf" and Path(source).parent != tmp_path:
            raise PermissionError("destination locked")
        return replace(source, target)

    monkeypatch.setattr(project.os, "replace", fail_install)
    with pytest.raises(ValueError, match="restored"):
        project.export_shapefile(path, [feature], "EPSG:26915")
    assert index.read_bytes() == b"old index"
