"""Raster loading and display in the source CRS, without silent reprojection.

A bounded working grid keeps the viewer responsive. Resampling is explicitly
recorded; vector Z values always come from source pixels (nearest neighbour),
not the display surface. Horizontal and vertical datum transformations are out
of scope. Rotated/sheared grids are rejected rather than shown incorrectly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math
import hashlib
from numbers import Integral, Real

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from scipy import ndimage


_BACKGROUND = np.array([24, 30, 40], dtype=np.uint8)


def filled_surface(data: np.ndarray) -> np.ndarray:
    """Nearest valid fill for derivatives only; never changes the valid mask."""
    valid = np.isfinite(data)
    if valid.all():
        return data.copy()
    if not valid.any():
        raise ValueError("The elevation band contains no valid pixels.")
    nearest = ndimage.distance_transform_edt(~valid, return_distances=False,
                                             return_indices=True)
    return data[tuple(nearest)].astype(np.float32)


def _unit_scale(unit: str | None) -> float | None:
    unit = (unit or "").lower().strip().replace("_", " ")
    if unit in {"m", "meter", "meters", "metre", "metres"}:
        return 1.0
    if "survey" in unit and ("foot" in unit or "feet" in unit):
        return 1200 / 3937
    if unit in {"ft", "foot", "feet", "international foot"}:
        return .3048
    return None


@dataclass
class Terrain:
    path: str
    data: np.ndarray
    valid: np.ndarray
    transform: Affine
    crs: object
    width: int
    height: int
    resolution: float
    units: str
    metadata: dict
    bounds: tuple[float, float, float, float]
    _source_transform: Affine = field(repr=False)
    _source_data: np.ndarray | None = field(default=None, repr=False)
    _filled: np.ndarray | None = field(default=None, repr=False)
    _render_cache: dict = field(default_factory=dict, repr=False)
    _source_scale: float = field(default=1., repr=False)
    _source_offset: float = field(default=0., repr=False)

    @classmethod
    def load(cls, path, max_dimension=2400, *, compute_fingerprint=False) -> "Terrain":
        if not isinstance(max_dimension, int) or max_dimension < 2:
            raise ValueError("Maximum display dimension must be an integer of at least 2.")
        path = str(Path(path).expanduser().resolve())
        try:
            source_stat = Path(path).stat()
            source = rasterio.open(path)
        except (rasterio.errors.RasterioIOError, OSError) as exc:
            raise ValueError(f"Cannot open terrain raster: {exc}") from exc
        with source:
            # Capture every GDAL-reported dependency before any pixel read, so
            # a VRT and the cached elevations cannot describe different epochs.
            try:
                dependencies = []
                for dependency_path in source.files:
                    stat = Path(dependency_path).stat()
                    dependencies.append({'path': dependency_path, 'size': stat.st_size,
                                         'mtime_ns': stat.st_mtime_ns})
            except OSError as exc:
                raise ValueError(f'Cannot identify terrain dependency: {exc}') from exc
            if not source.count or source.width < 2 or source.height < 2:
                raise ValueError("Terrain needs an elevation band at least 2 × 2 pixels.")
            if np.dtype(source.dtypes[0]).kind == 'c':
                raise ValueError("Complex-valued rasters cannot be used as elevation data.")
            source_scale, source_offset = float(source.scales[0]), float(source.offsets[0])
            if not math.isfinite(source_scale) or not math.isfinite(source_offset):
                raise ValueError("The elevation band has invalid scale/offset metadata. Export calibrated elevation values first.")
            t = source.transform
            if not np.isclose(t.b, 0, atol=1e-12) or not np.isclose(t.d, 0, atol=1e-12):
                raise ValueError("Rotated or sheared rasters are not supported yet. Export a north-up DEM first.")
            if t.a <= 0 or t.e >= 0:
                raise ValueError("Use a north-up raster with increasing easting and decreasing row northing.")
            factor = min(1., max_dimension / max(source.width, source.height))
            width, height = max(2, round(source.width * factor)), max(2, round(source.height * factor))
            working_t = Affine(t.a * source.width / width, 0, t.c,
                               0, t.e * source.height / height, t.f)
            # Small and typical tiles are retained in full for fast source Z reads.
            source_data = None
            if source.width * source.height <= 16_000_000:
                # Decode before any float32 working-grid conversion: encoded
                # integer offsets can otherwise erase distinct source heights.
                # The source cache retains float64 precision for exported Z.
                a = source.read(1, masked=True, out_dtype='float64')
                source_data = np.asarray(a.filled(np.nan), dtype=np.float64)
                source_data = source_data * source_scale + source_offset
                source_data[~np.isfinite(source_data)] = np.nan
            if (width, height) == (source.width, source.height) and source_data is not None:
                data = source_data.astype(np.float32)
            else:
                a = source.read(1, out_shape=(height, width), masked=True,
                                resampling=Resampling.bilinear, out_dtype='float64')
                data = ((np.asarray(a.filled(np.nan), dtype=np.float64) * source_scale)
                        + source_offset).astype(np.float32)
                # Bilinear interpolation alone can hide small NoData holes.
                # Map every invalid source pixel footprint to the display grid.
                # Scan strips rather than allocating an entire large source DEM.
                strip_height = max(1, min(512, 4_000_000 // source.width))
                for row in range(0, source.height, strip_height):
                    stop = min(source.height, row + strip_height)
                    if source_data is not None:
                        strip = source_data[row:stop]
                    else:
                        a = source.read(1, window=((row, stop), (0, source.width)),
                                        masked=True, out_dtype='float64')
                        strip = np.asarray(a.filled(np.nan)) * source_scale + source_offset
                    rr, cc = np.where(~np.isfinite(strip))
                    if not len(rr):
                        continue
                    rr = rr + row
                    r0 = np.floor(rr * height / source.height).astype(int)
                    c0 = np.floor(cc * width / source.width).astype(int)
                    r1 = np.minimum(height - 1, np.ceil((rr + 1) * height / source.height).astype(int) - 1)
                    c1 = np.minimum(width - 1, np.ceil((cc + 1) * width / source.width).astype(int) - 1)
                    data[r0, c0] = data[r0, c1] = data[r1, c0] = data[r1, c1] = np.nan
            data[~np.isfinite(data)] = np.nan
            valid = np.isfinite(data)
            if not valid.any():
                raise ValueError("The elevation band contains no valid pixels.")
            crs = source.crs
            projected = bool(crs and crs.is_projected)
            units = crs.linear_units if projected else ("degrees" if crs and crs.is_geographic else "unknown units")
            resolution = math.sqrt(abs(working_t.a * working_t.e))
            vertical_units = source.units[0] or source.tags(1).get('UNITTYPE', '') or "unspecified"
            horizontal_m = crs.linear_units_factor[1] if projected else None
            vertical_m = _unit_scale(vertical_units)
            metadata = {
                "original_width": source.width, "original_height": source.height,
                "working_width": width, "working_height": height,
                "original_resolution": math.sqrt(abs(t.a * t.e)),
                "original_resolution_xy": [abs(t.a), abs(t.e)],
                "working_resolution": resolution,
                "working_resolution_xy": [abs(working_t.a), abs(working_t.e)],
                "resampled": (width, height) != (source.width, source.height),
                "resampling": "bilinear; conservative NoData mask" if (width, height) != (source.width, source.height) else "none",
                "min": float(np.nanmin(data)), "max": float(np.nanmax(data)),
                "crs": crs.to_string() if crs else None,
                "crs_wkt": crs.to_wkt() if crs else None,
                "units": units, "vertical_units": vertical_units,
                "vertical_to_horizontal": vertical_m / horizontal_m if vertical_m and horizontal_m else 1.,
                "vertical_units_assumed": vertical_m is None,
                "valid_fraction": float(valid.mean()), "band": 1,
                "source_size": source_stat.st_size, "source_mtime_ns": source_stat.st_mtime_ns,
                "source_dependencies": dependencies,
                "band_scale": source_scale, "band_offset": source_offset,
                "scale_offset_applied": source_scale != 1. or source_offset != 0.,
                "source_nodata": float(source.nodata) if source.nodata is not None and math.isfinite(source.nodata) else None,
            }
            terrain = cls(path, data, valid, working_t, crs, width, height,
                          resolution, units, metadata, tuple(source.bounds), t, source_data,
                          _source_scale=source_scale, _source_offset=source_offset)
        terrain.check_source_unchanged()
        if compute_fingerprint:
            terrain.fingerprint()
        return terrain

    def check_source_unchanged(self):
        """Reject a changed load-time raster/dependency snapshot before use.

        Identities are local file size/mtime checks, not content hashes. This
        guard also covers the snapshot retained in the source sampling cache.
        """
        try:
            stat = Path(self.path).stat()
            if (stat.st_size, stat.st_mtime_ns) != (
                    self.metadata['source_size'], self.metadata['source_mtime_ns']):
                raise ValueError('Source changed after loading; reload the DEM before continuing.')
            dependencies = self.metadata.get('source_dependencies', [])
            for item in dependencies:
                current = Path(item['path']).stat()
                if (current.st_size, current.st_mtime_ns) != (item['size'], item['mtime_ns']):
                    raise ValueError('Source changed after loading (raster dependency); reload the DEM before continuing.')
            if dependencies:
                with rasterio.open(self.path) as source:
                    if set(source.files) != {item['path'] for item in dependencies}:
                        raise ValueError('Source changed after loading (raster dependencies); reload the DEM before continuing.')
        except (OSError, rasterio.errors.RasterioIOError) as exc:
            raise ValueError('Source changed or became unavailable after loading; reload the DEM before continuing.') from exc

    def fingerprint(self):
        """Return a cached SHA256 of this loaded raster's file contents.

        This explicitly reads the primary raster file once. For container or
        virtual formats referencing external files, it is not a digest of all
        external dependencies. Ordinary self-contained GeoTIFFs are covered.
        """
        if self.metadata.get('source_sha256'):
            return self.metadata['source_sha256']
        try:
            before = Path(self.path).stat()
            if (before.st_size != self.metadata.get('source_size') or
                    before.st_mtime_ns != self.metadata.get('source_mtime_ns')):
                raise ValueError('The terrain file changed after loading. Reload it before computing its fingerprint.')
            digest = hashlib.sha256()
            with open(self.path, 'rb') as handle:
                while block := handle.read(8 * 1024 * 1024):
                    digest.update(block)
            after = Path(self.path).stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('The terrain file changed while computing its fingerprint. Reload it and try again.')
        except OSError as exc:
            raise ValueError(f'Cannot fingerprint the terrain file: {exc}') from exc
        self.metadata['source_sha256'] = digest.hexdigest()
        self.metadata['fingerprint_scope'] = 'primary raster file'
        return self.metadata['source_sha256']

    def xy(self, row, col):
        """Map a working pixel-center index to native CRS coordinates."""
        x = self.transform.c + self.transform.a * (float(col) + .5)
        y = self.transform.f + self.transform.e * (float(row) + .5)
        return float(x), float(y)

    def rc(self, x, y):
        col = (float(x) - self.transform.c) / self.transform.a
        row = (float(y) - self.transform.f) / self.transform.e
        return float(row - .5), float(col - .5)

    def sample(self, x, y):
        return self.sample_many([(x, y)])[0]

    def sample_many(self, coordinates):
        """Read nearest source-pixel elevations, returning None outside/at NoData."""
        self.check_source_unchanged()
        points = list(coordinates)
        if self._source_data is not None:
            out = []
            h, w = self._source_data.shape
            for x, y in points:
                if not math.isfinite(x) or not math.isfinite(y):
                    out.append(None)
                    continue
                c = (x - self._source_transform.c) / self._source_transform.a
                r = (y - self._source_transform.f) / self._source_transform.e
                r, c = math.floor(r), math.floor(c)
                value = self._source_data[r, c] if 0 <= r < h and 0 <= c < w else np.nan
                out.append(float(value) if np.isfinite(value) else None)
            return out
        out = []
        with rasterio.open(self.path) as source:
            for (x, y) in points:
                if not math.isfinite(x) or not math.isfinite(y):
                    out.append(None)
                    continue
                row, col = source.index(x, y)
                if not (0 <= row < source.height and 0 <= col < source.width):
                    out.append(None)
                    continue
                a = source.read(1, window=((row, row + 1), (col, col + 1)), masked=True)
                value = a[0, 0]
                decoded = (float(value) * self._source_scale + self._source_offset
                           if not np.ma.is_masked(value) and np.isfinite(value) else np.nan)
                out.append(decoded if math.isfinite(decoded) else None)
        self.check_source_unchanged()
        return out

    def surface(self):
        if self._filled is None:
            self._filled = filled_surface(self.data)
        return self._filled

    def rgb(self, style='Terrain', azimuth=315, altitude=45, z_factor=1, *,
            palette='earth', stretch='percentile', low=None, high=None,
            shade_strength=.65, gamma=1., multidirectional=False, vertical_units=None,
            view_bounds=None):
        """Render a preview without modifying source data, exported Z, or units.

        Elevation stretches are 1st–99th percentile, full min/max, visible
        min/max, or custom decoded elevation bounds. For visible min/max,
        view_bounds is a half-open (row_start, row_stop, col_start, col_stop)
        region in the working raster; it is rounded outward and clipped to
        the raster. An empty or all-NoData region uses the full terrain range.
        Palettes color elevation (and optional slope
        views); shade_strength blends hillshade into Terrain only. Gamma > 1
        brightens midtones. A known vertical-unit override affects display
        gradients only. Geographic hillshade uses local spherical meter scales
        and is illustrative; tracing still requires a projected DEM.
        """
        if style not in {'Terrain', 'Hillshade', 'Slope', 'Elevation'}:
            raise ValueError(f'Unknown display style: {style}')
        numeric = (azimuth, altitude, z_factor, shade_strength, gamma)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in numeric):
            raise ValueError('Display and lighting values must be finite numbers.')
        if z_factor <= 0 or not 0 <= altitude <= 90 or not 0 <= shade_strength <= 1 or not .1 <= gamma <= 5:
            raise ValueError('Use positive vertical exaggeration, altitude 0–90°, shade strength 0–1, and gamma 0.1–5.')
        palette = str(palette).lower()
        palette = {'terrain': 'earth', 'gray': 'grayscale'}.get(palette, palette)
        palettes = {
            'earth': [[31, 91, 112], [68, 132, 113], [133, 163, 116], [190, 184, 131], [181, 144, 103], [194, 181, 158], [240, 237, 225]],
            # The requested low-to-high terrain colors, inspired by RAS.
            # This is an independent ramp, not an official RAS color table.
            'ras': [[50, 157, 164], [163, 219, 128], [35, 110, 49], [248, 225, 76], [245, 151, 54], [206, 53, 45], [155, 155, 155], [255, 255, 255]],
            'topographic': [[46, 111, 77], [116, 166, 91], [197, 204, 126], [223, 196, 139], [174, 134, 99], [137, 124, 113], [216, 213, 205], [255, 255, 255]],
            'spectral': [[59, 79, 163], [57, 145, 185], [102, 194, 165], [171, 221, 164], [255, 255, 191], [254, 224, 139], [253, 174, 97], [244, 109, 67], [213, 62, 79], [158, 1, 66]],
            'grayscale': [[24, 24, 24], [248, 248, 248]],
            'viridis': [[68, 1, 84], [65, 68, 135], [42, 120, 142], [34, 168, 132], [122, 209, 81], [253, 231, 37]],
            'inferno': [[0, 0, 4], [66, 10, 104], [147, 38, 103], [221, 81, 58], [252, 165, 10], [252, 255, 164]],
            'ocean': [[15, 30, 66], [24, 76, 120], [35, 128, 152], [82, 175, 181], [167, 219, 208], [238, 248, 226]],
        }
        if palette not in palettes:
            raise ValueError('Choose the earth, ras, topographic, spectral, grayscale, viridis, ocean, or inferno elevation palette.')
        if stretch not in {'percentile', 'minmax', 'view', 'custom'}:
            raise ValueError('Choose percentile, minmax, view, or custom elevation stretch.')
        if stretch == 'custom':
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (low, high)) or high <= low:
                raise ValueError('Custom elevation bounds must be finite, with maximum greater than minimum.')
        override = str(vertical_units).strip().lower() if vertical_units is not None else None
        if override in ('', 'auto', 'source'):
            override = None
        vertical_m = _unit_scale(override) if override else None
        if override and vertical_m is None:
            raise ValueError('Choose meters, feet, or US survey feet for the display-only vertical-unit override.')
        clipped_view = None
        if stretch == 'view' and view_bounds is not None:
            try:
                bounds = tuple(view_bounds)
            except TypeError as exc:
                raise ValueError('Visible terrain bounds must contain four finite row/column coordinates.') from exc
            if len(bounds) != 4 or not all(isinstance(v, Real) and not isinstance(v, bool)
                                          and (isinstance(v, Integral) or math.isfinite(v)) for v in bounds):
                raise ValueError('Visible terrain bounds must contain four finite row/column coordinates.')
            r0, r1, c0, c1 = bounds
            clipped_view = (max(0, min(self.height, math.floor(r0))),
                            max(0, min(self.height, math.ceil(r1))),
                            max(0, min(self.width, math.floor(c0))),
                            max(0, min(self.width, math.ceil(c1))))
            if r1 <= r0 or c1 <= c0:
                clipped_view = (0, 0, 0, 0)
        key = (style, float(azimuth), float(altitude), float(z_factor), palette, stretch,
               low if stretch == 'custom' else None, high if stretch == 'custom' else None,
               float(shade_strength), float(gamma), bool(multidirectional), override, clipped_view)
        if key in self._render_cache:
            return self._render_cache[key]
        z = self.surface()
        sx, sy = abs(self.transform.a), abs(self.transform.e)
        if self.crs and self.crs.is_geographic:
            latitude = (self.bounds[1] + self.bounds[3]) / 2
            sx *= 111319.490793 * max(abs(math.cos(math.radians(latitude))), 1e-6)
            sy *= 111319.490793
            scale = z_factor * (vertical_m or _unit_scale(self.metadata.get('vertical_units')) or 1.)
        else:
            horizontal_m = self.crs.linear_units_factor[1] if self.crs and self.crs.is_projected else 1.
            scale = z_factor * (vertical_m / horizontal_m if vertical_m is not None else self.metadata.get('vertical_to_horizontal', 1.))
        gy, gx = np.gradient(z, sy, sx)
        gx, gy = gx * scale, -gy * scale
        alt = np.deg2rad(altitude)
        denominator = np.sqrt(1 + gx * gx + gy * gy)
        directions = [azimuth - 45, azimuth, azimuth + 45, azimuth + 90] if multidirectional else [azimuth]
        shade = np.zeros_like(z, dtype=np.float32)
        for direction in directions:
            azi = np.deg2rad(direction)
            shade += np.clip((-gx * np.sin(azi) * np.cos(alt) - gy * np.cos(azi) * np.cos(alt) + np.sin(alt)) / denominator, 0, 1)
        shade /= len(directions)
        if style == 'Hillshade':
            result = np.repeat((35 + 220 * shade)[..., None], 3, axis=2)
        elif style == 'Slope':
            slope = np.rad2deg(np.arctan(np.hypot(gx, gy)))
            slope_colors = [[31, 55, 75], [42, 127, 125], [139, 189, 108], [246, 205, 98], [227, 119, 70], [158, 54, 83]] if palette == 'earth' else palettes[palette]
            result = _colorize(np.clip(slope / 60., 0, 1), slope_colors)
        else:
            if stretch == 'custom':
                lo, hi = low, high
            elif stretch in {'minmax', 'view'}:
                lo, hi = self.metadata['min'], self.metadata['max']
                if stretch == 'view' and clipped_view is not None:
                    r0, r1, c0, c1 = clipped_view
                    visible = self.data[r0:r1, c0:c1]
                    valid = self.valid[r0:r1, c0:c1] & np.isfinite(visible)
                    if valid.any():
                        lo, hi = float(visible[valid].min()), float(visible[valid].max())
            else:
                lo, hi = np.nanpercentile(self.data, [1, 99])
            # A flat visible area has no useful range: show a stable midpoint
            # instead of amplifying numerical noise or dividing by zero.
            norm = (np.clip((z - lo) / (hi - lo), 0, 1) if hi > lo
                    else np.where(z < lo, 0., np.where(z > hi, 1., .5)))
            result = _colorize(norm, palettes[palette])
            if style == 'Terrain':
                result *= (1. - (57. / 65.) * shade_strength + shade_strength * shade[..., None])
        if gamma != 1.:
            result = 255 * np.power(np.clip(result / 255., 0, 1), 1. / gamma)
        result = np.clip(result, 0, 255).astype(np.uint8)
        result[~self.valid] = _BACKGROUND
        if len(self._render_cache) >= 4:
            self._render_cache.pop(next(iter(self._render_cache)))
        self._render_cache[key] = result
        return result


def _colorize(values, colors):
    palette = np.array(colors, dtype=np.float32)
    positions = np.linspace(0, 1, len(palette))
    return np.stack([np.interp(values, positions, palette[:, i]) for i in range(3)], axis=-1).astype(np.float32)
