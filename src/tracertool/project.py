"""Validated project persistence and GIS interchange in the source DEM CRS.

Projects and GeoJSON retain the full feature metadata. GeoJSON deliberately uses
the older explicit-CRS extension; it is *not* an RFC 7946 WGS84 document. This
avoids silently transforming horizontal coordinates or claiming an ellipsoidal
vertical datum for elevations whose units and datum come from the source DEM.
Shapefiles preserve XYZ and expose the main tracing parameters as DBF fields.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
from uuid import uuid4

import shapefile
from rasterio.crs import CRS

from . import __version__


PROJECT_FORMAT = "tracertool-project"
PROJECT_VERSION = 1
_KINDS = {"ridge", "stream", "slope_break", "manual"}
_PARAMETERS = ("corridor", "smoothing", "terrain_weight", "spacing", "simplify")
_OPTIONAL_PARAMETERS = ("line_smoothing",)
_PARAMETER_FIELDS = (("corridor", "corr_px"), ("smoothing", "smooth_px"),
                     ("terrain_weight", "terr_wt"), ("spacing", "step_px"),
                     ("simplify", "simp_px"), ("line_smoothing", "smooth_ln"))
_SHAPE_SUFFIXES = (".shp", ".shx", ".dbf", ".prj", ".cpg")


def _path(value: str | os.PathLike[str], label: str) -> Path:
    try:
        if not os.fspath(value).strip():
            raise ValueError(f"Choose a {label} file path.")
        return Path(value).expanduser().resolve()
    except (TypeError, OSError, RuntimeError) as exc:
        raise ValueError(f"Invalid {label} file path: {exc}") from exc


def _json_value(value: Any, label: str) -> None:
    """Reject non-JSON values, including NaN/Infinity and non-string keys."""
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{label} contains a non-finite number.")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _json_value(child, f"{label}[{index}]")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{label} must use text object keys.")
            _json_value(child, f"{label}.{key}")
        return
    raise ValueError(f"{label} contains unsupported {type(value).__name__}; use JSON values.")


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number.")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number.")
    return number


def _validate_parameters(parameters: Any, label: str) -> None:
    if not isinstance(parameters, dict):
        raise ValueError(f"{label} parameters must be an object.")
    # Schema 1 originally stored only the five required parameters. Do not
    # populate missing optional settings with newer tracing defaults on load.
    for key in _PARAMETERS + tuple(key for key in _OPTIONAL_PARAMETERS if key in parameters):
        if key not in parameters:
            raise ValueError(f"{label} is missing tracing parameter {key}.")
        value = _number(parameters[key], f"{label} parameter {key}")
        if value < 0 or (key in {"corridor", "spacing"} and value == 0):
            bound = "positive" if key in {"corridor", "spacing"} else "zero or positive"
            raise ValueError(f"{label} parameter {key} must be {bound}.")
        if key == "line_smoothing" and value > 50:
            raise ValueError(f"{label} parameter line_smoothing must not exceed 50 working pixels.")


def _validate_anchors(anchors: Any, label: str, *, draft: bool = False) -> None:
    if not isinstance(anchors, list):
        raise ValueError(f"{label} anchors must be a list of native [x, y] points.")
    if not draft and len(anchors) == 1:
        raise ValueError(f"{label} needs at least two guide anchors, or an empty list.")
    for index, anchor in enumerate(anchors):
        if not isinstance(anchor, list) or len(anchor) != 2:
            raise ValueError(f"{label} anchor {index + 1} must contain exactly [x, y].")
        for value in anchor:
            _number(value, f"{label} anchor {index + 1}")


def _validate_settings(settings: Any) -> None:
    """Validate portable state; UI-specific display constraints live in the UI."""
    if not isinstance(settings, dict):
        raise ValueError("Project settings must be an object.")
    _json_value(settings, "Project settings")
    draft = settings.get("draft")
    if draft is not None:
        if not isinstance(draft, dict):
            raise ValueError("The saved draft must be an object.")
        if not isinstance(draft.get("kind"), str) or draft["kind"] not in _KINDS:
            raise ValueError("The saved draft needs a valid tracing kind.")
        if draft.get("coordinate_space", "native") != "native":
            raise ValueError("Saved draft anchors must use native map coordinates.")
        _validate_anchors(draft.get("anchors"), "Saved draft", draft=True)
        if "parameters" in draft:
            _validate_parameters(draft["parameters"], "Saved draft")
        if draft.get("edit_target") is not None and (not isinstance(draft["edit_target"], str) or not draft["edit_target"].strip()):
            raise ValueError("The saved draft edit_target must be a nonempty feature id.")
        segment = draft.get("segment_range")
        if segment is not None and (not isinstance(segment, list) or len(segment) != 2 or
                                    any(type(value) is not int or value < 0 for value in segment) or segment[0] >= segment[1]):
            raise ValueError("The saved draft segment_range must contain increasing nonnegative vertex indices.")
    reference = settings.get("terrain_reference")
    if isinstance(reference, dict):
        for key in ("sha256", "source_sha256"):
            digest = reference.get(key)
            if digest is not None and (not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest)):
                raise ValueError("The source SHA256 identity must contain 64 hexadecimal characters.")


def _validate_draft_target(features: list[dict], settings: dict) -> None:
    draft = settings.get("draft") or {}
    target = draft.get("edit_target")
    segment = draft.get("segment_range")
    if target is None:
        if segment is not None:
            raise ValueError("A saved segment correction must identify its edit_target line.")
        return
    feature = next((feature for feature in features if feature["id"] == target), None)
    if feature is None:
        raise ValueError("The saved draft refers to a line that is missing from the project.")
    if segment is not None and segment[1] >= len(feature["coordinates"]):
        raise ValueError("The saved correction range extends beyond its line's vertices.")


def _validate_features(features: Any, *, require_features: bool = False) -> None:
    if not isinstance(features, list):
        raise ValueError("Features must be a list of line features.")
    if require_features and not features:
        raise ValueError("There are no lines to export. Create or select at least one line.")
    identifiers: set[str] = set()
    required = {"id", "name", "kind", "coordinates", "metrics", "warnings", "parameters", "visible"}
    for index, feature in enumerate(features):
        label = f"Line {index + 1}"
        if not isinstance(feature, dict):
            raise ValueError(f"{label} must be an object.")
        missing = required - feature.keys()
        if missing:
            raise ValueError(f"{label} is missing required fields: {', '.join(sorted(missing))}.")
        _json_value(feature, label)
        for field in ("id", "name"):
            if not isinstance(feature[field], str) or not feature[field].strip():
                raise ValueError(f"{label} needs a nonempty {field}.")
            if "\x00" in feature[field]:
                raise ValueError(f"{label} {field} cannot contain a null character.")
        if feature["id"] in identifiers:
            raise ValueError(f"Duplicate line id {feature['id']!r}; every line needs a unique id.")
        identifiers.add(feature["id"])
        if not isinstance(feature["kind"], str) or feature["kind"] not in _KINDS:
            raise ValueError(f"{label} has an unknown kind; choose ridge, stream, slope_break, or manual.")
        if not isinstance(feature["visible"], bool):
            raise ValueError(f"{label} visible must be true or false.")
        coordinates = feature["coordinates"]
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise ValueError(f"{label} needs at least two XYZ vertices.")
        unique_xy = set()
        for vertex_index, coordinate in enumerate(coordinates):
            if not isinstance(coordinate, list) or len(coordinate) != 3:
                raise ValueError(f"{label}, vertex {vertex_index + 1}: provide exactly [x, y, z].")
            point = tuple(_number(value, f"{label}, vertex {vertex_index + 1}") for value in coordinate)
            unique_xy.add(point[:2])
        if len(unique_xy) < 2:
            raise ValueError(f"{label} has zero horizontal length; use two distinct map positions.")
        if not isinstance(feature["metrics"], dict):
            raise ValueError(f"{label} metrics must be an object.")
        if not isinstance(feature["warnings"], list) or any(not isinstance(w, str) for w in feature["warnings"]):
            raise ValueError(f"{label} warnings must be a list of text messages.")
        _validate_parameters(feature["parameters"], label)
        if "anchors" in feature:
            _validate_anchors(feature["anchors"], label)
        if "provenance" in feature and (not isinstance(feature["provenance"], list) or any(not isinstance(entry, dict) for entry in feature["provenance"])):
            raise ValueError(f"{label} provenance must be a list of event objects.")


def new_feature(name: str, kind: str, result: Any, params: Any) -> dict:
    """Create an independent, JSON-safe line record from a tracing result."""
    if not is_dataclass(params) or isinstance(params, type):
        raise ValueError("Tracing parameters must be a TraceParams dataclass instance.")
    try:
        feature = {
            "id": str(uuid4()),
            "name": name,
            "kind": kind,
            "coordinates": [list(coordinate) for coordinate in result.coordinates],
            "metrics": result.metrics,
            "warnings": result.warnings,
            "parameters": asdict(params),
            "visible": True,
        }
        if getattr(result, "anchors", None) is not None:
            feature["anchors"] = [list(anchor) for anchor in result.anchors]
    except (AttributeError, TypeError) as exc:
        raise ValueError("The trace result needs XYZ coordinates, metrics, and warnings.") from exc
    _validate_features([feature])
    # Detach all nested values, so future edits to a result cannot change a project.
    return json.loads(json.dumps(feature, allow_nan=False))


def _atomic_json(path: Path, document: dict) -> None:
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False) as handle:
            temporary = handle.name
            json.dump(document, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError(f"Could not save {path.name}: {exc}. Check the destination folder and available space.") from exc
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass


def _project_document(target: Path, terrain: Path, features: list[dict], settings: dict) -> dict:
    _validate_features(features)
    _validate_settings(settings)
    _validate_draft_target(features, settings)
    try:
        relative_terrain = Path(os.path.relpath(terrain, target.parent)).as_posix()
    except ValueError:
        relative_terrain = str(terrain)
    return {
        "format": PROJECT_FORMAT,
        "version": PROJECT_VERSION,
        "application_version": __version__,
        "terrain_path": relative_terrain,
        "features": features,
        "settings": settings,
    }


def _save_project_with_backup(target: Path, document: dict) -> None:
    """Keep the previous valid project in .bak; roll back ordinary commit errors."""
    if not target.is_file():
        _atomic_json(target, document)
        return
    try:
        load_project(target, allow_missing_terrain=True)
    except ValueError:
        # Never replace a known-good backup with corrupted or unrelated content.
        _atomic_json(target, document)
        return
    backup = target.with_name(target.name + ".bak")
    if backup.is_symlink() or (backup.exists() and not backup.is_file()):
        raise ValueError(f"Cannot update project backup {backup}: choose a regular file destination.")
    staging: Path | None = None
    preserve_recovery = False
    backup_changed = False
    had_backup = backup.is_file()
    try:
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.save-", dir=target.parent))
        staged_project = staging / "new-project.json"
        _atomic_json(staged_project, document)
        for source, destination in ((target, staging / "previous-good.json"), (backup, staging / "previous-backup.json")):
            if source == backup and not had_backup:
                continue
            with source.open("rb") as incoming, destination.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
                outgoing.flush()
                os.fsync(outgoing.fileno())
        os.replace(staging / "previous-good.json", backup)
        backup_changed = True
        os.replace(staged_project, target)
    except (OSError, ValueError) as exc:
        if backup_changed:
            try:
                if had_backup:
                    os.replace(staging / "previous-backup.json", backup)
                else:
                    backup.unlink(missing_ok=True)
            except OSError as rollback_exc:
                preserve_recovery = True
                raise ValueError(f"Project save failed: {exc}. The previous project is unchanged. Backup recovery files are in {staging}: {rollback_exc}") from exc
        raise ValueError(f"Could not save project {target.name}: {exc}. The previous project and backup are unchanged.") from exc
    finally:
        if staging is not None and not preserve_recovery:
            shutil.rmtree(staging, ignore_errors=True)


def save_project(path: str | os.PathLike[str], terrain_path: str | os.PathLike[str], features: list[dict], settings: dict) -> None:
    """Atomically save, retaining the previous valid project as ``filename.bak``."""
    target = _path(path, "project")
    terrain = _path(terrain_path, "terrain")
    if target == terrain or target.with_name(target.name + ".bak") == terrain:
        raise ValueError("The project path is the terrain file. Choose a separate project filename.")
    if not terrain.is_file():
        raise ValueError(f"Terrain file not found: {terrain}. Restore it before saving the project.")
    document = _project_document(target, terrain, features, settings)
    _save_project_with_backup(target, document)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"The project contains the duplicate object key {key!r}.")
        result[key] = value
    return result


def load_project(path: str | os.PathLike[str], *, allow_missing_terrain: bool = False) -> dict:
    """Read and validate a project, returning an absolute terrain path.

    ``allow_missing_terrain`` lets a caller offer a file-relink workflow. It only
    skips the file-existence check; all project and feature validation remains.
    The caller must load and verify the replacement raster before using lines.
    """
    source = _path(path, "project")
    try:
        with source.open(encoding="utf-8-sig") as handle:
            document = json.load(handle, object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError(f"Could not read project {source.name}: {exc}") from exc
    if not isinstance(document, dict) or document.get("format") != PROJECT_FORMAT:
        raise ValueError("This is not a TracerTool project. Open a saved TracerTool project JSON file.")
    if type(document.get("version")) is not int or document["version"] != PROJECT_VERSION:
        raise ValueError(f"Unsupported project version {document.get('version')!r}; this application reads version {PROJECT_VERSION}.")
    _json_value(document, "Project")
    _validate_features(document.get("features"))
    _validate_settings(document.get("settings"))
    _validate_draft_target(document["features"], document["settings"])
    terrain_value = document.get("terrain_path")
    if not isinstance(terrain_value, str) or not terrain_value.strip():
        raise ValueError("The project must specify its terrain_path.")
    terrain = _path(source.parent / terrain_value, "terrain")
    if not allow_missing_terrain and not terrain.is_file():
        raise ValueError(f"Project terrain file not found: {terrain}. Restore the terrain at that location, or update terrain_path in the project JSON.")
    document["terrain_path"] = str(terrain)
    return document


def _export_crs(value: Any) -> CRS:
    if value is None:
        raise ValueError("The terrain has no CRS. Assign the correct source CRS before exporting lines.")
    try:
        crs = CRS.from_user_input(value)
        if not crs:
            raise ValueError("empty CRS")
        return crs
    except (TypeError, ValueError, RuntimeError) as exc:
        raise ValueError(f"The export CRS is invalid: {exc}. Use the terrain's coordinate reference system.") from exc


def export_geojson(path: str | os.PathLike[str], features: list[dict], crs: Any) -> None:
    """Export legacy, explicit-native-CRS GeoJSON (not RFC 7946 GeoJSON)."""
    target = _path(path, "GeoJSON")
    _validate_features(features, require_features=True)
    source_crs = _export_crs(crs)
    authority = source_crs.to_authority()
    crs_name = f"urn:ogc:def:crs:{authority[0]}::{authority[1]}" if authority else source_crs.to_wkt()
    transformations = [entry["details"] for feature in features for entry in feature.get("provenance", [])
                       if entry.get("operation") == "transform_coordinates" and isinstance(entry.get("details"), dict)]
    reprojected = any(details.get("source_crs_wkt") != details.get("target_crs_wkt") for details in transformations)
    scaled_z = any(details.get("z_scale", 1) != 1 for details in transformations)
    document = {
        "type": "FeatureCollection",
        "name": target.stem,
        "crs": {"type": "name", "properties": {"name": crs_name}},
        "tracertool": {
            "application_version": __version__,
            "coordinate_system": "explicitly transformed output CRS" if reprojected else "native DEM CRS",
            "crs_wkt": source_crs.to_wkt(),
            "elevation": ("Stored Z includes explicit multipliers recorded in feature provenance; output vertical units are not inferred. No vertical datum transformation is performed."
                          if scaled_z else "Unmodified source DEM values; source vertical units and datum apply. No vertical datum transformation is performed."),
            "format_note": "Explicit-CRS GeoJSON extension; not an RFC 7946 WGS84 document.",
        },
        "features": [
            {
                "type": "Feature",
                "id": feature["id"],
                "properties": {key: value for key, value in feature.items() if key != "coordinates"},
                "geometry": {"type": "LineString", "coordinates": feature["coordinates"]},
            }
            for feature in features
        ],
    }
    _atomic_json(target, document)


def _short_utf8(text: str, size: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= size:
        return text
    return encoded[: size - 3].decode("utf-8", errors="ignore") + "..."


def _replace_shapefile(staged: list[Path], targets: list[Path], backup_dir: Path, obsolete: list[Path] | None = None) -> None:
    """Commit a staged sidecar set, restoring old files on an ordinary I/O error.

    Multiple files cannot be made power-loss atomic as a unit. All content is
    fully written before the short commit, and replacement failures roll back.
    """
    backups: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for target in targets + (obsolete or []):
            if target.exists():
                if not target.is_file():
                    raise ValueError(f"The export target is a directory: {target}")
                backup = backup_dir / (target.name + ".backup")
                os.replace(target, backup)
                backups.append((target, backup))
        for source, target in zip(staged, targets):
            os.replace(source, target)
            installed.append(target)
    except (OSError, ValueError) as exc:
        rollback_errors = []
        for target in installed:
            try:
                target.unlink(missing_ok=True)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        for target, backup in reversed(backups):
            try:
                os.replace(backup, target)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        if rollback_errors:
            # The caller preserves this directory when rollback is incomplete.
            raise ValueError(f"Shapefile replacement failed: {exc}. Recovery files are in {backup_dir}. " + "; ".join(rollback_errors)) from exc
        raise ValueError(f"Shapefile replacement failed: {exc}. Any previous export was restored.") from exc


def export_shapefile(path: str | os.PathLike[str], features: list[dict], crs: Any) -> list[str]:
    """Write a native-CRS PolyLineZ set, with UTF-8 DBF and an ESRI WKT .prj.

    Warning text is shortened to fit DBF's 254-byte field limit; the warning
    count and tracing parameters remain available. Use the project or GeoJSON
    when full nested metrics, per-segment editing history and warning text are
    needed. Parameter fields describe the feature's tracing settings; later
    partial corrections retain their own parameters in project provenance.
    Existing spatial and
    attribute indexes are invalidated when geometry/attributes are replaced.
    """
    target = _path(path, "shapefile").with_suffix(".shp")
    _validate_features(features, require_features=True)
    source_crs = _export_crs(crs)
    for feature in features:
        for field in ("id", "name"):
            if len(feature[field].encode("utf-8")) > 254:
                raise ValueError(f"Line {feature['name']!r}: {field} exceeds the shapefile 254-byte limit. Shorten it or export GeoJSON.")
    targets = [target.with_suffix(suffix) for suffix in _SHAPE_SUFFIXES]
    staging_dir: Path | None = None
    preserve_recovery = False
    try:
        staging_dir = Path(tempfile.mkdtemp(prefix=f".{target.stem}.export-", dir=target.parent))
        staged = [staging_dir / output.name for output in targets]
        with shapefile.Writer(str(staged[0]), shapeType=shapefile.POLYLINEZ, encoding="utf-8") as writer:
            writer.field("line_id", "C", 254)
            writer.field("name", "C", 254)
            writer.field("kind", "C", 16)
            writer.field("vertices", "N", 10, 0)
            writer.field("len_xy", "F", 24, 8)
            for _, field in _PARAMETER_FIELDS:
                writer.field(field, "F", 24, 8)
            writer.field("edited", "L")
            writer.field("prov_cnt", "N", 10, 0)
            writer.field("last_op", "C", 64)
            writer.field("warn_cnt", "N", 10, 0)
            writer.field("warnings", "C", 254)
            writer.field("app_ver", "C", 20)
            for feature in features:
                coordinates = feature["coordinates"]
                length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(coordinates, coordinates[1:]))
                numeric_values = [length] + [float(feature["parameters"].get(key, 0)) for key, _ in _PARAMETER_FIELDS]
                if any(not math.isfinite(value) or len(f"{value:.8f}") > 24 for value in numeric_values):
                    raise ValueError(f"Line {feature['name']!r} has values too large for shapefile numeric fields. Export GeoJSON instead.")
                writer.linez([coordinates])
                history = feature.get("provenance", [])
                last_operation = history[-1].get("operation", "") if history else ""
                last_operation = last_operation if isinstance(last_operation, str) else ""
                edited = (feature["metrics"].get("geometry_edited") is True or
                          feature["metrics"].get("manually_edited") is True)
                writer.record(feature["id"], feature["name"], feature["kind"], len(coordinates), *numeric_values,
                              edited, len(history), _short_utf8(last_operation, 64), len(feature["warnings"]),
                              _short_utf8("; ".join(feature["warnings"]), 254), __version__)
        staged[3].write_text(source_crs.to_wkt(version="WKT1_ESRI"), encoding="utf-8")
        staged[4].write_text("UTF-8\n", encoding="ascii")
        index_suffixes = {".sbn", ".sbx", ".qix", ".fix", ".ain", ".aih", ".ixs", ".mxs"}
        basename = target.stem.casefold()
        obsolete = [candidate for candidate in target.parent.iterdir()
                    if candidate.is_file() and
                    ((candidate.stem.casefold() == basename and candidate.suffix.casefold() in index_suffixes) or
                     (candidate.name.casefold().startswith(basename + ".") and candidate.suffix.casefold() == ".atx"))]
        try:
            _replace_shapefile(staged, targets, staging_dir, obsolete)
        except ValueError:
            preserve_recovery = any(staging_dir.glob("*.backup"))
            raise
        return [str(output) for output in targets]
    except (OSError, ValueError, shapefile.ShapefileException) as exc:
        raise ValueError(f"Could not export shapefile: {exc}") from exc
    finally:
        if staging_dir is not None and not preserve_recovery:
            shutil.rmtree(staging_dir, ignore_errors=True)
