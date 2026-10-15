"""Explicit, non-destructive coordinate and elevation transformations.

Horizontal reprojection never performs a vertical datum conversion. The only
permitted change to line Z is the caller's explicit positive ``z_scale``.
Raster outputs contain decoded source elevation values with scale=1, offset=0.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import shutil
import tempfile

import numpy as np
import rasterio
from rasterio.enums import ColorInterp, Resampling
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform, transform

from . import __version__
from .project import _export_crs, _number, _path, _validate_features


class RasterOperationCancelled(ValueError):
    """Raised when a caller cancels before output is committed."""


def _check_cancel(cancel) -> None:
    if cancel is not None and cancel():
        raise RasterOperationCancelled("Terrain operation cancelled; original files were not changed.")


def _resolution(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ValueError("Target resolution must be one positive value or an [x, y] pair.")
        result = tuple(_number(item, "Target resolution") for item in value)
        if any(item <= 0 for item in result):
            raise ValueError("Target resolution must be positive in target CRS units.")
        return result
    number = _number(value, "Target resolution")
    if number <= 0:
        raise ValueError("Target resolution must be positive in target CRS units.")
    return number


def _clean_tags(tags):
    return {key: value for key, value in tags.items()
            if not key.upper().startswith("STATISTICS_") and key.lower() not in {"scale", "offset", "scale_factor", "add_offset"}}


def _commit_raster(temporary: Path, target: Path) -> None:
    """Replace the TIFF while retiring only its stale, file-specific sidecars."""
    sidecars = [Path(str(target) + suffix) for suffix in (".msk", ".ovr", ".aux.xml")]
    sidecars = [path for path in sidecars if path.exists() or path.is_symlink()]
    if not sidecars:
        os.replace(temporary, target)
        return
    directory = Path(tempfile.mkdtemp(prefix=f".{target.name}.sidecars-", dir=target.parent))
    moved = []
    keep_recovery = False
    try:
        for sidecar in sidecars:
            if sidecar.is_dir():
                raise ValueError(f"Cannot replace a raster with a directory at its sidecar path: {sidecar}")
            backup = directory / sidecar.name
            os.replace(sidecar, backup)
            moved.append((sidecar, backup))
        os.replace(temporary, target)
    except (OSError, ValueError) as exc:
        restoration_errors = []
        for sidecar, backup in reversed(moved):
            try:
                os.replace(backup, sidecar)
            except OSError as restore_exc:
                restoration_errors.append(str(restore_exc))
        if restoration_errors:
            keep_recovery = True
            raise ValueError(f"Raster replacement failed: {exc}. The previous TIFF is unchanged; sidecar recovery files are in {directory}. " + "; ".join(restoration_errors)) from exc
        raise ValueError(f"Raster replacement failed: {exc}. The previous TIFF and its sidecars were restored.") from exc
    finally:
        if not keep_recovery:
            shutil.rmtree(directory, ignore_errors=True)


def reproject_dem(source_path, dest_path, target_crs, resolution=None,
                  resampling="bilinear", source_crs=None, cancel=None) -> Path:
    """Create a projected, single-band elevation GeoTIFF without changing source.

    ``resolution`` is in target horizontal CRS units. ``source_crs`` explicitly
    overrides source metadata, including for files without a declared CRS.
    Valid resampling names: nearest, bilinear, cubic, cubic_spline, lanczos,
    average. Processing is tiled and cancellation is checked between tiles.
    """
    source = _path(source_path, "source terrain")
    target = _path(dest_path, "reprojected terrain")
    if target == source or (target.exists() and source.exists() and os.path.samefile(source, target)):
        raise ValueError("Choose a separate output GeoTIFF; the source terrain cannot be overwritten.")
    if target.suffix.lower() not in {".tif", ".tiff"}:
        raise ValueError("The reprojected terrain filename must end in .tif or .tiff.")
    destination_crs = _export_crs(target_crs)
    if not destination_crs.is_projected:
        raise ValueError("Choose a projected target CRS for terrain tracing, such as the appropriate local UTM or State Plane CRS.")
    allowed = {name: getattr(Resampling, name) for name in ("nearest", "bilinear", "cubic", "cubic_spline", "lanczos", "average")}
    if not isinstance(resampling, str) or resampling not in allowed:
        raise ValueError("Resampling must be nearest, bilinear, cubic, cubic_spline, lanczos, or average.")
    spacing = _resolution(resolution)
    _check_cancel(cancel)
    temporary: Path | None = None
    try:
        with rasterio.open(source) as incoming:
            if incoming.count < 1 or min(incoming.width, incoming.height) < 2:
                raise ValueError("The source terrain needs an elevation band at least 2 × 2 pixels.")
            if np.dtype(incoming.dtypes[0]).kind == "c":
                raise ValueError("Complex-valued raster samples cannot be used as elevations.")
            origin_crs = _export_crs(source_crs if source_crs is not None else incoming.crs)
            scale = _number(incoming.scales[0], "Source elevation scale")
            offset = _number(incoming.offsets[0], "Source elevation offset")
            if scale == 0:
                raise ValueError("The source elevation scale is zero. Correct its calibration before reprojection.")
            affine, width, height = calculate_default_transform(origin_crs, destination_crs,
                                                                 incoming.width, incoming.height,
                                                                 *incoming.bounds, resolution=spacing)
            if width < 2 or height < 2:
                raise ValueError("The requested resolution produces fewer than 2 × 2 cells. Choose a finer target resolution.")
            # Keep precision for calibrated/large integer inputs; ordinary
            # Float32 DEMs retain their original storage precision.
            source_dtype = np.dtype(incoming.dtypes[0])
            wide = scale != 1 or offset != 0 or source_dtype.itemsize > 4 or (source_dtype.kind in "iu" and source_dtype.itemsize >= 4)
            dtype = "float64" if wide else "float32"
            fd, name = tempfile.mkstemp(prefix=f".{target.stem}.reproject-", suffix=".tif", dir=target.parent)
            os.close(fd)
            temporary = Path(name)
            profile = dict(driver="GTiff", width=width, height=height, count=1,
                           dtype=dtype, crs=destination_crs, transform=affine,
                           nodata=float("nan"), tiled=True, blockxsize=256, blockysize=256,
                           compress="deflate", predictor=3, BIGTIFF="IF_SAFER")
            # An alpha mask also preserves sources whose NoData is represented
            # by an internal dataset mask rather than a numeric sentinel.
            add_alpha = ColorInterp.alpha not in incoming.colorinterp
            with WarpedVRT(incoming, src_crs=origin_crs, crs=destination_crs,
                           transform=affine, width=width, height=height,
                           resampling=allowed[resampling], dtype="float64",
                           nodata=float("nan"), add_alpha=add_alpha,
                           init_dest_nodata=False, warp_extras={"INIT_DEST": "0"},
                           warp_mem_limit=128) as warped, rasterio.open(temporary, "w", **profile) as outgoing:
                alpha_band = next((index for index, interpretation in enumerate(warped.colorinterp, 1)
                                   if interpretation == ColorInterp.alpha), None)
                for _, window in outgoing.block_windows(1):
                    _check_cancel(cancel)
                    tile = warped.read(1, window=window, masked=True, out_dtype="float64")
                    values = np.ma.filled(tile, np.nan)
                    if alpha_band is not None:
                        alpha = warped.read(alpha_band, window=window)
                        values[alpha <= 0] = np.nan
                    valid = np.isfinite(values)
                    with np.errstate(over="ignore", invalid="ignore"):
                        values[valid] = values[valid] * scale + offset
                    if not np.all(np.isfinite(values[valid])):
                        raise ValueError("Calibrating source elevations produced non-finite values. Check the source scale and offset.")
                    with np.errstate(over="ignore", invalid="ignore"):
                        stored = values.astype(dtype)
                    if not np.all(np.isfinite(stored[valid])):
                        raise ValueError("Reprojected elevations exceed the output numeric range. Check source elevation values.")
                    outgoing.write(stored, 1, window=window)
                outgoing.scales = (1.0,)
                outgoing.offsets = (0.0,)
                if incoming.units[0]:
                    outgoing.set_band_unit(1, incoming.units[0])
                if incoming.descriptions[0]:
                    outgoing.set_band_description(1, incoming.descriptions[0])
                outgoing.update_tags(**_clean_tags(incoming.tags()))
                outgoing.update_tags(1, **_clean_tags(incoming.tags(1)))
                outgoing.update_tags(ns="TRACERTOOL", application_version=__version__,
                                     operation="horizontal_reprojection", source_name=source.name,
                                     source_crs_wkt=origin_crs.to_wkt(), target_crs_wkt=destination_crs.to_wkt(),
                                     source_crs_overridden=str(source_crs is not None).lower(),
                                     source_scale=str(scale), source_offset=str(offset),
                                     resampling=resampling, vertical_transform="none; decoded source units and datum retained")
        _check_cancel(cancel)
        # Windows' CRT _commit requires a writable file descriptor.
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        _commit_raster(temporary, target)
        temporary = None
        return target
    except RasterOperationCancelled:
        raise
    except Exception as exc:
        raise ValueError(f"Could not reproject terrain: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
            Path(str(temporary) + ".aux.xml").unlink(missing_ok=True)


def transform_features(features, source_crs, target_crs, z_scale=1.0) -> list[dict]:
    """Return independent features in a new horizontal CRS and explicit Z scale."""
    _validate_features(features)
    origin = _export_crs(source_crs)
    destination = _export_crs(target_crs)
    vertical_factor = _number(z_scale, "Elevation scale")
    if vertical_factor <= 0:
        raise ValueError("Elevation scale must be positive; use an explicit unit conversion factor.")
    transformed = copy.deepcopy(features)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")

    def xy_points(points):
        if not points:
            return []
        if origin == destination:
            return [[point[0], point[1]] for point in points]
        xs, ys = transform(origin, destination, [point[0] for point in points], [point[1] for point in points])
        return [[_number(x, "Transformed X"), _number(y, "Transformed Y")] for x, y in zip(xs, ys)]

    try:
        for feature in transformed:
            feature.setdefault("source_metrics", copy.deepcopy(feature["metrics"]))
            original_coordinates = feature["coordinates"]
            xy = xy_points(original_coordinates)
            coordinates = [point + [_number(original[2] * vertical_factor, "Transformed elevation")]
                           for point, original in zip(xy, original_coordinates)]
            feature["coordinates"] = coordinates
            if "anchors" in feature:
                feature["anchors"] = xy_points(feature["anchors"])
            distances = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(coordinates, coordinates[1:])]
            changes = [b[2] - a[2] for a, b in zip(coordinates, coordinates[1:])]
            elevations = [point[2] for point in coordinates]
            horizontal_length = sum(distances)
            horizontal_units = destination.linear_units if destination.is_projected else "degrees"
            # These measurements refer to the source raster grid or require a
            # known relationship between output horizontal and vertical units.
            # Retain them in source_metrics, not as properties of output XYZ.
            for key in ("working_resolution", "corridor_map_units", "corridor_map_units_xy",
                        "spacing_min_pixels", "spacing_median_pixels", "spacing_max_pixels",
                        "spacing_exception_count", "spacing_long_edge_count", "target_spacing_pixels",
                        "line_smoothing_pixels", "max_abs_grade_percent", "elevation_mismatch_vertices",
                        "sharp_guide_indices"):
                feature["metrics"].pop(key, None)
            if vertical_factor != 1:
                feature["metrics"]["source_vertical_units"] = feature["source_metrics"].get("vertical_units", "unspecified")
                feature["metrics"]["vertical_units"] = "unspecified (explicit Z multiplier; see provenance)"
            feature["metrics"].update({
                "length": _number(horizontal_length, "Transformed line length"),
                "vertices": len(coordinates),
                "units": horizontal_units,
                "length_units": horizontal_units,
                "elevation_min": min(elevations), "elevation_max": max(elevations),
                "elevation_start": elevations[0], "elevation_end": elevations[-1],
                "elevation_gain": sum(max(0, value) for value in changes),
                "elevation_loss": -sum(min(0, value) for value in changes),
                "elevation_change": coordinates[-1][2] - coordinates[0][2],
                "uphill_total": sum(max(0, value) for value in changes),
                "uphill_segments": sum(value > .001 for value in changes),
                "spacing_min": min(distances), "spacing_median": float(np.median(distances)),
                "spacing_max": max(distances),
            })
            feature["coordinate_crs"] = destination.to_wkt()
            feature.setdefault("provenance", []).append({
                "operation": "transform_coordinates",
                "time": timestamp,
                "details": {"source_crs_wkt": origin.to_wkt(), "target_crs_wkt": destination.to_wkt(),
                            "z_scale": vertical_factor, "vertical_datum_transform": False},
            })
        _validate_features(transformed)
        return transformed
    except Exception as exc:
        raise ValueError(f"Could not transform line coordinates: {exc}") from exc
