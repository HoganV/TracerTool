"""Bounded, calibrated source-native windows for experimental reach analysis.

No resampling or vertical conversion is applied to stored elevations. Window
allocation is checked before raster reads; missing source data is never filled
in the routing mask.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import math
import numpy as np
import rasterio
from affine import Affine
from .tracing import TraceCancelled

# Measured native windows stay below 4 GiB; no implicit downsampling.
MAX_CELLS = 2_000_000
WHOLE_SOURCE_CELLS = 500_000


def check_cancel(cancel):
    if cancel is not None and cancel():
        raise TraceCancelled('Tracing cancelled; no line was changed.')


def check_source_identity(identity):
    """Reject source replacement between analysis and publication of a result."""
    try:
        stat = Path(identity['path']).stat()
        dependencies = identity.get('dependencies', [])
        for item in dependencies:
            current = Path(item['path']).stat()
            if (current.st_size, current.st_mtime_ns) != (item['size'], item['mtime_ns']):
                raise ValueError('Source changed during analysis (raster dependency); reload and retry.')
        if dependencies:
            with rasterio.open(identity['path']) as src:
                if set(src.files) != {item['path'] for item in dependencies}:
                    raise ValueError('Source changed during analysis (raster dependencies); reload and retry.')
    except (OSError, rasterio.errors.RasterioIOError) as exc:
        raise ValueError('Source changed or became unavailable during analysis; reload and retry.') from exc
    if (stat.st_size, stat.st_mtime_ns) != (identity['size'], identity['mtime_ns']):
        raise ValueError('Source changed during analysis; reload and retry.')


@dataclass
class AnalysisGrid:
    data: np.ndarray
    valid: np.ndarray
    transform: Affine
    bounds: tuple
    source_shape: tuple
    vertical_to_horizontal: float | None
    source_identity: dict

    @property
    def resolution_xy(self):
        return abs(self.transform.a), abs(self.transform.e)

    def xy(self, row, col):
        return (float(self.transform.c + (col + .5) * self.transform.a),
                float(self.transform.f + (row + .5) * self.transform.e))

    def rc(self, x, y):
        return ((y - self.transform.f) / self.transform.e - .5,
                (x - self.transform.c) / self.transform.a - .5)


def condition_small_pits(grid, cancel=None):
    """Bounded analysis-only fill; never infer metres or cut an outlet.

    Priority flood computes hypothetical spill depths over the native valid
    graph. Only entire connected depressions of <=9 cells AND <=2 sigma are
    changed. Sigma is a relative source-Z roughness proxy: the minimum over
    four directional median-centred second-difference MADs divided by
    0.67448975*sqrt(6). It is NOT instrument accuracy or proof of an artifact.
    The area cap prevents waterbody/road-scale treatment, and component-level
    rejection prevents incrementally filling a deep basin via many tiny steps.
    Boundary/NoData-adjacent cells are open/unknown seeds, never crossed.
    """
    import heapq
    from dataclasses import replace
    from scipy import ndimage
    z, valid = grid.data, grid.valid
    h, w = z.shape
    estimates = []
    if h >= 3 and w >= 3:
        for dr, dc in ((1, 0), (0, 1), (1, 1), (1, -1)):
            check_cancel(cancel)
            values = (z[1+dr:h-1+dr, 1+dc:w-1+dc] +
                      z[1-dr:h-1-dr, 1-dc:w-1-dc] - 2*z[1:-1, 1:-1])
            values = values[np.isfinite(values)]
            if len(values):
                estimates.append(float(np.median(abs(values-np.median(values)))) /
                                 (.67448975*math.sqrt(6.)))
    sigma = min(estimates) if estimates else 0.
    limit = 2*sigma
    boundary = valid & ~ndimage.binary_erosion(valid, structure=np.ones((3, 3)))
    visited = ~valid | boundary
    filled = z.copy()
    queue = [(float(z[r, c]), int(r*w+c)) for r, c in np.argwhere(boundary)]
    heapq.heapify(queue)
    neighbors = ((-1, -1), (-1, 0), (-1, 1), (0, -1),
                 (0, 1), (1, -1), (1, 0), (1, 1))
    count = 0
    while queue:
        level, index = heapq.heappop(queue)
        count += 1
        if count % 4096 == 0:
            check_cancel(cancel)
        r, c = divmod(index, w)
        for dr, dc in neighbors:
            nr, nc = r+dr, c+dc
            if not (0 <= nr < h and 0 <= nc < w) or visited[nr, nc]:
                continue
            if dr and dc and not (valid[nr, c] and valid[r, nc]):
                continue
            visited[nr, nc] = True
            height = max(level, float(z[nr, nc]))
            filled[nr, nc] = height
            heapq.heappush(queue, (height, nr*w+nc))
    depth = np.where(valid, filled-z, 0.)
    labels, count = ndimage.label(depth > 0., structure=np.ones((3, 3)))
    sizes = np.bincount(labels.ravel(), minlength=count+1)
    maxima = ndimage.maximum(depth, labels, np.arange(1, count+1)) if count else []
    allowed = np.zeros(count+1, dtype=bool)
    pits = []
    slices = ndimage.find_objects(labels)
    for label, (maximum, bounds) in enumerate(zip(maxima, slices), 1):
        check_cancel(cancel)
        allowed[label] = sizes[label] <= 9 and maximum <= limit
        # Representative deepest cell; depths and affected area cover the whole
        # depression, not merely a single-cell nearest-neighbor escape.
        local = np.where(labels[bounds] == label, depth[bounds], -1.)
        r, c = np.unravel_index(np.argmax(local), local.shape)
        r, c = int(r+bounds[0].start), int(c+bounds[1].start)
        pits.append({'id': label, 'native_cell': [r+grid.bounds[0], c+grid.bounds[2]],
                     'location': list(grid.xy(r, c)), 'cells': int(sizes[label]),
                     'raw_source_z_at_max_depth': float(z[r, c]),
                     'spill_source_z': float(filled[r, c]),
                     'max_depth_source_units': float(maximum),
                     'applied_max_depth_source_units': float(maximum) if allowed[label] else 0.,
                     'decision': 'bounded_noise_scale_fill' if allowed[label] else 'retained_depression'})
    changed = allowed[labels]
    derived = np.where(changed, filled, z)
    info = {'policy': 'bounded_noise_scale_pits', 'noise_estimator': 'min_directional_second_difference_mad',
            'noise_sigma_source_units': sigma, 'depth_limit_source_units': limit,
            'max_pit_cells': 9, 'changed_cells': int(changed.sum()),
            'max_changed_depth_source_units': float(depth[changed].max()) if changed.any() else 0.,
            'pits': pits, '_pit_labels': labels}
    check_cancel(cancel)
    return replace(grid, data=derived), info


def read_grid(terrain, bounds=None, *, max_cells=MAX_CELLS, cancel=None):
    """Read a half-open native (r0,r1,c0,c1) window, never the display grid."""
    check_cancel(cancel)
    terrain.check_source_unchanged()
    try:
        stat = Path(terrain.path).stat()
        if (stat.st_size != terrain.metadata.get('source_size', stat.st_size) or
                stat.st_mtime_ns != terrain.metadata.get('source_mtime_ns', stat.st_mtime_ns)):
            raise ValueError('Source changed after loading; reload the DEM before Auto tracing.')
        with rasterio.open(terrain.path) as src:
            h, w = src.height, src.width
            bounds = (0, h, 0, w) if bounds is None else tuple(bounds)
            if (len(bounds) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, np.integer)) for v in bounds)):
                raise ValueError('Analysis bounds must be four native integer indices.')
            r0, r1, c0, c1 = bounds
            if not (0 <= r0 < r1 <= h and 0 <= c0 < c1 <= w):
                raise ValueError('Analysis window is outside the native DEM.')
            if (r1-r0) * (c1-c0) > max_cells:
                raise ValueError('Native Auto domain exceeds the memory budget; crop the DEM to this reach and retry.')
            t = src.transform
            if t.b or t.d or t.a <= 0 or t.e >= 0:
                raise ValueError('Auto requires a north-up, unrotated source DEM.')
            if src.crs != terrain.crs or t != terrain._source_transform:
                raise ValueError('Source grid changed; reload the DEM before Auto tracing.')
            scale, offset = float(src.scales[0]), float(src.offsets[0])
            if not math.isfinite(scale) or not math.isfinite(offset):
                raise ValueError('Source band calibration must be finite.')
            dependencies = []
            for path in src.files:
                dependency = Path(path).stat()
                dependencies.append({'path': path, 'size': dependency.st_size,
                                     'mtime_ns': dependency.st_mtime_ns})
            data = np.empty((r1-r0, c1-c0), dtype=np.float64)
            for row in range(r0, r1, 128):
                check_cancel(cancel)
                stop = min(r1, row+128)
                a = src.read(1, window=((row, stop), (c0, c1)), masked=True, out_dtype='float64')
                data[row-r0:stop-r0] = a.filled(np.nan) * scale + offset
            data[~np.isfinite(data)] = np.nan
            identity = {'path': str(terrain.path), 'size': stat.st_size,
                        'mtime_ns': stat.st_mtime_ns, 'sha256': terrain.metadata.get('source_sha256'),
                        'band': 1, 'band_scale': scale, 'band_offset': offset,
                        'dependencies': dependencies,
                        'crs': src.crs.to_string() if src.crs else None,
                        'native_shape': [h, w]}
        check_source_identity(identity)
        terrain.check_source_unchanged()
    except (OSError, rasterio.errors.RasterioIOError) as exc:
        raise ValueError(f'Cannot read native source DEM: {exc}') from exc
    check_cancel(cancel)
    factor = (None if terrain.metadata.get('vertical_units_assumed', True)
              else float(terrain.metadata['vertical_to_horizontal']))
    return AnalysisGrid(data, np.isfinite(data), t @ Affine.translation(c0, r0),
                        bounds, (h, w), factor, identity)
