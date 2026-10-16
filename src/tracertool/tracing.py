"""Interactive, anchor-guided landform tracing on a DEM working grid.

This is a cartographic assistant, not a hydrologic delineation model or a
survey breakline classifier. A local terrain-position/curvature cost helps a
user's anchors follow ridges, lows, or slope changes inside an explicit
corridor. It does not resolve culverts, bridges, drainage connectivity, or
vertical datums. The optional downhill walk deliberately stops at pits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np
from scipy import ndimage
from skimage.graph import MCP_Geometric

from .terrain import Terrain


@dataclass
class TraceParams:
    corridor: float = 12.
    smoothing: float = 0.
    terrain_weight: float = 8.
    spacing: float = 3.
    simplify: float = .75
    line_smoothing: float = 0.
    relax_anchors: bool = True


def default_params(terrain: Terrain, kind: str = 'stream') -> TraceParams:
    """Conservative new-draft settings expressed in *working cells*.

    The UI converts these distances with ``terrain.resolution``: a 10-metre
    grid gets a 120-metre search radius and 30-metre target spacing, whereas a
    1-metre grid gets 12 and 3 metres. Neither conversion implies accuracy.
    Attraction is dimensionless; smoothing is an explicit opt-in.
    """
    if kind not in {'ridge', 'stream', 'slope_break', 'manual', 'downstream'}:
        raise ValueError('Choose ridge, stream, slope_break, manual, or downstream tracing.')
    if not math.isfinite(terrain.resolution) or terrain.resolution <= 0:
        raise ValueError('The working grid must have a finite positive cell size.')
    return TraceParams()


@dataclass
class TraceResult:
    coordinates: list[list[float]]
    cells: list[list[float]]
    metrics: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    anchors: list[list[float]] = field(default_factory=list)
    fixed_anchor_indices: list[int] = field(default_factory=list)


class TraceCancelled(RuntimeError):
    """Raised when a caller cancels work at the next computation boundary."""


def _check_cancel(cancel):
    if cancel is not None and cancel():
        raise TraceCancelled('Tracing cancelled; no line was changed.')


def _validate(terrain, params):
    if not terrain.crs or not terrain.crs.is_projected:
        raise ValueError("Tracing requires a projected DEM with linear map units. Reproject the raster before tracing.")
    for name in ('corridor', 'smoothing', 'terrain_weight', 'spacing', 'simplify', 'line_smoothing'):
        value = getattr(params, name)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name.replace('_', ' ').title()} must be a finite number.")
    if params.corridor < 1:
        raise ValueError("Corridor must be at least 1 working pixel.")
    if not 0 <= params.smoothing <= 50:
        raise ValueError("Smoothing must be between 0 and 50 working pixels.")
    if not 0 <= params.terrain_weight <= 1000:
        raise ValueError("Terrain weight must be between 0 and 1,000.")
    if not .25 <= params.spacing <= 2000:
        raise ValueError("Vertex spacing must be between 0.25 and 2,000 working pixels.")
    if not 0 <= params.line_smoothing <= 50:
        raise ValueError("Line smoothing must be between 0 and 50 working pixels.")
    if not 0 <= params.simplify <= 200:
        raise ValueError("Simplification must be between 0 and 200 working pixels.")
    if not isinstance(params.relax_anchors, bool):
        raise ValueError('Relax anchors must be true or false.')


def _anchor(terrain, point):
    if len(point) != 2 or not all(math.isfinite(float(v)) for v in point):
        raise ValueError("Each anchor must contain a finite row and column.")
    # Clicks select containing pixels; assisted guides begin at cell centers.
    row, col = (math.floor(float(v) + .5) for v in point)
    if not (0 <= row < terrain.height and 0 <= col < terrain.width):
        raise ValueError("An anchor is outside the terrain. Click inside the raster.")
    if not terrain.valid[row, col]:
        raise ValueError("An anchor is on NoData. Move it onto valid terrain.")
    return row, col


def _distance_to_segment(rr, cc, a, b):
    dr, dc = b[0] - a[0], b[1] - a[1]
    length2 = dr * dr + dc * dc
    if length2 == 0:
        return np.hypot(rr - a[0], cc - a[1])
    t = np.clip(((rr - a[0]) * dr + (cc - a[1]) * dc) / length2, 0, 1)
    return np.hypot(rr - a[0] - t * dr, cc - a[1] - t * dc)


def _normalized_signed(a, valid):
    vals = np.abs(a[valid])
    scale = float(np.percentile(vals, 90)) if len(vals) else 0.
    if scale < 1e-10:
        return np.zeros_like(a, dtype=np.float32)
    return np.tanh(a / scale).astype(np.float32)


def _cost(terrain, bounds, kind, params, direction, cancel=None, guidance_mask=None):
    _check_cancel(cancel)
    r0, r1, c0, c1 = bounds
    # Read a halo so the working window does not create artificial landforms.
    # Feature detection and output sampling are independent of search radius.
    # The broader stream descriptor recognizes opposing banks of flat floors;
    # widening the search corridor must not blur away narrow terrain features.
    broad_sigma = max(12. if kind == 'stream' else 6., params.smoothing * 4)
    halo = max(6, math.ceil(broad_sigma * 4))
    hr0, hr1 = max(0, r0 - halo), min(terrain.height, r1 + halo)
    hc0, hc1 = max(0, c0 - halo), min(terrain.width, c1 + halo)
    z = terrain.surface()[hr0:hr1, hc0:hc1]
    _check_cancel(cancel)
    smooth = ndimage.gaussian_filter(z, params.smoothing) if params.smoothing else z
    _check_cancel(cancel)
    broad = ndimage.gaussian_filter(smooth, broad_sigma)
    _check_cancel(cancel)
    crop = (slice(r0 - hr0, r1 - hr0), slice(c0 - hc0, c1 - hc0))
    local = (smooth - broad)[crop]
    valid = terrain.valid[r0:r1, c0:c1]
    if guidance_mask is not None:
        valid = valid & guidance_mask
    # A scale-normalized local position gives both flat and steep DEMs useful
    # defaults. Curvature adds narrow feature sensitivity beyond broad relief.
    curvature = ndimage.laplace(smooth)[crop]
    tpi = _normalized_signed(local, valid)
    curv = _normalized_signed(curvature, valid)
    if kind in {'ridge', 'stream'}:
        # TPI and curvature are constant across an ideal parabolic channel.
        # Cross-profile slope supplies the missing centerline signal. The
        # anchor chord defines the approximate feature direction; additional
        # anchors handle tight bends. Signed relief separates crest from trough.
        # On a wide flat channel, tiny DEM texture and shoreline concavity
        # must not replace the broad opposing-bank signal. Derive stream
        # centering from an independent relief scale; ridge tops use a finer
        # relief scale so narrow crests remain resolved.
        gy, gx = np.gradient(broad)
        dr, dc = direction
        length = max(math.hypot(dr, dc), 1e-12)
        cross_slope = np.abs((-dc * gy + dr * gx) / length)[crop]
        cross_scale = float(np.percentile(cross_slope[valid], 95)) if valid.any() else 0.
        center = np.exp(-np.square(cross_slope / max(cross_scale * .35, 1e-10)))
        signed = .7 * tpi - .3 * curv
        landform = .5 + .5 * (signed if kind == 'ridge' else -signed)
        # Flat ground is not a crest merely because cross slope is zero.
        # Gate centering by signed feature relief; otherwise an adjacent flat
        # field can beat a noisy levee top. Normalize inside the guide corridor
        # so a narrow diagonal feature is not overwhelmed by the bounding box.
        suitability = landform * (.25 + .75 * center)
    else:
        gy, gx = np.gradient(smooth)
        slope = np.hypot(gx, gy)
        sgy, sgx = np.gradient(slope)
        change = np.hypot(sgx, sgy)[crop]
        scale = float(np.percentile(change[valid], 95)) if valid.any() else 0.
        suitability = np.clip(change / max(scale, 1e-10), 0, 1)
    return 1. + params.terrain_weight * (1. - np.clip(suitability, 0, 1))


def _segment_cells(a, b):
    """Exact supercover of a segment in center-index coordinates.

    Intersections with pixel boundaries are evaluated on both sides. A
    diagonal that only touches a NoData corner is conservatively rejected.
    """
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    delta = b - a
    times = [0., 1.]
    for axis in (0, 1):
        if abs(delta[axis]) < 1e-12:
            continue
        lo, hi = sorted((a[axis], b[axis]))
        borders = np.arange(math.ceil(lo - .5), math.floor(hi - .5) + 1, dtype=float) + .5
        ts = (borders - a[axis]) / delta[axis]
        times.extend(ts[(ts > 0) & (ts < 1)].tolist())
    times = np.unique(times)
    mids = (times[:-1] + times[1:]) / 2
    positions = a + np.r_[times, mids][:, None] * delta
    # ±epsilon includes both sides of exact edges/corners, nothing else.
    out = set()
    for er in (-1e-9, 1e-9):
        for ec in (-1e-9, 1e-9):
            cells = np.floor(positions + [.5 + er, .5 + ec]).astype(int)
            out.update(map(tuple, cells.tolist()))
    return out


def _segment_valid(mask, a, b):
    h, w = mask.shape
    return all(0 <= r < h and 0 <= c < w and mask[r, c] for r, c in _segment_cells(a, b))


def validate_segments(terrain: Terrain, coordinates) -> None:
    """Validate native-CRS XY/XYZ edited geometry; raise on unsafe segments.

    Every crossed working cell, including exact corner touches, must be valid.
    The working mask conservatively includes source NoData when downsampled.
    Optional Z is checked for finiteness, but callers must refresh edited Z via
    Terrain.sample/sample_many before saving; this function never changes it.
    """
    coordinates = list(coordinates)
    if len(coordinates) < 2:
        raise ValueError("A line needs at least two vertices.")
    pixels = []
    native_xy = []
    for point in coordinates:
        if len(point) not in (2, 3):
            raise ValueError("Each line vertex must contain XY or XYZ coordinates.")
        try:
            values = [float(v) for v in point]
        except (TypeError, ValueError) as exc:
            raise ValueError("Line coordinates must be finite numbers.") from exc
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Line coordinates must be finite numbers.")
        row, col = terrain.rc(values[0], values[1])
        if not (-.5 < row < terrain.height - .5 and -.5 < col < terrain.width - .5):
            raise ValueError("A line vertex leaves the raster. Move it inside valid terrain.")
        pixels.append((row, col))
        native_xy.append((values[0], values[1]))
    for a, b in zip(pixels[:-1], pixels[1:]):
        if not _segment_valid(terrain.valid, a, b):
            raise ValueError("A line segment crosses NoData or leaves the raster. Move the vertex or add a vertex around the gap.")
    if any(z is None for z in terrain.sample_many(native_xy)):
        raise ValueError("A line vertex is on source NoData. Move it onto valid terrain.")


def _simplify(points, tolerance, mask):
    """Douglas–Peucker simplification, retaining barrier-safe segments."""
    points = np.asarray(points, dtype=float)
    if len(points) <= 2 or tolerance <= 0:
        return points.tolist()
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        sub = points[i + 1:j]
        distances = _distance_to_segment(sub[:, 0], sub[:, 1], points[i], points[j])
        k = i + 1 + int(np.argmax(distances))
        if float(np.max(distances)) <= tolerance and _segment_valid(mask, points[i], points[j]):
            continue
        keep.add(k)
        stack.extend(((i, k), (k, j)))
    return points[sorted(keep)].tolist()


def _arc_data(points):
    points = np.asarray(points, dtype=float)
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    keep = np.r_[True, lengths > 1e-10]
    points = points[keep]
    stations = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    return points, stations


def _at_stations(points, stations, targets):
    return np.column_stack([np.interp(targets, stations, points[:, axis]) for axis in (0, 1)])


def _resample(points, spacing, mask=None, tolerance=None):
    """Fresh, evenly redistributed arc-length stations across a complete path.

    Sampling no longer restarts at every input corner. Where a proposed chord
    crosses NoData or cuts a real bend beyond tolerance, retain the necessary
    reference bend. Such safety exceptions may have closer station spacing.
    Callers split at hard user anchors so every explicit fixed anchor remains exact.
    """
    points, stations = _arc_data(points)
    if len(points) < 2:
        return points.tolist()
    targets = np.linspace(0, stations[-1], max(1, math.ceil(stations[-1] / spacing)) + 1)
    vertices = _at_stations(points, stations, targets)
    if mask is None and tolerance is None:
        return vertices.tolist()
    output = [vertices[0].tolist()]
    # Adaptive insertion retains actual reference corners, never all raster
    # corners by default. Each interval has at most ceil(spacing) raw cells.
    for i in range(len(vertices) - 1):
        # An explicit stack also supports strict zero tolerance on long,
        # detailed paths without exhausting Python's recursion limit.
        pending = [(vertices[i], vertices[i + 1], targets[i], targets[i + 1])]
        while pending:
            a, b, start, stop = pending.pop()
            inside = (stations > start + 1e-9) & (stations < stop - 1e-9)
            candidates = points[inside]
            candidate_stations = stations[inside]
            safe = mask is None or _segment_valid(mask, a, b)
            if len(candidates):
                errors = _distance_to_segment(candidates[:, 0], candidates[:, 1], a, b)
                index = int(np.argmax(errors))
                shape_ok = tolerance is None or errors[index] <= tolerance
                if not safe or not shape_ok:
                    middle, station = candidates[index], candidate_stations[index]
                    pending.extend(((middle, b, station, stop), (a, middle, start, station)))
                    continue
            if not safe:
                raise ValueError('A smoothed line would cross NoData; reduce line smoothing or add a guide around the gap.')
            output.append(list(b))
    return output


def _smooth_vectors(path, mask, cost, radius, terrain_weight, cancel=None):
    """Refine raster routes into continuous feature-following vector geometry.

    First regularize shape by arc length, then use smooth cross-profile cost
    evidence to recenter within a bounded trust band of the original route.
    Endpoints are fixed. Proposed vertices that leave the feature's low-cost
    envelope or touch obstacles are backed off, with exact segment checks.
    """
    if radius <= 0 or len(path) < 3:
        return np.asarray(path, dtype=float).tolist()
    raw, stations = _arc_data(path)
    reference = np.asarray(_resample(raw, 1., mask=mask), dtype=float)
    step = stations[-1] / max(1, len(reference) - 1)
    sigma = radius / max(step, 1e-6)
    pad = max(2, math.ceil(4 * sigma))
    def smooth_shape(values):
        # Linear extension retains a straight oblique line exactly at its ends.
        before = values[0] + np.arange(-pad, 0)[:, None] * (values[1] - values[0])
        after = values[-1] + np.arange(1, pad + 1)[:, None] * (values[-1] - values[-2])
        extended = np.concatenate((before, values, after))
        filtered = ndimage.gaussian_filter1d(extended, sigma, axis=0, mode='nearest')[pad:-pad]
        filtered[0], filtered[-1] = reference[0], reference[-1]
        return filtered
    finite_cost = np.where(np.isfinite(cost), cost, 1e6)
    def sample(values):
        return ndimage.map_coordinates(finite_cost, values.T, order=1, mode='constant', cval=1e6)
    baseline_cost = sample(reference)
    allowance = max(.35, terrain_weight * .12)
    def constrained(candidate):
        displacement = candidate - reference
        distance = np.linalg.norm(displacement, axis=1)
        candidate = reference + displacement * np.minimum(1., radius / np.maximum(distance, 1e-12))[:, None]
        for _ in range(5):
            unacceptable = sample(candidate) > baseline_cost + allowance
            if not unacceptable.any():
                break
            candidate[unacceptable] = (candidate[unacceptable] + reference[unacceptable]) / 2
        unacceptable = sample(candidate) > baseline_cost + allowance
        candidate[unacceptable] = reference[unacceptable]
        candidate[0], candidate[-1] = reference[0], reference[-1]
        # Local rollback protects holes/corners without discarding smoothing
        # everywhere else on a long line. Original reference edges are safe.
        for _ in range(4):
            unsafe = [i for i, (a, b) in enumerate(zip(candidate[:-1], candidate[1:])) if not _segment_valid(mask, a, b)]
            if not unsafe:
                return candidate
            indices = np.unique(np.r_[unsafe, np.asarray(unsafe) + 1])
            candidate[indices] = reference[indices]
        return reference.copy()
    current = constrained(smooth_shape(reference))
    # Soft cross-profile minima are more stable than choosing one highest/lowest
    # pixel and give a plateau a centered, smoothly varying representative line.
    offsets = np.linspace(-min(radius, 4.), min(radius, 4.), 17)
    for _ in range(3):
        _check_cancel(cancel)
        tangent = np.gradient(current, axis=0)
        length = np.linalg.norm(tangent, axis=1)
        normals = np.column_stack((-tangent[:, 1], tangent[:, 0])) / np.maximum(length[:, None], 1e-12)
        probes = current[:, None, :] + normals[:, None, :] * offsets[None, :, None]
        costs = sample(probes.reshape(-1, 2)).reshape(len(current), -1)
        minimum = costs.min(axis=1, keepdims=True)
        weights = np.exp(-np.minimum((costs - minimum) / max(.15, terrain_weight * .035), 80))
        weights *= np.exp(-.5 * (offsets / max(radius, 1.)) ** 2)[None, :]
        shift = (weights * offsets).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-12)
        shift = ndimage.gaussian_filter1d(shift, sigma, mode='nearest')
        candidate = current + .6 * normals * shift[:, None]
        current = constrained(candidate)
    return current.tolist()


def _profile_support_cost(cost, mask, centers, tangent, offsets):
    """Mean longitudinal evidence connected to each candidate's center.

    A raster edge permits one-sided support. NoData stops support in that
    direction: neither samples across a gap nor diagonal corner crossings can
    contribute to the candidate's score.
    """
    centers = np.asarray(centers, dtype=float)
    probes = centers[:, None, :] + offsets[None, :, None] * tangent
    values = ndimage.map_coordinates(cost, probes.reshape(-1, 2).T,
                                    order=0, mode='constant', cval=np.inf).reshape(len(centers), -1)
    middle = len(offsets) // 2  # The odd, symmetric sampling includes offset zero.
    finite = np.isfinite(values)
    left = np.logical_and.accumulate(finite[:, :middle + 1][:, ::-1], axis=1)[:, ::-1]
    right = np.logical_and.accumulate(finite[:, middle:], axis=1)
    connected = np.concatenate((left, right[:, 1:]), axis=1)
    if not mask.all():
        # Finite probes alone can miss a diagonal touching an invalid corner.
        # Check the full support segment, shortening only the obstructed side.
        for index, center in enumerate(centers):
            if not connected[index, middle]:
                continue
            for step in (-1, 1):
                indices = np.arange(middle + step, len(offsets) if step > 0 else -1, step)
                indices = indices[connected[index, indices]]
                if not len(indices) or _segment_valid(mask, center, probes[index, indices[-1]]):
                    continue
                low, high = 0, len(indices)
                while low < high:
                    trial = (low + high + 1) // 2
                    if _segment_valid(mask, center, probes[index, indices[trial - 1]]):
                        low = trial
                    else:
                        high = trial - 1
                connected[index, indices[low:]] = False
    counts = connected.sum(axis=1)
    # Retain at least the former three-probe evidence requirement, while
    # allowing those probes to lie on the available side of an edge or gap.
    return np.divide(np.where(connected, values, 0.).sum(axis=1), counts,
                     out=np.full(len(centers), np.inf), where=counts >= 3)


def _relax_guides(terrain, points, kind, params, fixed, cancel=None):
    """Move rough guides across their local direction toward feature evidence.

    Search cross-sections retain the user's along-line coverage and point
    order. Every displacement must itself avoid NoData. Short neighboring
    segments and tight reversals limit movement so a broad corridor cannot
    collapse an intentional bend or swap neighboring guides.
    """
    output = list(points)
    if not params.relax_anchors or params.terrain_weight == 0:
        return output
    grid_radius = math.hypot(terrain.height, terrain.width)
    for index, point in enumerate(points):
        _check_cancel(cancel)
        if index in fixed:
            continue
        vectors = []
        if index:
            vectors.append(np.asarray(point, float) - points[index - 1])
        if index + 1 < len(points):
            vectors.append(np.asarray(points[index + 1], float) - point)
        lengths = [float(np.linalg.norm(v)) for v in vectors]
        units = [v / length for v, length in zip(vectors, lengths)]
        if len(units) == 2 and float(units[0] @ units[1]) < -.5:
            continue
        tangent = np.sum(units, axis=0)
        tangent /= np.linalg.norm(tangent)
        normal = np.array([-tangent[1], tangent[0]])
        radius = min(params.corridor, grid_radius, min(lengths) * .45)
        offsets = np.linspace(-radius, radius, max(2, math.ceil(radius * 2)) + 1)
        candidates = np.unique(np.rint(np.asarray(point) + offsets[:, None] * normal).astype(int), axis=0)
        displacement = np.linalg.norm(candidates - point, axis=1)
        keep = ((displacement <= radius + 1e-8) & (candidates[:, 0] >= 0) &
                (candidates[:, 0] < terrain.height) & (candidates[:, 1] >= 0) &
                (candidates[:, 1] < terrain.width))
        candidates = candidates[keep]
        candidates = np.asarray([p for p in candidates if terrain.valid[tuple(p)] and
                                 _segment_valid(terrain.valid, point, p)], dtype=int)
        if not len(candidates):
            continue
        # Include the original cell explicitly, even for an oblique cross-section.
        candidates = np.unique(np.vstack((point, candidates)), axis=0)
        # Assess a short continuing feature, not just the three cells around
        # a point. A tiny sharp shoulder bump can otherwise outrank a broad
        # continuous crest (or a small pit outrank a channel) through local
        # curvature alone. Keep this support independent of search radius and
        # shorten it near closely spaced guides so it does not span a bend.
        support_radius = min(8., min(lengths) * .25)
        longitudinal = np.linspace(-support_radius, support_radius,
                                   2 * max(1, math.ceil(support_radius)) + 1)
        padding = math.ceil(support_radius) + 5
        r0, c0 = np.maximum(candidates.min(axis=0) - padding, 0)
        r1, c1 = np.minimum(candidates.max(axis=0) + padding + 1, (terrain.height, terrain.width))
        bounds = (int(r0), int(r1), int(c0), int(c1))
        cost = _cost(terrain, bounds, kind, params, tangent, cancel=cancel)
        local_mask = terrain.valid[r0:r1, c0:c1]
        cost[~local_mask] = np.inf
        support = _profile_support_cost(cost, local_mask, candidates - [r0, c0], tangent, longitudinal)
        score = support.copy()
        distance = np.linalg.norm(candidates - point, axis=1)
        score += .4 * np.square(distance / max(radius, 1.)) + .01 * distance
        original = int(np.flatnonzero(np.all(candidates == point, axis=1))[0])
        # No reliable terrain evidence (flat ground, edge, or tiny improvement):
        # keep the rough guide instead of arbitrarily choosing a nearby cell.
        selected = int(np.argmin(score))
        if math.isfinite(score[original]) and score[selected] < score[original] - .1:
            # A favorable monotonic trend is not a located crest, trough, or
            # bank. Require supporting terrain on both sides of the proposed
            # guide. Otherwise a broad descriptor can push guides across flat
            # ground away from an isolated pit, or pick an arbitrary shoulder
            # in a smooth parabola when slope-break mode has no discrete edge.
            cross = candidates[selected] + np.array([-4., 4.])[:, None] * normal
            sides = _profile_support_cost(cost, local_mask, cross - [r0, c0], tangent, longitudinal)
            if np.isfinite(sides).all() and np.all(sides > support[selected] + .01):
                output[index] = tuple(int(v) for v in candidates[selected])
    return output


def _route(terrain, a, b, kind, params, cancel=None, guide=None, resample=True):
    _check_cancel(cancel)
    guide_a, guide_b = guide if guide is not None else (a, b)
    margin = math.ceil(min(params.corridor, max(terrain.height, terrain.width))) + 1
    r0, r1 = max(0, min(guide_a[0], guide_b[0]) - margin), min(terrain.height, max(guide_a[0], guide_b[0]) + margin + 1)
    c0, c1 = max(0, min(guide_a[1], guide_b[1]) - margin), min(terrain.width, max(guide_a[1], guide_b[1]) + margin + 1)
    rr, cc = np.ogrid[r0:r1, c0:c1]
    distance = _distance_to_segment(rr, cc, guide_a, guide_b)
    mask = terrain.valid[r0:r1, c0:c1] & (distance <= params.corridor + 1e-8)
    cost = _cost(terrain, (r0, r1, c0, c1), kind, params, (b[0] - a[0], b[1] - a[1]), cancel=cancel, guidance_mask=mask)
    # A weak guidance term resolves ties on flat ground without overpowering
    # terrain. The corridor itself is a hard constraint.
    cost += .15 * (distance / params.corridor) ** 2
    cost[~mask] = np.inf
    start, end = (a[0] - r0, a[1] - c0), (b[0] - r0, b[1] - c0)
    sampling = (abs(terrain.transform.e) / terrain.resolution,
                abs(terrain.transform.a) / terrain.resolution)
    def solve(fully_connected):
        _check_cancel(cancel)
        solver = MCP_Geometric(cost, fully_connected=fully_connected, sampling=sampling)
        # The compiled MCP solve cannot be interrupted mid-call. Cancellation
        # is observed immediately before and after each solve.
        solver.find_costs([start], [end])
        _check_cancel(cancel)
        return solver.traceback(end)
    try:
        path = solve(True)
        # MCP permits cutting a diagonal across invalid corners. Fall back to
        # cardinal connectivity when that happens, preserving valid topology.
        unsafe = any(p[0] != q[0] and p[1] != q[1] and
                     (not mask[p[0], q[1]] or not mask[q[0], p[1]])
                     for p, q in zip(path[:-1], path[1:]))
        if unsafe:
            path = solve(False)
    except TraceCancelled:
        raise
    except (ValueError, RuntimeError) as exc:
        raise ValueError("No valid route connects these anchors inside the corridor. Widen the corridor or add anchors around NoData.") from exc
    if not path or not all(mask[r, c] for r, c in path):
        raise ValueError("No valid route connects these anchors inside the corridor. Widen the corridor or move an anchor.")
    _check_cancel(cancel)
    if params.line_smoothing > 0:
        shaped = _smooth_vectors(path, mask, cost, params.line_smoothing, params.terrain_weight, cancel)
    else:
        shaped = _simplify(path, params.simplify, mask)
    _check_cancel(cancel)
    spaced = _resample(shaped, params.spacing, mask=mask, tolerance=params.simplify) if resample else shaped
    # Local-mask validation also guarantees the simplified route stays inside
    # the hard corridor, including between vertices.
    if not all(_segment_valid(mask, p, q) for p, q in zip(spaced[:-1], spaced[1:])):
        raise ValueError("A route segment crosses NoData; add an anchor away from the raster boundary.")
    return [[r + r0, c + c0] for r, c in spaced]


def _result(terrain, cells, kind, params, extra_warnings=None):
    xy = [terrain.xy(r, c) for r, c in cells]
    elevations = terrain.sample_many(xy)
    if any(z is None for z in elevations):
        raise ValueError("A traced vertex touches source NoData. Move the anchors farther from the gap.")
    coordinates = [[x, y, z] for (x, y), z in zip(xy, elevations)]
    distance = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(coordinates[:-1], coordinates[1:]))
    dz = np.diff(elevations)
    edge_pixels = np.linalg.norm(np.diff(np.asarray(cells), axis=0), axis=1)
    edge_map = np.linalg.norm(np.diff(np.asarray(xy), axis=0), axis=1)
    short_edges = int(np.count_nonzero(edge_pixels < params.spacing * .625))
    warnings = list(extra_warnings or [])
    if not math.isclose(abs(terrain.transform.a), abs(terrain.transform.e), rel_tol=1e-6):
        warnings.append("This DEM has rectangular pixels. Corridor, smoothing, and spacing are measured in working pixels; map-unit sizes vary with direction.")
    if terrain.metadata.get('resampled'):
        warnings.append("Traced on a reduced working grid; inspect against the original DEM before production use.")
    if terrain.metadata.get('vertical_units_assumed'):
        warnings.append("The DEM does not identify vertical units. Elevations are preserved; slope displays assume horizontal units.")
    if kind in {'stream', 'downstream'} and np.sum(np.maximum(dz, 0)) > max(.001, float(np.ptp(elevations)) * .02):
        warnings.append("This line contains uphill segments. Check direction, pits, bridges, and anchor placement; no depression filling is applied.")
    metrics = {"length": float(distance), "units": terrain.units,
               "vertices": len(coordinates), "elevation_min": float(min(elevations)),
               "elevation_max": float(max(elevations)), "elevation_start": float(elevations[0]),
               "elevation_end": float(elevations[-1]), "elevation_gain": float(np.maximum(dz, 0).sum()),
               "elevation_loss": float(-np.minimum(dz, 0).sum()),
               "vertical_units": terrain.metadata.get('vertical_units', 'unspecified'),
               "working_resolution": terrain.resolution, "corridor_map_units": params.corridor * terrain.resolution,
               "corridor_map_units_xy": [params.corridor * abs(terrain.transform.a), params.corridor * abs(terrain.transform.e)],
               "spacing_min": float(edge_map.min()), "spacing_median": float(np.median(edge_map)),
               "spacing_max": float(edge_map.max()), "spacing_min_pixels": float(edge_pixels.min()),
               "spacing_median_pixels": float(np.median(edge_pixels)), "spacing_max_pixels": float(edge_pixels.max()),
               "spacing_exception_count": short_edges, "target_spacing_pixels": params.spacing,
               "spacing_long_edge_count": int(np.count_nonzero(edge_pixels > params.spacing * (1 + 1e-8))),
               "line_smoothing_pixels": params.line_smoothing if kind != 'manual' else 0.,
               "kind": kind}
    return TraceResult(coordinates, cells, metrics, warnings)


def _sharp_guide_indices(coordinates, indices):
    """Return one-based guide labels whose adjacent map-space turn exceeds 90°."""
    sharp = []
    for guide, index in enumerate(indices[1:-1], 2):
        incoming = np.asarray(coordinates[index][:2]) - coordinates[index - 1][:2]
        outgoing = np.asarray(coordinates[index + 1][:2]) - coordinates[index][:2]
        norm = float(np.linalg.norm(incoming) * np.linalg.norm(outgoing))
        angle = math.degrees(math.acos(np.clip(float(incoming @ outgoing) / max(norm, 1e-12), -1, 1)))
        if angle > 90. + 1e-6:
            sharp.append(guide)
    return sharp


def _guide_warning(indices):
    labels = ', '.join(str(i) for i in indices)
    return f'Guide anchor(s) {labels} create turns sharper than 90°. Check that these fixed guides lie on the intended crest or channel; they have not been moved automatically.'


def trace(terrain: Terrain, anchors, kind: str, params: TraceParams | None = None,
          cancel=None, fixed_anchor_indices=None) -> TraceResult:
    """Follow rough guides in click order, retaining manual subcell positions.

    Spacing targets evenly distributed arc-length stations in working pixels;
    hard anchors, genuine bends, and obstacle safety can need closer vertices.
    Assisted guides may move laterally unless ``relax_anchors`` is false or
    their original zero-based index is in ``fixed_anchor_indices``. It is not
    a hydrologic integration step. Smoothing changes
    terrain guidance, never exported source elevations. Stream routes can climb
    and must be reviewed; explicit warnings report this condition.
    """
    _check_cancel(cancel)
    params = params or default_params(terrain, kind)
    _validate(terrain, params)
    if kind not in {'ridge', 'stream', 'slope_break', 'manual'}:
        raise ValueError("Choose ridge, stream, slope_break, or manual tracing.")
    if len(anchors) < 2:
        raise ValueError("Add at least two anchors to trace a line.")
    fixed = set()
    if fixed_anchor_indices is not None:
        for index in fixed_anchor_indices:
            if isinstance(index, bool) or not isinstance(index, (int, np.integer)) or not 0 <= index < len(anchors):
                raise ValueError('Fixed anchor indices must identify existing guides using zero-based integers.')
            fixed.add(int(index))
    validated = [_anchor(terrain, p) for p in anchors]
    # Manual geometry follows the user's actual positions, including distinct
    # subcell anchors. Terrain-assisted paths continue to use cell centers.
    source = [(float(p[0]), float(p[1])) for p in anchors] if kind == 'manual' else validated
    points, mapped_fixed = [], set()
    for index, point in enumerate(source):
        if not points or point != points[-1]:
            points.append(point)
        if index in fixed:
            mapped_fixed.add(len(points) - 1)
    fixed = mapped_fixed
    if len(points) < 2:
        location = 'map position' if kind == 'manual' else 'terrain pixel'
        raise ValueError(f'Place the second anchor in a different {location}.')
    relaxed = kind != 'manual' and params.relax_anchors
    routed_points = _relax_guides(terrain, points, kind, params, fixed, cancel) if relaxed else points
    cells = []
    anchor_indices = [0]
    for index, (a, b) in enumerate(zip(routed_points[:-1], routed_points[1:])):
        _check_cancel(cancel)
        if kind == 'manual':
            if not _segment_valid(terrain.valid, a, b):
                raise ValueError("A manual segment crosses NoData. Add an anchor around the gap.")
            part = _resample([a, b], params.spacing)
        else:
            part = _route(terrain, a, b, kind, params, cancel=cancel,
                          guide=(points[index], points[index + 1]), resample=not relaxed)
        cells.extend(part if not cells else part[1:])
        anchor_indices.append(len(cells) - 1)
    sharp_guides = _sharp_guide_indices([terrain.xy(r, c) for r, c in cells], anchor_indices)
    if relaxed:
        # Preserve the complete original corridor during cross-guide sampling.
        # Only explicit fixed guides restart spacing; rough guides are shape
        # references, so their count and search radius do not dictate density.
        mask = np.zeros_like(terrain.valid)
        margin = math.ceil(min(params.corridor, max(terrain.height, terrain.width))) + 1
        for a, b in zip(points[:-1], points[1:]):
            r0, r1 = max(0, min(a[0], b[0]) - margin), min(terrain.height, max(a[0], b[0]) + margin + 1)
            c0, c1 = max(0, min(a[1], b[1]) - margin), min(terrain.width, max(a[1], b[1]) + margin + 1)
            rr, cc = np.ogrid[r0:r1, c0:c1]
            mask[r0:r1, c0:c1] |= _distance_to_segment(rr, cc, a, b) <= params.corridor + 1e-8
        mask &= terrain.valid
        boundaries = sorted({0, len(cells) - 1} | {anchor_indices[i] for i in fixed})
        sampled = []
        for start, stop in zip(boundaries[:-1], boundaries[1:]):
            _check_cancel(cancel)
            part = _resample(cells[start:stop + 1], params.spacing, mask=mask, tolerance=params.simplify)
            sampled.extend(part if not sampled else part[1:])
        cells = sampled
    _check_cancel(cancel)
    result = _result(terrain, cells, kind, params)
    _check_cancel(cancel)
    result.anchors = [list(terrain.xy(r, c)) for r, c in points]
    result.fixed_anchor_indices = sorted(fixed)
    result.metrics['sharp_guide_indices'] = sharp_guides
    movement = np.linalg.norm(np.asarray(routed_points) - points, axis=1)
    result.metrics['relaxed_guide_count'] = int(np.count_nonzero(movement > 1e-8))
    result.metrics['guide_displacement_max_pixels'] = float(movement.max())
    result.metrics['fixed_anchor_indices'] = sorted(fixed) if relaxed else list(range(len(points)))
    if sharp_guides and kind != 'manual':
        result.warnings.append(_guide_warning(sharp_guides) if not relaxed else
                               'The rough guide creates a turn sharper than 90°. Review guide order and the intended terrain feature.')
    return result


def trace_downstream(terrain: Terrain, start, params: TraceParams | None = None, cancel=None) -> TraceResult:
    """Steepest D8 descent on a smoothed DEM, stopping at a pit or boundary.

    This exploratory single-seed tool does not fill depressions, infer outlets,
    cross NoData, or promise network connectivity. Anchored stream tracing is
    preferable where drainage is ambiguous.
    """
    _check_cancel(cancel)
    params = params or default_params(terrain, 'downstream')
    _validate(terrain, params)
    current = _anchor(terrain, start)
    z = ndimage.gaussian_filter(terrain.surface(), params.smoothing) if params.smoothing else terrain.surface()
    points = [current]
    reason = "Stopped at a local pit or flat; no depression filling is applied."
    limit = min(100_000, terrain.width * terrain.height)
    sx, sy = abs(terrain.transform.a), abs(terrain.transform.e)
    for step in range(limit):
        if step % 64 == 0:
            _check_cancel(cancel)
        r, c = current
        if r in (0, terrain.height - 1) or c in (0, terrain.width - 1):
            reason = "Stopped at the raster edge."
            break
        best, best_drop = None, 1e-10
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if not (dr or dc) or not terrain.valid[r + dr, c + dc]:
                    continue
                if dr and dc and (not terrain.valid[r + dr, c] or not terrain.valid[r, c + dc]):
                    continue
                drop = float(z[r, c] - z[r + dr, c + dc]) / math.hypot(dc * sx, dr * sy)
                if drop > best_drop:
                    best, best_drop = (r + dr, c + dc), drop
        if best is None:
            break
        current = best
        points.append(current)
    else:
        reason = "Stopped at the 100,000-step safety limit."
    if len(points) < 2:
        raise ValueError("The seed is at a pit, flat, or raster edge. Use two or more stream anchors to guide a route.")
    cells = _resample(_simplify(points, params.simplify, terrain.valid), params.spacing, mask=terrain.valid, tolerance=params.simplify)
    _check_cancel(cancel)
    result = _result(terrain, cells, 'downstream', params, [reason])
    _check_cancel(cancel)
    return result
