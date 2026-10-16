#!/usr/bin/env python3
"""Create a public, deterministic terrain demo without reading external data.

The 640 × 512 grid has 1 metre square cells in EPSG:32615 (UTM zone 15N).
XY origins are arbitrary map coordinates; Z is a synthetic elevation in metres
without a claimed vertical datum. A curved flat-topped levee occupies the west
side and a separate curved stream valley occupies the east. A small northwest
NoData corner demonstrates a masked raster. Neither terrain nor lines describe
a real place, and this fixture is not a hydrologic or surveying benchmark.

Run from any directory with the project's Python dependencies installed:
    python scripts/create_demo.py --output artifacts/demo
Optional --screenshot captures the actual Qt application, using only this demo.
Generated TIFF/project files belong in the ignored artifacts directory, not Git.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import os
from pathlib import Path
import sys
import tempfile
from uuid import NAMESPACE_URL, uuid5

import numpy as np
import rasterio
from rasterio.transform import from_origin

# The documented command works in a source checkout without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracertool.project import load_project, new_feature, save_project
from tracertool.terrain import Terrain
from tracertool.tracing import TraceParams, trace, validate_segments


WIDTH, HEIGHT = 640, 512
CELL_SIZE = 1.
CRS = "EPSG:32615"
NODATA = -9999.


def levee_center(rows):
    return 166. + 42. * np.sin((np.asarray(rows) - 40.) * np.pi / 430.)


def stream_center(rows):
    return 440. + 40. * np.sin((np.asarray(rows) + 30.) * 1.6 * np.pi / 512.)


def synthetic_dem():
    """Return the generated float32 elevation grid; no files or randomness used."""
    rows, columns = np.mgrid[:HEIGHT, :WIDTH]
    ground = 118. - .018 * rows
    ridge_distance = np.abs(columns - levee_center(rows))
    valley_distance = np.abs(columns - stream_center(rows))
    # Six-metre half-width crown with twelve-metre sloping embankments.
    levee = 9. * np.clip((18. - ridge_distance) / 12., 0., 1.)
    # Broad floodplain plus a distinct central channel, separate from the levee.
    valley = 5. * np.exp(-.5 * (valley_distance / 44.) ** 2)
    channel = 5. * np.exp(-.5 * (valley_distance / 10.) ** 2)
    texture = .04 * np.sin(rows * .13) * np.cos(columns * .17)
    elevations = (ground + levee - valley - channel + texture).astype(np.float32)
    elevations[(rows < 22) & (columns < 32)] = NODATA
    return elevations


def create_demo(output):
    """Write a generated GeoTIFF and portable project, returning its project path.

    Repeated runs use the same raster, guide anchors, and feature identities.
    Geometry uses explicit demonstration parameters; changing the tracing
    engine or application version can legitimately change future fixture bytes.
    """
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    terrain_path = output / "demo.tif"
    project_path = output / "demo.tracer.json"
    with rasterio.open(terrain_path, "w", driver="GTiff", width=WIDTH, height=HEIGHT,
                       count=1, dtype="float32", crs=CRS,
                       transform=from_origin(500000, 4500000, CELL_SIZE, CELL_SIZE),
                       nodata=NODATA, compress="deflate", predictor=3) as dataset:
        dataset.write(synthetic_dem(), 1)
        dataset.set_band_unit(1, "m")
        dataset.set_band_description(1, "Generated elevation; synthetic metres, no vertical datum")
        dataset.update_tags(SOURCE="TracerTool analytic synthetic fixture; no external terrain data",
                            AREA_OR_POINT="Area")
    terrain = Terrain.load(terrain_path, compute_fingerprint=True)
    # This published example intentionally demonstrates optional smoothing;
    # new projects use the unsmoothed cell-relative defaults.
    parameters = TraceParams(corridor=30, smoothing=2, line_smoothing=4, spacing=8, simplify=1, relax_anchors=False)
    rows = [40, 256, 472]
    features = []
    for name, kind, center in (("Curved levee crest", "ridge", levee_center),
                               ("Stream valley centerline", "stream", stream_center)):
        anchors = [(row, round(float(center(row)))) for row in rows]
        result = trace(terrain, anchors, kind, parameters)
        validate_segments(terrain, result.coordinates)
        feature = new_feature(name, kind, result, parameters)
        feature["id"] = str(uuid5(NAMESPACE_URL, f"tracertool:synthetic-demo:v1:{kind}"))
        features.append(feature)
    settings = {
        "parameters": asdict(parameters), "style": "Terrain", "azimuth": 315., "z_factor": 1.,
        "preferences": {"display": {"multidirectional": True, "shade_strength": .55}},
        "terrain_reference": {
            "crs_wkt": terrain.crs.to_wkt(), "bounds": list(terrain.bounds),
            "original_width": WIDTH, "original_height": HEIGHT,
            "original_resolution_xy": [CELL_SIZE, CELL_SIZE],
            "source_sha256": terrain.fingerprint(),
        },
        "demo": {"synthetic": True, "generator": "scripts/create_demo.py",
                 "grid": "640 × 512; 1 metre cells", "horizontal_crs": CRS,
                 "elevation_units": "metres", "vertical_datum": "none; synthetic elevations",
                 "source": "Analytic formulas only; no external terrain data"},
    }
    save_project(project_path, terrain_path, features, settings)
    return project_path


def capture_demo(project_path, destination):
    """Capture the real desktop widgets with isolated preferences and recovery."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from tracertool.app import MainWindow, STYLE

    destination = Path(destination).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    previous_state = os.environ.get("TRACERTOOL_STATE_DIR")
    with tempfile.TemporaryDirectory(prefix="tracertool-demo-state-") as state:
        os.environ["TRACERTOOL_STATE_DIR"] = state
        window = None
        try:
            application = QApplication.instance() or QApplication(["TracerTool synthetic demo"])
            application.setStyle("Fusion")
            application.setStyleSheet(STYLE)
            window = MainWindow()
            window.resize(1500, 960)
            window.show()
            application.processEvents()
            project = load_project(project_path)
            window.install_terrain(window.load_terrain_image(project["terrain_path"]), project)
            window.canvas.fit()
            window.select_feature(project["features"][0]["id"])
            window.statusBar().showMessage("Generated synthetic demo · 1 metre cells · no real-world terrain data")
            application.processEvents()
            if not window.grab().save(str(destination)):
                raise RuntimeError(f"Could not save the demo screenshot to {destination}.")
        finally:
            if window is not None:
                window.dirty = False
                window.close()
                window.deleteLater()
                application.processEvents()
            if previous_state is None:
                os.environ.pop("TRACERTOOL_STATE_DIR", None)
            else:
                os.environ["TRACERTOOL_STATE_DIR"] = previous_state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=Path("artifacts/demo"), help="Folder for generated TIFF and project")
    parser.add_argument("--screenshot", type=Path, help="Optional real application screenshot (PNG)")
    args = parser.parse_args(argv)
    project = create_demo(args.output)
    if args.screenshot:
        capture_demo(project, args.screenshot)
    print(project)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
