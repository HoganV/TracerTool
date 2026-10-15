"""Measure local DEM load, four display styles and four guided trace modes.

This smoke benchmark measures processing time, not tracing accuracy. Inputs are
read-only; output goes to artifacts/benchmark.json unless --output is supplied.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tracertool.terrain import Terrain
from tracertool.tracing import TraceParams, trace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=ROOT / "referenceTiles")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/benchmark.json")
    args = parser.parse_args()
    paths = sorted(p for p in args.directory.iterdir() if p.suffix.lower() in {".tif", ".tiff"})
    if not paths:
        parser.error("No TIFF files found in the chosen directory.")
    result = {"python": platform.python_version(), "platform": platform.platform(),
              "processor": platform.processor(), "max_dimension": 2400,
              "note": "Synthetic anchor locations; timing only, not accuracy evaluation.", "tiles": []}
    for path in paths:
        start = time.perf_counter()
        terrain = Terrain.load(path)
        row = {"file": path.name, "load_seconds": time.perf_counter() - start,
               "width": terrain.width, "height": terrain.height,
               "working_resolution": terrain.resolution, "units": terrain.units,
               "resampled": terrain.metadata["resampled"], "renders": {}, "traces": {}}
        for style in ("Terrain", "Hillshade", "Slope", "Elevation"):
            start = time.perf_counter()
            terrain.rgb(style)
            row["renders"][style] = time.perf_counter() - start
        anchors = [(terrain.height * .35, terrain.width * .40),
                   (terrain.height * .65, terrain.width * .60)]
        row["anchors_row_col"] = anchors
        for kind in ("stream", "ridge", "slope_break", "manual"):
            start = time.perf_counter()
            candidate = trace(terrain, anchors, kind, TraceParams())
            row["traces"][kind] = {"seconds": time.perf_counter() - start,
                                    "metrics": candidate.metrics, "warnings": candidate.warnings}
        result["tiles"].append(row)
        print(f"{path.name}: load {row['load_seconds']:.3f}s; "
              f"four views {sum(row['renders'].values()):.3f}s; "
              f"four traces {sum(v['seconds'] for v in row['traces'].values()):.3f}s")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
