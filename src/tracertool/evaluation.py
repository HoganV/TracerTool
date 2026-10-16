"""Paired reach discrepancy evaluation, not a hydrological accuracy certificate.

Midpoint quadrature is uniform in arc length. Distances to the target are exact
Euclidean point-to-continuous-segment distances. Since distance to a closed set
is 1-Lipschitz, each source interval differs from its midpoint by at most h/2.
This bounds mean, quantiles, and the continuous directed Hausdorff maximum by
h/2 (quantiles refer to the arc-length measure, not vertex counts).
"""
from __future__ import annotations

import math
import hashlib
import json
from pathlib import Path
import time
from copy import deepcopy
import numpy as np

MAX_SAMPLES = 1_000_000


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load_pair(manifest_path, data_dir):
    """Read frozen ESRI reference pair; hashes and CRS must match exactly."""
    import rasterio
    manifest_path, data_dir = Path(manifest_path), Path(data_dir).resolve()
    if manifest_path.stat().st_size > 2_000_000:
        raise ValueError('Manifest exceeds size budget')
    manifest = json.loads(manifest_path.read_text())
    if manifest['schema_version'] != 1 or manifest['split'] not in ('development', 'validation'):
        raise ValueError('Unsupported manifest or blind acceptance split: do not inspect holdout')
    assets = {}
    for key in ('raster', 'reference'):
        spec = manifest['assets'][key]
        path = (data_dir / spec['file']).resolve()
        if not path.is_relative_to(data_dir):
            raise ValueError('Asset path escapes data directory')
        if sha256_file(path) != spec['sha256']:
            raise ValueError(f'Hash mismatch: {key}')
        assets[key] = path
    if assets['reference'].stat().st_size > 20_000_000:
        raise ValueError('Vector exceeds size budget')
    vector = json.loads(assets['reference'].read_text())
    if vector.get('error') or vector.get('exceededTransferLimit'):
        raise ValueError('Incomplete or failed vector response')
    vector_crs = rasterio.crs.CRS.from_epsg(vector['spatialReference'].get('latestWkid', vector['spatialReference']['wkid']))
    expected = rasterio.crs.CRS.from_string(manifest['crs'])
    cases = []
    with rasterio.open(assets['raster']) as ds:
        if ds.crs != expected or vector_crs != expected or not expected.is_projected:
            raise ValueError('Raster, reference and manifest must share a projected CRS')
        for spec in manifest['cases']:
            matches = [f for f in vector['features'] if f['attributes']['objectid'] == spec['feature_id']]
            if len(matches) != 1:
                raise ValueError('Missing or duplicate reference feature')
            line = _line(matches[0]['geometry']['paths'][spec['path_index']])
            left, bottom, right, top = ds.bounds
            if not ((line[:, 0] >= left) & (line[:, 0] < right) & (line[:, 1] > bottom) & (line[:, 1] <= top)).all():
                raise ValueError('Complete reference geometry is not raster-covered')
            guides = [line[i].tolist() for i in spec['guide_indices']]
            if len(guides) < 2:
                raise ValueError('At least two explicit guides required')
            cases.append(dict(id=spec['id'], reference=line.tolist(), guides=guides))
    return manifest, assets, cases


def run_pair(manifest_path, data_dir, method='legacy', spacing=1.0, max_dimension=2500):
    """Lazy engine dispatch; no reference geometry is supplied to either engine."""
    from .terrain import Terrain
    from .tracing import default_params
    manifest, assets, cases = load_pair(manifest_path, data_dir)
    module_names = ('evaluation.py', 'terrain.py', 'tracing.py', 'analysis_grid.py', 'stream_auto.py')
    module_hashes = {name: sha256_file(Path(__file__).with_name(name)) for name in module_names}
    terrain = Terrain.load(assets['raster'], max_dimension=max_dimension)
    params = default_params(terrain, 'stream')
    if method == 'legacy':
        from .tracing import trace
        engine_source = Path(__file__).with_name('tracing.py')
        def engine(guides, case_id):
            return trace(terrain, [terrain.rc(*xy) for xy in guides], 'stream', params)
    elif method == 'auto':
        from .stream_auto import trace_auto
        engine_source = Path(__file__).with_name('stream_auto.py')
        def engine(guides, case_id):
            return trace_auto(terrain, [terrain.rc(*xy) for xy in guides], params)
    else:
        raise ValueError('Unknown method')
    report = evaluate_cases(cases, engine, spacing)
    from dataclasses import asdict
    import platform
    import sys
    report['provenance'] = dict(manifest_sha256=sha256_file(manifest_path), manifest_id=manifest['id'],
        method=method, engine_source_sha256=sha256_file(engine_source),
        harness_sha256=sha256_file(__file__), split=manifest['split'], label_role=manifest['label_role'],
        assets=manifest['assets'], resolved_trace_params=asdict(params), terrain=terrain.metadata,
        max_dimension=max_dimension, python=sys.version, platform=platform.platform())
    from importlib.metadata import version
    if any(sha256_file(Path(__file__).with_name(name)) != value for name, value in module_hashes.items()):
        raise ValueError('Evaluation source changed during execution; rerun on a stable snapshot')
    report['provenance']['module_sha256'] = module_hashes
    report['provenance']['dependency_versions'] = {
        name: version(name) for name in ('numpy', 'scipy', 'rasterio')}
    return report


def _line(coordinates):
    points = np.asarray(coordinates, dtype=float)
    if points.ndim != 2 or points.shape[0] < 2 or points.shape[1] < 2:
        raise ValueError('A line needs at least two XY vertices')
    points = points[:, :2]
    if not np.isfinite(points).all():
        raise ValueError('Non-finite XY coordinates')
    points = points[np.r_[True, np.any(np.diff(points, axis=0) != 0, axis=1)]]
    if len(points) < 2:
        raise ValueError('Zero-length line')
    with np.errstate(over='ignore', invalid='ignore', under='ignore'):
        squared = np.sum(np.diff(points, axis=0) ** 2, axis=1)
    if not np.isfinite(squared).all() or np.any(squared <= 0):
        raise ValueError('Numerically degenerate or non-finite segment length')
    return points


def uniform_samples(coordinates, spacing=1.0):
    """Equal arc-length interval midpoints, with actual step <= spacing."""
    if not math.isfinite(spacing) or spacing <= 0:
        raise ValueError('Spacing must be finite and positive')
    points = _line(coordinates)
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cumulative = np.r_[0., np.cumsum(lengths)]
    count = math.ceil(cumulative[-1] / spacing)
    if count > MAX_SAMPLES:
        raise ValueError('Sampling exceeds bounded sample budget')
    step = float(cumulative[-1] / count)
    distances = (np.arange(count) + .5) * step
    return np.column_stack([np.interp(distances, cumulative, points[:, i]) for i in (0, 1)]), step


def point_line_distances(points, coordinates):
    """Exact nearest continuous-segment distances, bounded-memory chunking."""
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError('Expected finite XY sample points')
    line = _line(coordinates)
    result = np.full(len(points), np.inf)
    for offset in range(0, len(line) - 1, 256):
        starts = line[offset:offset + 256]
        ends = line[offset + 1:offset + 257]
        starts = starts[:len(ends)]
        delta = ends - starts
        squared = np.sum(delta * delta, axis=1)
        for first in range(0, len(points), 512):
            relative = points[first:first + 512, None, :] - starts[None, :, :]
            t = np.clip(np.sum(relative * delta, axis=2) / squared, 0, 1)
            distances = np.linalg.norm(relative - t[:, :, None] * delta, axis=2).min(axis=1)
            result[first:first + len(distances)] = np.minimum(result[first:first + len(distances)], distances)
    return result


def _distance_summary(distances, step):
    return dict(mean=float(np.mean(distances)), median=float(np.quantile(distances, .5, method='inverted_cdf')),
                p95=float(np.quantile(distances, .95, method='inverted_cdf')), maximum=float(np.max(distances)),
                samples=len(distances), actual_step=step, sampling_error_bound=step / 2)


def compare_lines(prediction, reference, spacing=1.0):
    """Two directed summaries; symmetric scores weight the directions equally."""
    directed = []
    for source, target in ((prediction, reference), (reference, prediction)):
        samples, step = uniform_samples(source, spacing)
        directed.append(_distance_summary(point_line_distances(samples, target), step))
    forward, reverse = directed
    symmetric = {key: (forward[key] + reverse[key]) / 2 for key in ('mean', 'median')}
    # A directed p95 can miss discrepancies on <5% of a reach; maximum and
    # independent branch review remain necessary. Thresholds use the bound.
    symmetric['p95'] = max(forward['p95'], reverse['p95'])
    symmetric['p95_upper_bound'] = max(d['p95'] + d['sampling_error_bound'] for d in directed)
    symmetric['maximum'] = max(forward['maximum'], reverse['maximum'])
    symmetric['hausdorff_upper_bound'] = max(d['maximum'] + d['sampling_error_bound'] for d in directed)
    return dict(prediction_to_reference=forward, reference_to_prediction=reverse, symmetric=symmetric)


def evaluate_cases(cases, solver, spacing=1.0):
    """Solver receives ONLY declared guides and opaque ID, never reference XY.

    ``solver(guides_xy, case_id)`` returns the core TraceResult contract.
    Unresolved results abstain even if they carry partial geometry. Ambiguous
    geometry is scored but never counted as an unqualified candidate.
    """
    if not math.isfinite(spacing) or spacing <= 0:
        raise ValueError('Spacing must be finite and positive')
    counts = dict(total=len(cases), candidate=0, failure=0, abstention=0, ambiguous=0)
    rows = []
    if len({case['id'] for case in cases}) != len(cases):
        raise ValueError('Duplicate reach IDs')
    for case in cases:
        row = dict(id=case['id'], guide_count=len(case['guides']))
        started = time.perf_counter()
        try:
            result = solver(deepcopy(case['guides']), case['id'])
            status = result.metrics.get('status', 'candidate')
            if status not in ('candidate', 'ambiguous', 'unresolved'):
                raise ValueError(f'Unknown solver status: {status}')
            row.update(status='abstention' if status == 'unresolved' else status,
                       engine_metrics=result.metrics, warnings=result.warnings)
            if status != 'unresolved':
                row['distances'] = compare_lines(result.coordinates, case['reference'], spacing)
                row['prediction'] = result.coordinates
                # Endpoint intent is recorded, not mistaken for branch correctness.
                pred, ref = _line(result.coordinates), _line(case['reference'])
                row['endpoint_displacement'] = [float(np.linalg.norm(pred[i] - ref[i])) for i in (0, -1)]
            row['branch_correct'] = None
            row['outlet_correct'] = None
            # Validate before counting or aggregating. A partial/non-finite
            # score must not poison the completed report or count as coverage.
            json.dumps(row, allow_nan=False)
        except Exception as error:
            for key in ('distances', 'prediction', 'endpoint_displacement', 'engine_metrics', 'warnings'):
                row.pop(key, None)
            row.update(status='failure', error_type=type(error).__name__, error=str(error))
        row['seconds'] = time.perf_counter() - started
        counts[row['status']] += 1
        rows.append(row)
    scored = [r['distances']['symmetric']['p95'] for r in rows if 'distances' in r]
    summary = dict(scored_reaches=len(scored), symmetric_p95=None)
    if scored:
        summary['symmetric_p95'] = dict(median=float(np.median(scored)), p95=float(np.quantile(scored, .95)),
                                        maximum=float(max(scored)), values=scored)
    return dict(schema_version=1, counts=counts, reaches=rows, reach_summary=summary,
                candidate_coverage=counts['candidate'] / len(cases) if cases else 0,
                sampling_spacing=spacing, metric_units='source projected XY units',
                operator_time=None, operator_clicks=None,
                limitations=['Discrepancy against unreviewed labels is not validated accuracy',
                             'Branch/outlet correctness and operator effort not independently reviewed'])


def compare_reports(baseline, contender):
    """Equal-weight paired reach deltas; no survivor-only promotion assertion."""
    if baseline['sampling_spacing'] != contender['sampling_spacing']:
        raise ValueError('Paired reports must use the same scoring spacing')
    before = {r['id']: r for r in baseline['reaches']}
    after = {r['id']: r for r in contender['reaches']}
    if before.keys() != after.keys():
        raise ValueError('Paired reports must contain the same reach IDs')
    for key in ('manifest_sha256', 'max_dimension'):
        if baseline.get('provenance', {}).get(key) != contender.get('provenance', {}).get(key):
            raise ValueError('Paired reports have different manifest or analysis settings')
    rows, missing = [], []
    for reach_id in before:
        b, a = before[reach_id], after[reach_id]
        if 'distances' not in b or 'distances' not in a:
            missing.append(reach_id)
            continue
        old, new = b['distances']['symmetric']['p95'], a['distances']['symmetric']['p95']
        rows.append(dict(id=reach_id, baseline_p95=old, contender_p95=new, delta=new - old,
                         relative_gain=(old - new) / old if old else None))
    gains = [r['relative_gain'] for r in rows if r['relative_gain'] is not None]
    return dict(total_reaches=len(before), comparable_reaches=len(rows), unscored_reaches=missing, paired_reaches=rows,
                median_paired_p95_delta=float(np.median([r['delta'] for r in rows])) if rows else None,
                median_paired_relative_gain=float(np.median(gains)) if gains else None,
                baseline_counts=baseline['counts'], contender_counts=contender['counts'],
                promotion_evidence=False,
                limitation='Exposed unreviewed pilots; paired survivors do not establish holdout gain')


def threshold_passed(report, max_p95=None, max_non_candidate_fraction=0.0):
    """Threshold every scored reach, while retaining all attempts in coverage."""
    if not 0 <= max_non_candidate_fraction <= 1:
        raise ValueError('Non-candidate fraction must be between zero and one')
    if max_p95 is not None and (not math.isfinite(max_p95) or max_p95 < 0):
        raise ValueError('p95 threshold must be finite and nonnegative')
    if not report['counts']['total'] or 1 - report['candidate_coverage'] > max_non_candidate_fraction:
        return False
    scored = [row['distances']['symmetric']['p95_upper_bound']
              for row in report['reaches'] if 'distances' in row]
    return (bool(scored) and all(math.isfinite(value) and value >= 0 for value in scored)
            and (max_p95 is None or max(scored) <= max_p95))
