import copy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from tracertool import raster_ops
from tracertool.project import export_geojson, new_feature
from tracertool.raster_ops import RasterOperationCancelled, reproject_dem, transform_features
from tracertool.tracing import TraceParams


def make_dem(path, *, crs="EPSG:32615", shape=(32, 32), calibrated=False, internal_mask=False):
    values = np.arange(np.prod(shape), dtype="float64").reshape(shape) * .05
    if calibrated:
        values = np.arange(np.prod(shape), dtype="int16").reshape(shape)
    nodata = None if internal_mask else -9999
    if not internal_mask:
        values[8:12, 8:12] = nodata
    with rasterio.open(path, "w", driver="GTiff", height=shape[0], width=shape[1], count=1,
                       dtype=values.dtype, crs=crs, transform=from_origin(500000, 4500000, 2, 2), nodata=nodata) as dataset:
        dataset.write(values, 1)
        if calibrated:
            dataset.scales = (.1,)
            dataset.offsets = (100,)
        if internal_mask:
            mask = np.full(shape, 255, dtype="uint8")
            mask[8:12, 8:12] = 0
            dataset.write_mask(mask)
        dataset.set_band_unit(1, "ft")
        dataset.set_band_description(1, "Ground elevation")
        dataset.update_tags(vertical_datum="NAVD88")
        dataset.update_tags(1, STATISTICS_MINIMUM="stale", source_note="fixture")
    return values


def test_reproject_decodes_scale_offset_preserves_nodata_units_and_source(tmp_path):
    source, target = tmp_path / "source.tif", tmp_path / "projected.tif"
    encoded = make_dem(source, calibrated=True)
    original = source.read_bytes()
    result = reproject_dem(source, target, "EPSG:32615", resolution=2, resampling="nearest")
    assert result == target
    assert source.read_bytes() == original
    with rasterio.open(target) as output:
        values = output.read(1)
        valid = encoded != -9999
        assert np.allclose(values[valid], encoded[valid] * .1 + 100, rtol=0, atol=1e-10)
        assert np.isnan(values[~valid]).all()
        assert output.scales == (1.0,) and output.offsets == (0.0,)
        assert output.units == ("ft",)
        assert output.descriptions == ("Ground elevation",)
        assert output.tags()["vertical_datum"] == "NAVD88"
        assert "STATISTICS_MINIMUM" not in output.tags(1)
        assert output.tags(1)["source_note"] == "fixture"
        assert output.tags(ns="TRACERTOOL")["source_crs_overridden"] == "false"
        assert output.crs.to_epsg() == 32615
        assert output.dtypes == ("float64",)


def test_internal_validity_mask_and_valid_zero_are_preserved(tmp_path):
    source, target = tmp_path / "masked.tif", tmp_path / "projected.tif"
    values = make_dem(source, internal_mask=True)
    reproject_dem(source, target, "EPSG:32615", resolution=2, resampling="nearest")
    with rasterio.open(target) as output:
        warped = output.read(1, masked=True)
        assert warped.mask[8:12, 8:12].all()
        assert not warped.mask[0, 0]
        assert warped[0, 0] == 0
        assert warped[20, 20] == values[20, 20]


def test_reproject_changes_horizontal_crs_and_resolution(tmp_path):
    source, target = tmp_path / "source.tif", tmp_path / "projected.tif"
    make_dem(source)
    reproject_dem(source, target, "EPSG:32614", resolution=(3, 4))
    with rasterio.open(target) as output:
        assert output.crs.to_epsg() == 32614
        assert output.res == (3, 4)
        assert np.isfinite(output.read(1)).any()
        assert output.units[0] == "ft"


def test_missing_source_crs_requires_explicit_override(tmp_path):
    source, target = tmp_path / "source.tif", tmp_path / "projected.tif"
    make_dem(source, crs=None)
    original = source.read_bytes()
    with pytest.raises(ValueError, match="no CRS"):
        reproject_dem(source, target, "EPSG:32615")
    assert not target.exists()
    reproject_dem(source, target, "EPSG:32615", source_crs="EPSG:32615", resampling="nearest")
    assert source.read_bytes() == original
    with rasterio.open(source) as incoming:
        assert incoming.crs is None
    with rasterio.open(target) as output:
        assert output.crs.to_epsg() == 32615
        assert output.tags(ns="TRACERTOOL")["source_crs_overridden"] == "true"


def test_cancellation_between_tiles_preserves_destination_and_cleans_temporary(tmp_path):
    source, target = tmp_path / "source.tif", tmp_path / "previous.tif"
    make_dem(source, shape=(600, 600))
    target.write_bytes(b"previous output remains intact")
    source_bytes, target_bytes = source.read_bytes(), target.read_bytes()
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls >= 3

    with pytest.raises(RasterOperationCancelled, match="cancelled"):
        reproject_dem(source, target, "EPSG:32615", cancel=cancelled)
    assert calls >= 3
    assert target.read_bytes() == target_bytes
    assert source.read_bytes() == source_bytes
    assert not list(tmp_path.glob(".*.reproject-*"))


def test_failed_atomic_commit_preserves_previous_raster(tmp_path, monkeypatch):
    source, target = tmp_path / "source.tif", tmp_path / "output.tif"
    make_dem(source)
    target.write_bytes(b"previous output")
    original = target.read_bytes()
    real_replace = raster_ops.os.replace

    def fail_commit(src, dst):
        if Path(dst) == target:
            raise PermissionError("output locked")
        return real_replace(src, dst)

    monkeypatch.setattr(raster_ops.os, "replace", fail_commit)
    with pytest.raises(ValueError, match="output locked"):
        reproject_dem(source, target, "EPSG:32615")
    assert target.read_bytes() == original
    assert not list(tmp_path.glob(".*.reproject-*"))


def test_source_cannot_be_overwritten_and_geographic_target_rejected(tmp_path):
    source = tmp_path / "source.tif"
    make_dem(source)
    original = source.read_bytes()
    with pytest.raises(ValueError, match="cannot be overwritten"):
        reproject_dem(source, source, "EPSG:32614")
    with pytest.raises(ValueError, match="projected target CRS"):
        reproject_dem(source, tmp_path / "geographic.tif", "EPSG:4326")
    assert source.read_bytes() == original


@pytest.mark.parametrize("resolution", [0, -1, True, float("nan"), [2], [2, 0]])
def test_invalid_target_resolution_rejected_before_output(tmp_path, resolution):
    source = tmp_path / "source.tif"
    make_dem(source)
    target = tmp_path / "invalid.tif"
    with pytest.raises(ValueError, match="resolution"):
        reproject_dem(source, target, "EPSG:32615", resolution=resolution)
    assert not target.exists()


@pytest.fixture
def feature():
    return new_feature("Meridian", "stream", SimpleNamespace(
        coordinates=[[3.0, 0.0, 100.0], [3.0, .01, 99.0]], anchors=[[3.0, 0.0], [3.0, .01]],
        warnings=[], metrics={"source_note": "preserved"}), TraceParams())


def test_feature_transform_preserves_line_smoothing_and_local_correction_history(feature):
    feature["parameters"]["line_smoothing"] = 4
    feature["provenance"] = [{"operation": "replace_segment", "details": {
        "start": 0, "end": 1, "parameters": {**feature["parameters"], "line_smoothing": 7}}}]
    original = copy.deepcopy(feature)
    transformed = transform_features([feature], "EPSG:4326", "EPSG:32631")[0]
    assert transformed["parameters"] == original["parameters"]
    assert transformed["provenance"][:-1] == original["provenance"]
    assert transformed["provenance"][-1]["operation"] == "transform_coordinates"
    assert feature == original


@pytest.mark.parametrize("target_crs,z_scale", [("EPSG:32615", 1), ("EPSG:32615", .3048),
                                               ("EPSG:2276", 1), ("EPSG:2276", .3048)])
def test_transformed_export_metrics_describe_output_and_retain_source_metrics(tmp_path, feature, target_crs, z_scale):
    import json
    feature["coordinates"] = [[500000., 4500000., 100.], [500008., 4500000., 90.], [500016., 4500000., 95.]]
    feature["anchors"] = [point[:2] for point in feature["coordinates"]]
    feature["metrics"] = {"units": "metre", "vertical_units": "foot", "length": 16,
                          "elevation_start": 100, "elevation_end": 95, "elevation_min": 90,
                          "elevation_max": 100, "elevation_gain": 5, "elevation_loss": 10,
                          "spacing_min": 8, "spacing_median": 8, "spacing_max": 8,
                          "working_resolution": 1, "corridor_map_units": 30,
                          "spacing_min_pixels": 8, "spacing_exception_count": 0,
                          "max_abs_grade_percent": 38.1, "source_note": "Keep source metadata"}
    original = copy.deepcopy(feature)
    transformed = transform_features([feature], "EPSG:32615", target_crs, z_scale)[0]
    coordinates = np.asarray(transformed["coordinates"])
    distances = np.linalg.norm(np.diff(coordinates[:, :2], axis=0), axis=1)
    metrics = transformed["metrics"]
    assert transformed["source_metrics"] == original["metrics"]
    assert metrics["units"] == metrics["length_units"] == ("metre" if target_crs == "EPSG:32615" else "US survey foot")
    assert metrics["length"] == pytest.approx(distances.sum())
    assert [metrics[key] for key in ("spacing_min", "spacing_median", "spacing_max")] == pytest.approx([
        distances.min(), np.median(distances), distances.max()])
    assert [metrics[key] for key in ("elevation_start", "elevation_end", "elevation_min", "elevation_max",
                                    "elevation_gain", "elevation_loss")] == pytest.approx(np.asarray([100, 95, 90, 100, 5, 10]) * z_scale)
    for key in ("working_resolution", "corridor_map_units", "spacing_min_pixels", "spacing_exception_count", "max_abs_grade_percent"):
        assert key not in metrics
    assert metrics["source_note"] == "Keep source metadata"
    if z_scale == 1:
        assert metrics["vertical_units"] == "foot"
    else:
        assert metrics["vertical_units"].startswith("unspecified")
        assert metrics["source_vertical_units"] == "foot"

    path = tmp_path / "export.geojson"
    export_geojson(path, [transformed], target_crs)
    exported = json.loads(path.read_text())
    note = exported["tracertool"]
    assert note["coordinate_system"] == ("native DEM CRS" if target_crs == "EPSG:32615" else "explicitly transformed output CRS")
    assert ("Unmodified" in note["elevation"]) is (z_scale == 1)
    assert "No vertical datum transformation" in note["elevation"]
    assert exported["features"][0]["properties"]["source_metrics"] == original["metrics"]
    assert feature == original


def test_repeated_transformations_preserve_initial_source_metrics(feature):
    original = copy.deepcopy(feature)
    first = transform_features([feature], "EPSG:4326", "EPSG:32631", z_scale=2)
    second = transform_features(first, "EPSG:32631", "EPSG:32632", z_scale=.5)[0]
    assert second["source_metrics"] == original["metrics"]
    assert [point[2] for point in second["coordinates"]] == [point[2] for point in original["coordinates"]]
    assert len(second["provenance"]) == 2
    assert feature == original


def test_known_coordinate_transform_roundtrip_preserves_originals_and_anchors(feature):
    before = copy.deepcopy(feature)
    projected = transform_features([feature], "EPSG:4326", "EPSG:32631")
    line = projected[0]
    assert line["coordinates"][0] == pytest.approx([500000, 0, 100], abs=1e-6)
    assert line["coordinates"][1][0] == pytest.approx(500000, abs=1e-6)
    assert line["coordinates"][1][1] == pytest.approx(1105.300461, abs=1e-5)
    assert line["anchors"][1] == line["coordinates"][1][:2]
    assert line["metrics"]["length_units"] == "metre"
    assert line["metrics"]["length"] == pytest.approx(1105.300461, abs=1e-5)
    assert line["metrics"]["source_note"] == "preserved"
    assert line["provenance"][-1]["details"]["vertical_datum_transform"] is False
    restored = transform_features(projected, "EPSG:32631", "EPSG:4326")
    assert np.allclose(restored[0]["coordinates"], feature["coordinates"], rtol=0, atol=1e-10)
    assert feature == before
    projected[0]["metrics"]["source_note"] = "edited copy"
    assert feature == before


def test_elevation_changes_only_with_explicit_positive_scale(feature):
    before = copy.deepcopy(feature)
    projected = transform_features([feature], "EPSG:4326", "EPSG:32631", z_scale=.3048)[0]
    assert [point[2] for point in projected["coordinates"]] == pytest.approx([30.48, 30.1752])
    assert projected["metrics"]["elevation_change"] == pytest.approx(-.3048)
    assert projected["provenance"][-1]["details"]["z_scale"] == .3048
    assert feature == before
    for bad_scale in (0, -1, True, float("inf")):
        with pytest.raises(ValueError):
            transform_features([feature], "EPSG:4326", "EPSG:32631", z_scale=bad_scale)


def test_failed_coordinate_transform_does_not_mutate_input(feature):
    feature["coordinates"][1][1] = 100.0  # Latitude outside the valid domain.
    before = copy.deepcopy(feature)
    with pytest.raises(ValueError, match="transform"):
        transform_features([feature], "EPSG:4326", "EPSG:32631")
    assert feature == before


def test_raster_overwrite_removes_stale_external_mask_and_overviews(tmp_path):
    source, target = tmp_path / "source.tif", tmp_path / "output.tif"
    make_dem(source)
    make_dem(target)
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(target, "r+") as old:
            old.write_mask(np.zeros((32, 32), dtype="uint8"))
    mask = Path(str(target) + ".msk")
    overview = Path(str(target) + ".ovr")
    auxiliary = Path(str(target) + ".aux.xml")
    assert mask.exists()
    overview.write_bytes(b"old overview")
    auxiliary.write_text("<PAMDataset/>")
    reproject_dem(source, target, "EPSG:32615", resampling="nearest")
    assert not any(path.exists() for path in (mask, overview, auxiliary))
    with rasterio.open(target) as output:
        assert not output.read(1, masked=True).mask[0, 0]
    assert not list(tmp_path.glob("*.sidecars-*"))


def test_failed_raster_commit_restores_previous_external_sidecars(tmp_path, monkeypatch):
    source, target = tmp_path / "source.tif", tmp_path / "output.tif"
    make_dem(source)
    make_dem(target)
    mask = Path(str(target) + ".msk")
    mask.write_bytes(b"previous external mask")
    before = target.read_bytes()
    replace = raster_ops.os.replace

    def fail_final(source_path, target_path):
        if Path(target_path) == target:
            raise PermissionError("output locked")
        return replace(source_path, target_path)

    monkeypatch.setattr(raster_ops.os, "replace", fail_final)
    with pytest.raises(ValueError, match="sidecars were restored"):
        reproject_dem(source, target, "EPSG:32615")
    assert target.read_bytes() == before
    assert mask.read_bytes() == b"previous external mask"
