"""The public demo must be reproducible and independent of private rasters."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np
import pytest
import rasterio

from tracertool.project import load_project
from tracertool.terrain import Terrain
from tracertool.tracing import TraceParams, validate_segments


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "create_demo.py"
spec = importlib.util.spec_from_file_location("tracertool_demo_script", SCRIPT)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def test_generated_demo_is_deterministic_and_portable(tmp_path):
    first = demo.create_demo(tmp_path / "first")
    second = demo.create_demo(tmp_path / "second")
    assert first.read_bytes() == second.read_bytes()
    first_raster = first.parent / "demo.tif"
    assert first_raster.read_bytes() == (second.parent / first_raster.name).read_bytes()
    document = json.loads(first.read_text())
    assert document["terrain_path"] == first_raster.name
    assert document["settings"]["demo"]["synthetic"] is True
    assert {f["kind"] for f in document["features"]} == {"ridge", "stream"}
    assert all(f["parameters"]["spacing"] == TraceParams().spacing for f in document["features"])


def test_demo_native_elevations_geometry_and_nodata(tmp_path):
    project = load_project(demo.create_demo(tmp_path))
    terrain = Terrain.load(project["terrain_path"])
    assert terrain.crs.to_epsg() == 32615
    assert terrain.resolution == 1
    assert terrain.metadata["vertical_units"] == "m"
    assert not terrain.metadata["resampled"]
    assert terrain.data.shape == (512, 640)
    with rasterio.open(terrain.path) as dataset:
        np.testing.assert_array_equal(dataset.read(1), demo.synthetic_dem())
        assert dataset.tags()["SOURCE"].startswith("TracerTool analytic synthetic")
    assert not terrain.valid[10, 10]
    with pytest.raises(ValueError, match="NoData"):
        validate_segments(terrain, [terrain.xy(10, 40), terrain.xy(10, 10)])
    for feature in project["features"]:
        coordinates = feature["coordinates"]
        validate_segments(terrain, coordinates)
        assert [p[2] for p in coordinates] == terrain.sample_many([p[:2] for p in coordinates])
        cells = np.asarray([terrain.rc(*p[:2]) for p in coordinates])
        center = demo.levee_center if feature["kind"] == "ridge" else demo.stream_center
        assert np.max(np.abs(cells[:, 1] - center(cells[:, 0]))) < 4
        lengths = np.linalg.norm(np.diff(cells, axis=0), axis=1)
        assert 5 <= lengths.min() <= np.median(lengths) <= lengths.max() <= 8
        vectors = np.diff(cells, axis=0) / lengths[:, None]
        turns = np.degrees(np.arccos(np.clip((vectors[:-1] * vectors[1:]).sum(axis=1), -1, 1)))
        assert turns.max() < 20, "The demonstration lines should have no abrupt guide-induced kinks."
        assert all(anchor in [p[:2] for p in coordinates] for anchor in feature["anchors"])
        assert not feature["warnings"]


def test_documented_command_runs_outside_checkout_without_external_data(tmp_path):
    output = tmp_path / "generated"
    screenshot = tmp_path / "demo.png"
    completed = subprocess.run([sys.executable, str(SCRIPT), "--output", str(output),
                                "--screenshot", str(screenshot)],
                               cwd=tmp_path, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": "1"},
                               text=True, capture_output=True, timeout=30, check=True)
    project_path = Path(completed.stdout.strip())
    assert project_path == output / "demo.tracer.json"
    assert project_path.is_file()
    project = load_project(project_path)
    assert Path(project["terrain_path"]).parent == output
    assert set(p.name for p in output.iterdir()) == {"demo.tif", "demo.tracer.json"}
    assert "referenceTiles" not in SCRIPT.read_text()
    png = screenshot.read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", png[16:24]) == (1500, 960)
