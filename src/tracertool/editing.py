"""Pure line editing with exact NoData checks and auditable geometry changes.

Existing vertices keep their XYZ values. New/moved vertices sample the DEM;
full replacements resample all vertices. Local retraces restore both original
boundary vertices verbatim, even when the tracer snapped fractional anchors.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
import math
from uuid import uuid4

from .tracing import (TraceParams, _resample, _simplify, _sharp_guide_indices,
                      _guide_warning, validate_segments)


_DYNAMIC_WARNINGS = (
    'This line contains uphill', 'Traced on a reduced working grid',
    'The DEM does not identify vertical units', 'This DEM has rectangular pixels',
    'Some retained elevations differ', 'Stopped at ',
    'Guide anchor(s)',
)


def _copy_feature(feature):
    if not isinstance(feature, dict):
        raise ValueError('Choose an existing line to edit.')
    try:
        out = json.loads(json.dumps(feature, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError('The line contains invalid project data.') from exc
    if not isinstance(out.get('id'), str) or not out['id']:
        raise ValueError('The line needs a persistent identity before editing.')
    if out.get('kind') not in {'ridge', 'stream', 'slope_break', 'manual'}:
        raise ValueError('The line has an unsupported tracing kind.')
    _coordinates(out.get('coordinates'))
    return out


def _coordinates(coordinates):
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
        raise ValueError('A line needs at least two distinct XYZ vertices.')
    result = []
    for point in coordinates:
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            raise ValueError('Line vertices must contain exactly XYZ coordinates.')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point):
            raise ValueError('Line coordinates must be finite numbers.')
        result.append(list(point))
    for a, b in zip(result[:-1], result[1:]):
        if a[:2] == b[:2]:
            raise ValueError('The edit would create a zero-length edge. Use distinct neighboring vertices.')
    return result


def _index(index, count):
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < count:
        raise ValueError('Choose a vertex belonging to this line.')
    return index


def _point(terrain, xy):
    if not isinstance(xy, (list, tuple)) or len(xy) != 2:
        raise ValueError('A cursor position must contain native X and Y coordinates.')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in xy):
        raise ValueError('The cursor position must contain finite numbers.')
    x, y = xy
    z = terrain.sample(x, y)
    if z is None:
        raise ValueError('The new vertex is outside the DEM or on NoData.')
    return [x, y, z]


def _finish(terrain, feature, coordinates, operation, details=None, *, retain_anchors=False):
    out = _copy_feature(feature)
    coordinates = _coordinates(coordinates)
    validate_segments(terrain, coordinates)
    distances = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(coordinates[:-1], coordinates[1:])]
    changes = [b[2] - a[2] for a, b in zip(coordinates[:-1], coordinates[1:])]
    elevations = [p[2] for p in coordinates]
    gain, loss = sum(max(d, 0) for d in changes), -sum(min(d, 0) for d in changes)
    samples = terrain.sample_many([p[:2] for p in coordinates])
    mismatch = sum(not math.isclose(p[2], z, abs_tol=1e-5, rel_tol=1e-7) for p, z in zip(coordinates, samples))
    warnings = [w for w in out.get('warnings', []) if isinstance(w, str) and not w.startswith(_DYNAMIC_WARNINGS)]
    if terrain.metadata.get('resampled'):
        warnings.append('Traced on a reduced working grid; inspect against the original DEM before production use.')
    if terrain.metadata.get('vertical_units_assumed'):
        warnings.append('The DEM does not identify vertical units. Elevations are preserved; slope displays assume horizontal units.')
    if not math.isclose(abs(terrain.transform.a), abs(terrain.transform.e), rel_tol=1e-6):
        warnings.append('This DEM has rectangular pixels. Corridor, smoothing, and spacing are measured in working pixels; map-unit sizes vary with direction.')
    if out['kind'] == 'stream' and gain > max(.001, (max(elevations) - min(elevations)) * .02):
        warnings.append('This line contains uphill segments. Check direction, pits, bridges, and anchor placement; no depression filling is applied.')
    if mismatch:
        warnings.append('Some retained elevations differ from current DEM samples; original XYZ values were preserved.')
    params = out.get('parameters', {})
    corridor = float(params.get('corridor', TraceParams().corridor))
    target_spacing = float(params.get('spacing', TraceParams().spacing))
    pixel_points = [terrain.rc(p[0], p[1]) for p in coordinates]
    pixel_edges = [math.dist(a, b) for a, b in zip(pixel_points[:-1], pixel_points[1:])]
    ordered_pixels, ordered_map = sorted(pixel_edges), sorted(distances)
    def median(values):
        middle = len(values) // 2
        return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    metrics = {
        'length': float(sum(distances)), 'units': terrain.units,
        'vertices': len(coordinates), 'elevation_min': float(min(elevations)),
        'elevation_max': float(max(elevations)), 'elevation_start': float(elevations[0]),
        'elevation_end': float(elevations[-1]), 'elevation_gain': float(gain),
        'elevation_loss': float(loss), 'uphill_segments': sum(d > .001 for d in changes),
        'vertical_units': terrain.metadata.get('vertical_units', 'unspecified'),
        'working_resolution': terrain.resolution, 'corridor_map_units': corridor * terrain.resolution,
        'corridor_map_units_xy': [corridor * abs(terrain.transform.a), corridor * abs(terrain.transform.e)],
        'spacing_min': min(distances), 'spacing_median': median(ordered_map), 'spacing_max': max(distances),
        'spacing_min_pixels': min(pixel_edges), 'spacing_median_pixels': median(ordered_pixels), 'spacing_max_pixels': max(pixel_edges),
        'target_spacing_pixels': target_spacing,
        'spacing_exception_count': sum(edge < target_spacing * .625 for edge in pixel_edges),
        'spacing_long_edge_count': sum(edge > target_spacing * (1 + 1e-8) for edge in pixel_edges),
        'kind': out['kind'], 'geometry_edited': True, 'manually_edited': True, 'elevation_mismatch_vertices': mismatch,
    }
    if retain_anchors and out.get('anchors'):
        # Match repeated guide positions in traversal order. Reverse retains
        # guides, whereas every geometry-changing edit invalidates them.
        indices, cursor = [], 0
        for anchor in out['anchors']:
            match = next((i for i in range(cursor, len(coordinates))
                          if math.dist(coordinates[i][:2], anchor) < 1e-7), None)
            if match is None:
                indices = []
                break
            indices.append(match)
            cursor = match + 1
        if len(indices) >= 2:
            sharp = _sharp_guide_indices(coordinates, indices)
            metrics['sharp_guide_indices'] = sharp
            if sharp and out['kind'] != 'manual':
                warnings.append(_guide_warning(sharp))
    if not terrain.metadata.get('vertical_units_assumed'):
        scale = terrain.metadata.get('vertical_to_horizontal', 1.)
        metrics['max_abs_grade_percent'] = max(abs(dz) * scale / ds * 100 for dz, ds in zip(changes, distances))
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    record = {'operation': operation, 'time': timestamp, 'details': details or {},
              'source_crs': terrain.metadata.get('crs'), 'working_resolution': terrain.resolution}
    if terrain.metadata.get('source_sha256'):
        record['source_sha256'] = terrain.metadata['source_sha256']
    history = out.get('provenance', [])
    if not isinstance(history, list) or any(not isinstance(entry, dict) for entry in history):
        raise ValueError('The line has invalid editing provenance.')
    out.update(coordinates=coordinates, metrics=metrics, warnings=list(dict.fromkeys(warnings)),
               provenance=history + [record], modified_at=timestamp)
    if not retain_anchors:
        out.pop('anchors', None)
        out.pop('fixed_anchor_indices', None)
    try:
        return json.loads(json.dumps(out, allow_nan=False))
    except (ValueError, TypeError) as exc:
        raise ValueError('The edit produced invalid project metadata.') from exc


def move_vertex(terrain, feature, index, xy):
    source = _copy_feature(feature)
    coordinates = source['coordinates']
    _index(index, len(coordinates))
    before = deepcopy(coordinates[index])
    coordinates[index] = _point(terrain, xy)
    return _finish(terrain, feature, coordinates, 'move_vertex', {'index': index, 'before': before, 'after': coordinates[index]})


def insert_vertex(terrain, feature, after_index, xy):
    source = _copy_feature(feature)
    coordinates = source['coordinates']
    _index(after_index, len(coordinates))
    coordinates.insert(after_index + 1, _point(terrain, xy))
    return _finish(terrain, feature, coordinates, 'insert_vertex', {'after_index': after_index, 'vertex': coordinates[after_index + 1]})


def delete_vertex(terrain, feature, index):
    source = _copy_feature(feature)
    coordinates = source['coordinates']
    _index(index, len(coordinates))
    if len(coordinates) <= 2:
        raise ValueError('A line must retain at least two vertices. Delete the whole feature instead.')
    before = coordinates.pop(index)
    return _finish(terrain, feature, coordinates, 'delete_vertex', {'index': index, 'removed': before})


def reverse_feature(terrain, feature):
    source = _copy_feature(feature)
    if 'anchors' in source:
        source['anchors'] = list(reversed(source['anchors']))
        if 'fixed_anchor_indices' in source:
            source['fixed_anchor_indices'] = sorted(len(source['anchors']) - 1 - i for i in source['fixed_anchor_indices'])
    return _finish(terrain, source, list(reversed(source['coordinates'])), 'reverse_feature', retain_anchors=True)


def split_feature(terrain, feature, index):
    source = _copy_feature(feature)
    coordinates = source['coordinates']
    _index(index, len(coordinates))
    if index in (0, len(coordinates) - 1):
        raise ValueError('Split at an internal vertex so both resulting lines have at least two vertices.')
    second_id = str(uuid4())
    first = _finish(terrain, feature, coordinates[:index + 1], 'split_feature',
                    {'index': index, 'part': 1, 'other_id': second_id})
    second = _finish(terrain, feature, coordinates[index:], 'split_feature',
                     {'index': index, 'part': 2, 'source_id': source['id']})
    second['id'] = second_id
    second['name'] = source.get('name', 'Line') + ' (split)'
    return first, second


def join_features(terrain, first, second, tolerance):
    a, b = _copy_feature(first), _copy_feature(second)
    if a['id'] == b['id']:
        raise ValueError('Choose two different lines to join.')
    if a['kind'] != b['kind']:
        raise ValueError('Join lines of the same kind so their tracing meaning remains clear.')
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError('Join tolerance must be a finite nonnegative map distance.')
    ac, bc = a['coordinates'], b['coordinates']
    distance, ai, bi = min((math.hypot(ac[i][0] - bc[j][0], ac[i][1] - bc[j][1]), i, j)
                           for i in (0, len(ac) - 1) for j in (0, len(bc) - 1))
    if distance > tolerance:
        raise ValueError(f'The closest endpoints are {distance:.3f} {terrain.units} apart, beyond the {tolerance:g} tolerance.')
    if ai == 0:
        ac = list(reversed(ac))
    if bi == len(bc) - 1:
        bc = list(reversed(bc))
    coordinates = ac + (bc[1:] if distance == 0 else bc)
    out = _finish(terrain, first, coordinates, 'join_features',
                  {'joined_id': b['id'], 'joined_name': b.get('name', ''),
                   'gap': distance, 'tolerance': tolerance,
                   'connection': 'shared_endpoint' if distance == 0 else 'bridge',
                   'first_endpoint_xyz': deepcopy(ac[-1]), 'second_endpoint_xyz': deepcopy(bc[0]),
                   'first_reversed': ai == 0, 'second_reversed': bi == len(b['coordinates']) - 1,
                   'joined_parameters': b.get('parameters', {}), 'joined_provenance': b.get('provenance', [])})
    return out


def replace_segment(terrain, feature, start, end, result, params):
    """Replace inclusive vertex range while preserving exact original borders.

    Tracing works at cell centers, but corrections often start at fractional
    vertices. Both boundary XYZ coordinates are restored before validating all
    new connections. Segment-specific parameters are recorded in provenance;
    the original feature's overall parameter record remains unchanged.
    """
    source = _copy_feature(feature)
    coordinates = source['coordinates']
    _index(start, len(coordinates)); _index(end, len(coordinates))
    if start >= end:
        raise ValueError('The correction must start before its final vertex.')
    try:
        replacement = _coordinates(result.coordinates)
    except AttributeError as exc:
        raise ValueError('A correction needs a completed tracing result.') from exc
    if not is_dataclass(params) or isinstance(params, type):
        raise ValueError('A correction needs TraceParams for its provenance.')
    # Accept a result supplied in the opposite click direction when unambiguous.
    def gap(p, q):
        return math.hypot(p[0] - q[0], p[1] - q[1])
    forward = gap(replacement[0], coordinates[start]) + gap(replacement[-1], coordinates[end])
    backward = gap(replacement[-1], coordinates[start]) + gap(replacement[0], coordinates[end])
    reversed_trace = backward < forward
    if reversed_trace:
        replacement.reverse()
    replacement = [deepcopy(coordinates[start])] + [_point(terrain, p[:2]) for p in replacement[1:-1]] + [deepcopy(coordinates[end])]
    updated = coordinates[:start] + replacement + coordinates[end + 1:]
    return _finish(terrain, feature, updated, 'replace_segment',
                   {'start_index': start, 'end_index': end, 'old_vertices': end - start + 1,
                    'new_vertices': len(replacement), 'parameters': asdict(params),
                    'trace_reversed': reversed_trace, 'boundary_xyz_preserved': True,
                    'anchors': deepcopy(getattr(result, 'anchors', []))})


def refresh_feature(terrain, feature, coordinates, operation):
    """Replace a complete line and resample every vertex from the source DEM."""
    if not isinstance(operation, str) or not operation.strip():
        raise ValueError('Name the operation so this replacement can be audited.')
    coordinates = _coordinates(coordinates)
    sampled = [_point(terrain, p[:2]) for p in coordinates]
    return _finish(terrain, feature, sampled, operation,
                   {'full_replacement': True, 'old_vertices': len(feature.get('coordinates', [])),
                    'new_vertices': len(sampled)})


def reconstruct_anchors(terrain, feature, tolerance_pixels=2., max_spacing_pixels=100.):
    """Derive sparse native XY guides from legacy/manual geometry on request.

    These are reconstructed guides, not the original user anchors. Simplify
    within a working-pixel tolerance while retaining NoData-safe connections,
    then bound guide separation to help trace long or winding reaches.
    """
    source = _copy_feature(feature)
    coordinates = source['coordinates']
    validate_segments(terrain, coordinates)
    if not math.isfinite(tolerance_pixels) or tolerance_pixels < 0:
        raise ValueError('Guide simplification tolerance must be finite and nonnegative.')
    if not math.isfinite(max_spacing_pixels) or max_spacing_pixels < .25:
        raise ValueError('Maximum guide spacing must be at least 0.25 working pixels.')
    cells = [terrain.rc(p[0], p[1]) for p in coordinates]
    guides = _resample(_simplify(cells, tolerance_pixels, terrain.valid), max_spacing_pixels, mask=terrain.valid, tolerance=tolerance_pixels)
    xy = [list(terrain.xy(r, c)) for r, c in guides]
    xy[0], xy[-1] = deepcopy(coordinates[0][:2]), deepcopy(coordinates[-1][:2])
    return xy
