"""Allowlisted metadata for generated evaluation reports, not a general scrubber."""
from __future__ import annotations

import math
import re


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _token(value):
    # Opaque public IDs/basenames only, not relative/absolute/UNC/URI paths.
    return (type(value) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value)
            is not None and '..' not in value)


def _hash(value):
    return type(value) is str and re.fullmatch(r'[a-fA-F0-9]{64}', value) is not None


def _boolean(value):
    return type(value) is bool


def _nullable(check):
    return lambda value: value is None or check(value)


def _enum(*values):
    return lambda value: type(value) is str and value in values


_COUNTS = dict.fromkeys(('total', 'candidate', 'failure', 'abstention', 'ambiguous'), _number)
_DISTANCE = dict.fromkeys(('mean', 'median', 'p95', 'maximum', 'samples', 'actual_step',
                           'sampling_error_bound', 'p95_upper_bound', 'hausdorff_upper_bound'), _number)
_ASSET = {'file': _token, 'sha256': _hash, 'bytes': _number}
_PARAMS = dict.fromkeys(('corridor', 'smoothing', 'terrain_weight', 'spacing', 'simplify',
                         'line_smoothing'), _number)
_PARAMS['relax_anchors'] = _boolean
_PROVENANCE = {
    'manifest_id': _token, 'manifest_sha256': _hash,
    'method': _enum('legacy', 'auto'), 'engine_source_sha256': _hash, 'harness_sha256': _hash,
    'split': _enum('development', 'validation'),
    'assets': {'raster': _ASSET, 'reference': _ASSET},
    'module_sha256': dict.fromkeys(('evaluation.py', 'terrain.py', 'tracing.py',
                                  'analysis_grid.py', 'stream_auto.py'), _hash),
    'dependency_versions': dict.fromkeys(('numpy', 'scipy', 'rasterio'), _token),
    'resolved_trace_params': _PARAMS, 'max_dimension': _number,
}
_REACH = {
    'id': _token, 'guide_count': _number, 'seconds': _number,
    'status': _enum('candidate', 'failure', 'abstention', 'ambiguous'),
    'error_type': _enum('ValueError', 'RuntimeError', 'TypeError', 'KeyError', 'OSError',
                        'MemoryError', 'FloatingPointError', 'OverflowError', 'ZeroDivisionError'),
    'distances': dict.fromkeys(('prediction_to_reference', 'reference_to_prediction', 'symmetric'), _DISTANCE),
    'endpoint_displacement': [_number],
    'branch_correct': _nullable(_boolean), 'outlet_correct': _nullable(_boolean),
}
_REPORT = {
    'schema_version': _number, 'counts': _COUNTS, 'reaches': [_REACH],
    'candidate_coverage': _number, 'sampling_spacing': _number,
    'metric_units': _enum('source projected XY units'),
    'operator_time': _nullable(_number), 'operator_clicks': _nullable(_number),
    'reach_summary': {'scored_reaches': _number, 'symmetric_p95': ({
        'median': _number, 'p95': _number, 'maximum': _number, 'values': [_number]},)},
    'thresholds': {'max_p95': _nullable(_number), 'max_non_candidate_fraction': _number},
    'threshold_passed': _boolean, 'provenance': _PROVENANCE,
    'local_report_sha256': _hash, 'total_solver_and_scoring_seconds': _number,
}
_OMIT = object()


def _select(value, schema):
    # A one-element tuple declares a nullable structured field.
    if isinstance(schema, tuple):
        return None if value is None else _select(value, schema[0])
    if isinstance(schema, dict):
        if type(value) is not dict:
            return _OMIT
        result = {}
        for key, child_schema in schema.items():
            if key in value:
                child = _select(value[key], child_schema)
                if child is not _OMIT:
                    result[key] = child
        return result
    if isinstance(schema, list):
        if type(value) is not list:
            return _OMIT
        return [clean for child in value if (clean := _select(child, schema[0])) is not _OMIT]
    return value if schema(value) else _OMIT


def sanitize_report(value):
    """Select a detached, primitive-only subset of one generated report.

    Unknown keys/types, geometry, free-form errors/warnings/limitations, raw
    engine diagnostics, machine identity and terrain metadata are excluded.
    Asset descriptors retain reference hashes (unlike reach reference geometry).
    This schema is deliberately lossy, not a general privacy guarantee: public
    IDs and asset basenames still require independent privacy/license review.
    """
    clean = _select(value, _REPORT)
    return {} if clean is _OMIT else clean
