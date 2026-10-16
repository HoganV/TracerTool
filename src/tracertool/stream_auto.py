"""Experimental native-resolution drainage-aware reach proposals.

Flat-resolved D8 and disclosed bounded noise-scale conditioning are evidence.
Global least-cost geometry is refused if it exits a retained depression.
This is not a hydrologically validated delineator.
"""
from __future__ import annotations
import heapq
import math
import numpy as np
from scipy import ndimage
from .analysis_grid import (MAX_CELLS, WHOLE_SOURCE_CELLS, read_grid, check_cancel, check_source_identity,
                            condition_small_pits)
from .tracing import (TraceParams, TraceResult, _segment_valid, _arc_data,
                      _at_stations, _distance_to_segment)

NEIGHBORS = ((-1, 0), (0, -1), (0, 1), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1))


def _slices(shape, dr, dc):
    h, w = shape
    return ((slice(max(0, -dr), min(h, h-dr)), slice(max(0, -dc), min(w, w-dc))),
            (slice(max(0, dr), min(h, h+dr)), slice(max(0, dc), min(w, w+dc))))


def drainage(grid, cancel=None):
    """D8 with outlet-seeded equal-height BFS; closed flats remain unresolved.

    No epsilon slope or elevation changes. Each flat receiver points to an
    earlier BFS layer, so accumulation uses graph topology rather than unstable
    elevation sorting of ties. Diagonals obey the native corner mask.
    """
    z, valid = grid.data, grid.valid
    h, w = z.shape
    receiver = np.full(z.shape, -1, dtype=np.int32)
    slope = np.zeros(z.shape, dtype=float)
    equal = np.zeros(z.shape, dtype=bool)
    indices = np.arange(z.size, dtype=np.int32).reshape(z.shape)
    sx, sy = grid.resolution_xy
    for dr, dc in NEIGHBORS:
        check_cancel(cancel)
        a, b = _slices(z.shape, dr, dc)
        allowed = valid[a] & valid[b]
        if dr and dc:
            allowed &= valid[a[0], b[1]] & valid[b[0], a[1]]
        drop = np.where(allowed, (z[a]-z[b]) / math.hypot(dr*sy, dc*sx), -np.inf)
        better = drop > slope[a]
        receiver[a][better] = indices[b][better]
        slope[a][better] = drop[better]
        equal[a] |= allowed & (z[a] == z[b])
    from collections import deque
    recv = receiver.ravel()
    queue = deque(int(i) for i in np.flatnonzero((receiver >= 0) & equal))
    flat_resolved = np.zeros(z.shape, dtype=bool)
    count = 0
    while queue:
        index = queue.popleft()
        count += 1
        if count % 4096 == 0:
            check_cancel(cancel)
        r, c = divmod(index, w)
        for dr, dc in NEIGHBORS:
            nr, nc = r+dr, c+dc
            if not (0 <= nr < h and 0 <= nc < w and valid[nr, nc]):
                continue
            if dr and dc and not (valid[nr, c] and valid[r, nc]):
                continue
            if receiver[nr, nc] < 0 and z[nr, nc] == z[r, c]:
                receiver[nr, nc] = index
                flat_resolved[nr, nc] = True
                queue.append(nr*w+nc)
    accumulation = valid.astype(np.float64)
    accum = accumulation.ravel()
    incoming = np.bincount(recv[recv >= 0], minlength=z.size)
    queue = deque(int(i) for i in np.flatnonzero(valid.ravel() & (incoming == 0)))
    count = 0
    while queue:
        index = queue.popleft()
        count += 1
        if count % 4096 == 0:
            check_cancel(cancel)
        target = recv[index]
        if target >= 0:
            accum[target] += accum[index]
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(int(target))
    terminal = valid & (receiver < 0)
    flat = terminal & equal
    # Missing neighbors cannot establish a closed depression: both domain edges
    # and native NoData holes leave the possible downstream continuation unknown.
    boundary = valid & ~ndimage.binary_erosion(valid, structure=np.ones((3, 3)))
    sink = terminal & ~equal & ~boundary
    flat_labels, _ = ndimage.label(flat, structure=np.ones((3, 3)))
    open_labels = np.unique(flat_labels[boundary])
    closed_flat = flat & ~np.isin(flat_labels, open_labels)
    sink |= closed_flat
    return {'receiver': receiver, 'accumulation': accumulation, 'flat': flat,
            'flat_resolved': flat_resolved,
            'sink': sink, 'slope': slope, 'boundary': boundary}


def channel_evidence(grid, cancel=None):
    """Multiscale directional valley response in physical horizontal distances.

    Opposing-bank relief with cross-profile slope centering distinguishes a
    trough from an inclined plane. Eight profile directions do not use a guide
    chord. Invalid samples contribute no evidence, including across holes.
    """
    z = grid.data
    valid = grid.valid
    sx, sy = grid.resolution_xy
    base = math.sqrt(sx*sy)
    evidence = np.zeros(z.shape, dtype=np.float64)
    rr, cc = np.indices(z.shape, dtype=np.float64)
    safe_z = np.where(valid, z, 0.)
    reliefs = []
    for scale in (2., 5., 12.):
        check_cancel(cancel)
        radius = base * scale
        response = np.zeros(z.shape, dtype=np.float64)
        for angle in np.arange(8) * np.pi / 8:
            dr, dc = math.sin(angle)*radius/sy, math.cos(angle)*radius/sx
            plus = (rr+dr, cc+dc)
            minus = (rr-dr, cc-dc)
            p = ndimage.map_coordinates(safe_z, plus, order=1, mode='nearest')
            m = ndimage.map_coordinates(safe_z, minus, order=1, mode='nearest')
            # Eroding by the full profile rectangle is conservative around holes.
            support = ndimage.minimum_filter(valid, size=(2*math.ceil(abs(dr))+1,
                                                          2*math.ceil(abs(dc))+1), mode='constant', cval=0)
            relief = np.maximum(0., np.minimum(p-z, m-z))
            centered = np.exp(-np.abs(p-m) / np.maximum((p+m-2*z), 1e-12))
            response = np.maximum(response, np.where(support, relief*centered, 0.))
        positive = response[valid & (response > 0)]
        norm = float(np.percentile(positive, 70)) if len(positive) else 0.
        reliefs.append(norm)
        if norm > 1e-12:
            evidence = np.maximum(evidence, np.clip(response/(norm*.8), 0, 1))
    evidence[~valid] = 0.
    return evidence, reliefs


def _solve(grid, cost, hydrology, starts, targets, cancel=None):
    """Multi-source Dijkstra; hard mask and diagonal corner exclusion."""
    h, w = cost.shape
    distance = np.full(h*w, np.inf)
    previous = np.full(h*w, -1, dtype=np.int32)
    origin = np.full(h*w, -1, dtype=np.int16)
    queue = []
    for label, (point, initial) in enumerate(starts):
        index = point[0]*w+point[1]
        if initial < distance[index]:
            distance[index], origin[index] = initial, label
            heapq.heappush(queue, (float(initial), int(index)))
    remaining = {r*w+c for r, c in targets}
    sx, sy = grid.resolution_xy
    base = math.sqrt(sx*sy)
    z = grid.data.ravel()
    valid = grid.valid
    costs = cost.ravel()
    receivers = hydrology['receiver'].ravel()
    relief = max(float(np.nanpercentile(grid.data, 90)-np.nanpercentile(grid.data, 10))*.01, 1e-10)
    iterations = 0
    while queue and remaining:
        total, index = heapq.heappop(queue)
        if total > distance[index]:
            continue
        remaining.discard(index)
        iterations += 1
        if iterations % 1024 == 0:
            check_cancel(cancel)
        r, c = divmod(index, w)
        for dr, dc in NEIGHBORS:
            nr, nc = r+dr, c+dc
            if not (0 <= nr < h and 0 <= nc < w and valid[nr, nc]):
                continue
            if dr and dc and not (valid[nr, c] and valid[r, nc]):
                continue
            neighbor = nr*w+nc
            length = math.hypot(dr*sy, dc*sx)/base
            # Finite uphill costs permit exploration, not acceptance through
            # retained basins. Costs use derived analysis Z; exported elevations
            # always use the original calibrated source.
            uphill = min(20., max(0., (z[neighbor]-z[index])/relief))
            align = .55 if receivers[index] == neighbor else 1.
            edge = length * ((costs[index]+costs[neighbor])*.5*align + 2*uphill)
            proposed = total+edge
            if proposed < distance[neighbor]:
                distance[neighbor] = proposed
                previous[neighbor], origin[neighbor] = index, origin[index]
                heapq.heappush(queue, (float(proposed), neighbor))
    check_cancel(cancel)
    return distance, previous, origin


class SinkUnresolved(ValueError):
    """Refusal with located raw/derived pit evidence for callers to inspect."""

    def __init__(self, message, diagnostics, conditioning_summary):
        super().__init__(message)
        self.diagnostics = diagnostics
        self.conditioning_summary = conditioning_summary


class _DomainUnresolved(ValueError):
    """A larger native domain may resolve connectivity/evidence."""


def _resample_native(points, grid, spacing, tolerance, cancel=None):
    """Redistribute physical arc length, retaining bends and native mask safety."""
    sx, sy = grid.resolution_xy
    scale = np.asarray([sy, sx])
    physical, stations = _arc_data(np.asarray(points)*scale)
    if len(physical) < 2:
        return (physical/scale).tolist()
    targets = np.linspace(0, stations[-1], max(1, math.ceil(stations[-1]/spacing))+1)
    vertices = _at_stations(physical, stations, targets)
    output = [(vertices[0]/scale).tolist()]
    for i in range(len(vertices)-1):
        check_cancel(cancel)
        pending = [(vertices[i], vertices[i+1], targets[i], targets[i+1])]
        while pending:
            a, b, start, stop = pending.pop()
            inside = (stations > start+1e-9) & (stations < stop-1e-9)
            candidates = physical[inside]
            safe = _segment_valid(grid.valid, a/scale, b/scale)
            if len(candidates):
                errors = _distance_to_segment(candidates[:, 0], candidates[:, 1], a, b)
                index = int(np.argmax(errors))
                if not safe or errors[index] > tolerance:
                    middle, station = candidates[index], stations[inside][index]
                    pending.extend(((middle, b, station, stop), (a, middle, start, station)))
                    continue
            if not safe:
                raise ValueError('A proposed native segment crosses NoData; adjust the guides.')
            output.append((b/scale).tolist())
    return output


def trace_auto(terrain, anchors, params=None, cancel=None, fixed_anchor_indices=None):
    """Search an expanding reach rectangle at native resolution within a hard cap.

    Partial-domain accumulation is explicitly uncertain. A route touching an
    artificial boundary triggers expansion, never acceptance as a complete reach.
    """
    check_cancel(cancel)
    h = int(terrain.metadata['original_height'])
    w = int(terrain.metadata['original_width'])
    if h*w <= WHOLE_SOURCE_CELLS:
        return _trace_domain(terrain, anchors, params, cancel, fixed_anchor_indices)
    if len(anchors) < 2:
        raise ValueError('Add at least two guides for Auto stream tracing.')
    native = []
    t = terrain._source_transform
    for point in anchors:
        if len(point) != 2 or not all(math.isfinite(float(v)) for v in point):
            raise ValueError('Each guide must contain a finite row and column.')
        x, y = terrain.xy(*point)
        native.append(((y-t.f)/t.e-.5, (x-t.c)/t.a-.5))
    native = np.asarray(native)
    lo = np.floor(native.min(axis=0)).astype(int)
    hi = np.ceil(native.max(axis=0)).astype(int)+1
    margin = max(48, int(np.max(hi-lo)*.5))
    # A generous initial halo is not a memory requirement. Fit the first
    # native window before analysis; subsequent boundary-driven expansion must
    # still fail rather than silently shrink the required context.
    while margin > 48:
        extent = np.minimum(hi+margin, [h, w])-np.maximum(lo-margin, 0)
        if int(extent[0])*int(extent[1]) <= MAX_CELLS:
            break
        margin = max(48, margin//2)
    while True:
        bounds = (max(0, int(lo[0])-margin), min(h, int(hi[0])+margin),
                  max(0, int(lo[1])-margin), min(w, int(hi[1])+margin))
        if (bounds[1]-bounds[0])*(bounds[3]-bounds[2]) > MAX_CELLS:
            raise ValueError('Native Auto reach exceeds the memory budget; crop the source DEM or split this reach.')
        try:
            result = _trace_domain(terrain, anchors, params, cancel, fixed_anchor_indices, bounds)
        except _DomainUnresolved:
            if bounds == (0, h, 0, w):
                # More margin cannot reveal evidence/connectivity outside the
                # complete source. Preserve the actionable original refusal.
                raise
            margin *= 2
            continue
        route = np.array([[(p[1]-t.f)/t.e-.5, (p[0]-t.c)/t.a-.5] for p in result.coordinates])
        artificial = ((bounds[0] > 0 and route[:, 0].min() < bounds[0]+16) or
                      (bounds[1] < h and route[:, 0].max() > bounds[1]-17) or
                      (bounds[2] > 0 and route[:, 1].min() < bounds[2]+16) or
                      (bounds[3] < w and route[:, 1].max() > bounds[3]-17))
        if not artificial:
            return result
        margin *= 2


def _trace_domain(terrain, anchors, params=None, cancel=None, fixed_anchor_indices=None, bounds=None):
    """Return an experimental source-native candidate; never call legacy trace."""
    check_cancel(cancel)
    if not terrain.crs or not terrain.crs.is_projected:
        raise ValueError('Auto tracing requires a projected DEM with linear map units.')
    params = params or TraceParams()
    if not math.isfinite(params.spacing) or not .25 <= params.spacing <= 2000:
        raise ValueError('Output spacing must be finite and between 0.25 and 2,000 working cells.')
    if not math.isfinite(params.simplify) or not 0 <= params.simplify <= 200:
        raise ValueError('Output simplification must be finite and between 0 and 200 working cells.')
    if len(anchors) < 2:
        raise ValueError('Add at least two guides for Auto stream tracing.')
    fixed = set(fixed_anchor_indices or [])
    if any(isinstance(i, bool) or not isinstance(i, (int, np.integer)) or not 0 <= i < len(anchors) for i in fixed):
        raise ValueError('Fixed anchor indices must be existing zero-based guide indices.')
    xy = []
    for point in anchors:
        if len(point) != 2 or not all(math.isfinite(float(v)) for v in point):
            raise ValueError('Each guide must contain a finite row and column.')
        if not (-.5 < point[0] < terrain.height-.5 and -.5 < point[1] < terrain.width-.5):
            raise ValueError('A guide is outside the DEM.')
        xy.append(list(terrain.xy(*point)))
    grid = read_grid(terrain, bounds, cancel=cancel)
    truncated = grid.bounds != (0, grid.source_shape[0], 0, grid.source_shape[1])
    points = [tuple(int(math.floor(v+.5)) for v in grid.rc(*p)) for p in xy]
    if any(not grid.valid[p] for p in points):
        raise ValueError('A guide touches native source NoData; move it onto valid terrain.')
    if any(a == b for a, b in zip(points[:-1], points[1:])):
        raise ValueError('Place adjacent guides in different native source cells; '
                         'Auto cannot resolve distinct protected locations within one cell.')
    connected, _ = ndimage.label(grid.valid, structure=ndimage.generate_binary_structure(2, 1))
    if len({int(connected[p]) for p in points}) != 1:
        raise _DomainUnresolved('Unresolved: no connected native route; NoData is impassable. Adjust guides or crop a larger valid reach.')
    del connected
    evidence, _ = channel_evidence(grid, cancel)
    if evidence.max() <= 0:
        raise _DomainUnresolved('Unresolved: flat or no directional channel evidence. Add independently reviewed guides or use Manual tracing.')
    grid, conditioning = condition_small_pits(grid, cancel)
    pit_labels = conditioning.pop('_pit_labels')
    hydro = drainage(grid, cancel)
    accumulation = np.log1p(hydro['accumulation'])
    accumulation /= max(float(accumulation.max()), 1.)
    cost = 1.+24.*(1.-evidence)**2+4.*(1.-accumulation)
    if len(points) > 32:
        raise ValueError('Auto supports up to 32 guides per reach; split the reach into smaller sections.')
    sx, sy = grid.resolution_xy
    base = math.sqrt(sx*sy)
    protected = fixed | {0, len(points)-1}
    candidates, penalties = [], []
    for i, point in enumerate(points):
        check_cancel(cancel)
        if i in protected:
            candidates.append([point])
            penalties.append([0.])
            continue
        # Small discrete guide-state sets, jointly optimized over the entire
        # reach. These are not independently snapped nearest minima.
        span = min(math.hypot((point[0]-points[j][0])*sy, (point[1]-points[j][1])*sx)
                   for j in (i-1, i+1))
        radius = min(32*base, max(4*base, span*.22))
        rr, cc = np.mgrid[max(0, point[0]-math.ceil(radius/sy)):min(grid.data.shape[0], point[0]+math.ceil(radius/sy)+1),
                         max(0, point[1]-math.ceil(radius/sx)):min(grid.data.shape[1], point[1]+math.ceil(radius/sx)+1)]
        displacement = np.hypot((rr-point[0])*sy, (cc-point[1])*sx)
        eligible = grid.valid[rr, cc] & (displacement <= radius)
        score = cost[rr, cc]+4.*(displacement/radius)**2
        choices = np.flatnonzero(eligible)
        choices = choices[np.argsort(score.ravel()[choices], kind='stable')[:32]]
        selected = [(int(rr.ravel()[j]), int(cc.ravel()[j])) for j in choices]
        if point not in selected:
            selected.append(point)
        candidates.append(selected)
        penalties.append([4.*math.hypot((p[0]-point[0])*sy, (p[1]-point[1])*sx)**2/radius**2 for p in selected])
    records = []
    scores = np.asarray([0.])
    w = grid.data.shape[1]
    for stage in range(1, len(points)):
        starts = [(p, float(score)) for p, score in zip(candidates[stage-1], scores)]
        distance, previous, origin = _solve(grid, cost, hydro, starts, candidates[stage], cancel)
        ends = [r*w+c for r, c in candidates[stage]]
        scores = distance[ends]+penalties[stage]
        records.append((previous, origin[ends].copy()))
        if not np.isfinite(scores).any():
            raise _DomainUnresolved('Unresolved: no connected native route; NoData is impassable. Crop a larger valid reach or adjust guides.')
    chosen = int(np.argmin(scores))
    parts = []
    for stage in range(len(points)-1, 0, -1):
        previous, labels = records[stage-1]
        end = candidates[stage][chosen]
        indices = [end[0]*w+end[1]]
        while previous[indices[-1]] >= 0:
            if len(indices) % 4096 == 0:
                check_cancel(cancel)
            indices.append(int(previous[indices[-1]]))
        part = [list(divmod(j, w)) for j in indices[::-1]]
        if stage in protected:
            part[-1] = list(grid.rc(*xy[stage]))
        chosen = int(labels[chosen])
        if stage-1 in protected:
            part[0] = list(grid.rc(*xy[stage-1]))
        parts.append(part)
    parts.reverse()
    path, output = [], []
    spacing = params.spacing*terrain.resolution
    tolerance = min(params.simplify*terrain.resolution, .75*min(sx, sy))
    for part in parts:
        path.extend(part if not path else part[1:])
        if not all(_segment_valid(grid.valid, a, b) for a, b in zip(part[:-1], part[1:])):
            raise ValueError('A protected exact guide creates a native NoData crossing; move the guide.')
        sampled = _resample_native(part, grid, spacing, tolerance, cancel)
        output.extend(sampled if not output else sampled[1:])
    coords = [[*grid.xy(r, c), 0.] for r, c in output]
    elevations = terrain.sample_many([p[:2] for p in coords])
    if any(z is None for z in elevations):
        raise ValueError('Native source NoData touches the proposed geometry; no result was accepted.')
    for p, z in zip(coords, elevations):
        p[2] = z
    for a, b in zip(output[:-1], output[1:]):
        check_cancel(cancel)
        if not _segment_valid(grid.valid, a, b):
            raise ValueError('A proposed native segment crosses NoData; no result was accepted.')
    dz = np.diff(elevations)
    lengths = np.linalg.norm(np.diff(np.asarray(coords)[:, :2], axis=0), axis=1)
    route_indices = tuple(np.rint(np.asarray(path)).astype(int).T)
    route_pit_ids = set(int(i) for i in pit_labels[route_indices] if i)
    route_pits = [p for p in conditioning['pits'] if p['id'] in route_pit_ids]
    retained = [p for p in route_pits if p['decision'] == 'retained_depression']
    route_labels = pit_labels[route_indices]
    exited = set(int(i) for i in route_labels[:-1][route_labels[:-1] != route_labels[1:]])
    if hydro['sink'][route_indices][:-1].any() or any(p['id'] in exited for p in retained):
        details = '; '.join(f"depth={p['max_depth_source_units']:.6g} source-Z, cells={p['cells']}"
                            for p in retained[:8])
        raise SinkUnresolved(
            'Unresolved: the proposed route exits or continues through a retained native sink; '
            'material fill/breach requires independent review and explicit consent. ' + details,
            route_pits, {k: v for k, v in conditioning.items() if k != 'pits'})
    support = float(evidence[route_indices].mean())
    if support < .15:
        raise _DomainUnresolved('Unresolved: insufficient directional channel evidence along this reach; use Manual tracing or better guides.')
    alternative_ratio = None
    if len(points) == 2 and len(path) > 20:
        # A separated alternative is a relative ambiguity test, not a calibrated
        # confidence interval. Penalize only the central third of this route;
        # headwater/junction endpoints remain available to both alternatives.
        blocked = np.zeros(grid.data.shape, dtype=bool)
        middle = np.rint(np.asarray(path[len(path)//3:2*len(path)//3])).astype(int)
        blocked[tuple(middle.T)] = True
        separation = ndimage.distance_transform_edt(~blocked, sampling=(sy/base, sx/base))
        alternative_cost = cost.copy()
        alternative_cost[separation < 6.] += 50.
        dist2, _, _ = _solve(grid, alternative_cost, hydro, [(points[0], 0.)], [points[-1]], cancel)
        alternative = dist2[points[-1][0]*w+points[-1][1]]
        original = float(scores[0])
        if np.isfinite(alternative):
            alternative_ratio = float(alternative/max(original, 1e-12))
    diagnostics: list[dict] = [{'code': 'experimental', 'message': 'Experimental relative evidence; not hydrologically validated.'},
                   {'code': 'source_identity', 'message': 'Native band-1 calibrated source; display grid not used.'},
                   {'code': 'conditioning', 'message': 'Outlet-connected flats resolved without changing Z; only bounded noise-scale pits treated on a derived analysis surface. No breaching or vertical conversion. Source Z is unchanged.'}]
    ambiguous = truncated
    for pit in route_pits:
        if pit['decision'] == 'bounded_noise_scale_fill':
            ambiguous = True
            diagnostics.append({'code': 'pit_conditioned',
                                'message': 'Small noise-scale depression filled for analysis only; artifact status is uncertain, inspect original profile.',
                                **pit})
    if alternative_ratio is not None and alternative_ratio <= 1.25:
        ambiguous = True
        diagnostics.append({'code': 'alternative_route', 'message': 'A separated native route has similar cost; branch choice is ambiguous.'})
    if truncated:
        diagnostics.append({'code': 'domain_truncated', 'message': 'Adaptive native reach window excludes the rest of the source; contributing area and alternatives outside this domain are unknown.'})
    if hydro['sink'][route_indices].any():
        ambiguous = True
        diagnostics.append({'code': 'sink', 'message': 'Route ends at a native local sink; downstream continuation is unresolved.',
                            'location': coords[-1][:2]})
    if hydro['boundary'][route_indices].any():
        ambiguous = True
        index = int(np.flatnonzero(hydro['boundary'][route_indices])[0])
        diagnostics.append({'code': 'data_boundary', 'message': 'Route touches a source or NoData boundary; drainage beyond valid data is unknown.',
                            'location': list(grid.xy(*path[index]))})
    if hydro['flat'][route_indices].any():
        ambiguous = True
        diagnostics.append({'code': 'flat', 'message': 'Flat drainage direction is unresolved; geometry uses surrounding channel evidence.'})
    if np.maximum(dz, 0).sum() > 1e-8:
        ambiguous = True
        diagnostics.append({'code': 'uphill', 'message': 'Candidate includes uphill source segments; inspect pits, structures and guide order.'})
    metrics = {'engine': 'stream_auto', 'engine_version': 1,
               'status': 'ambiguous' if ambiguous else 'candidate',
               'analysis_resolution': base, 'analysis_resolution_xy': [sx, sy],
               'effective_config': {'conditioning': 'bounded_noise_scale_pits' if conditioning['changed_cells'] else 'none',
                                    'conditioning_summary': {k: v for k, v in conditioning.items() if k != 'pits'},
                                    'flat_routing': 'outlet_seeded_equal_height_bfs', 'grid': 'native',
                                    'domain_bounds': list(grid.bounds), 'domain_truncated': truncated,
                                    'max_cells': MAX_CELLS,
                                    'estimated_peak_analysis_bytes': int(grid.data.size*(512+4*len(points))),
                                    'channel_scales_cells': [2., 5., 12.],
                                    'direction_count': 8, 'guide_solver': 'joint_layered_dijkstra',
                                    'source_identity': grid.source_identity,
                                    'vertical_to_horizontal': grid.vertical_to_horizontal,
                                    'output_spacing_map_units': params.spacing*terrain.resolution,
                                    'output_simplification_map_units': tolerance},
               'diagnostics': diagnostics, 'length': float(lengths.sum()), 'units': terrain.units,
               'vertices': len(coords), 'kind': 'stream', 'elevation_min': float(min(elevations)),
               'elevation_max': float(max(elevations)), 'elevation_start': float(elevations[0]),
               'elevation_end': float(elevations[-1]), 'elevation_gain': float(np.maximum(dz, 0).sum()),
               'elevation_loss': float(-np.minimum(dz, 0).sum()),
               'vertical_units': terrain.metadata.get('vertical_units', 'unspecified'),
               'spacing_min': float(lengths.min()), 'spacing_median': float(np.median(lengths)),
               'spacing_max': float(lengths.max()), 'relative_support': support,
               'alternative_cost_ratio': alternative_ratio}
    check_cancel(cancel)
    check_source_identity(grid.source_identity)
    return TraceResult(coords, [list(terrain.rc(*p[:2])) for p in coords], metrics,
                       [d['message'] for d in diagnostics], xy, sorted(fixed))
