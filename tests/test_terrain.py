from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin, Affine

from tracertool.terrain import Terrain


def write_dem(tmp_path, data, *, crs='EPSG:32615', transform=None, units='m'):
    path = tmp_path / 'dem.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=data.shape[1], height=data.shape[0],
                       count=1, dtype='float32', crs=crs,
                       transform=transform or from_origin(500000, 4500000, 2, 2),
                       nodata=-9999) as dst:
        dst.write(np.where(np.isfinite(data), data, -9999).astype('float32'), 1)
        if units:
            dst.set_band_unit(1, units)
    return path


def test_native_pixel_centers_and_source_samples(tmp_path):
    data = np.arange(120, dtype='float32').reshape(10, 12)
    terrain = Terrain.load(write_dem(tmp_path, data))
    assert terrain.xy(0, 0) == (500001., 4499999.)
    assert terrain.rc(*terrain.xy(4.2, 6.8)) == pytest.approx((4.2, 6.8))
    assert terrain.sample(*terrain.xy(3, 4)) == data[3, 4]
    assert terrain.sample(0, 0) is None
    assert terrain.sample(float('nan'), 0) is None
    assert terrain.metadata['original_resolution'] == 2
    assert terrain.metadata['resampled'] is False
    assert terrain.units == 'metre'


def test_downsampling_retains_source_z_and_masks_small_holes(tmp_path):
    data = np.arange(1600, dtype='float32').reshape(40, 40)
    data[9, 9] = np.nan
    terrain = Terrain.load(write_dem(tmp_path, data), max_dimension=10)
    assert terrain.data.shape == (10, 10)
    assert terrain.metadata['resampled'] is True
    assert terrain.metadata['working_resolution'] == 8
    assert not terrain.valid[2, 2]
    # A 4x4 average differs from the original pixel selected by this center.
    x, y = terrain.xy(4, 5)
    assert terrain.sample(x, y) == data[18, 22]
    assert terrain.sample(x, y) != terrain.data[4, 5]
    assert terrain.sample(500019, 4499981) is None


@pytest.mark.parametrize('style', ['Terrain', 'Hillshade', 'Slope', 'Elevation'])
def test_render_flat_nodata_and_styles(tmp_path, style):
    data = np.ones((20, 25), dtype='float32') * 10
    data[:3, :4] = np.nan
    terrain = Terrain.load(write_dem(tmp_path, data))
    rgb = terrain.rgb(style)
    assert rgb.shape == (20, 25, 3)
    assert rgb.dtype == np.uint8
    assert np.isfinite(rgb).all()
    np.testing.assert_array_equal(rgb[0, 0], [24, 30, 40])
    assert terrain.rgb(style) is rgb


def test_missing_and_geographic_crs_viewable(tmp_path):
    data = np.ones((10, 10), dtype='float32')
    for crs in (None, 'EPSG:4326'):
        terrain = Terrain.load(write_dem(tmp_path, data, crs=crs))
        assert terrain.rgb().shape == (10, 10, 3)


def test_rejects_unsupported_or_empty_inputs(tmp_path):
    data = np.ones((10, 10), dtype='float32')
    with pytest.raises(ValueError, match='Rotated'):
        Terrain.load(write_dem(tmp_path, data, transform=Affine(2, .1, 0, .2, -2, 0)))
    with pytest.raises(ValueError, match='no valid'):
        Terrain.load(write_dem(tmp_path, data * np.nan))
    with pytest.raises(ValueError, match='Cannot open'):
        Terrain.load(tmp_path / 'missing.tif')


def test_known_vertical_unit_conversion(tmp_path):
    terrain = Terrain.load(write_dem(tmp_path, np.ones((10, 10)), units='foot'))
    assert terrain.metadata['vertical_to_horizontal'] == pytest.approx(.3048)
    assert not terrain.metadata['vertical_units_assumed']


def test_band_scale_offset_applies_to_display_and_source_z(tmp_path):
    data = np.arange(1600, dtype='float32').reshape(40, 40)
    data[1, 1] = np.nan
    path = write_dem(tmp_path, data)
    with rasterio.open(path, 'r+') as source:
        source.scales = [.25]
        source.offsets = [-100.]
    terrain = Terrain.load(path)
    assert terrain.data[6, 8] == pytest.approx(data[6, 8] * .25 - 100)
    assert terrain.sample(*terrain.xy(6, 8)) == pytest.approx(data[6, 8] * .25 - 100)
    assert terrain.sample(*terrain.xy(1, 1)) is None
    assert terrain.metadata['scale_offset_applied']
    assert terrain.metadata['band_scale'] == .25
    # Both bounded-grid source sampling and the non-cached large-raster code
    # path must apply encoding exactly once.
    terrain = Terrain.load(path, max_dimension=10)
    xy = terrain.xy(4, 5)
    expected = data[18, 22] * .25 - 100
    assert terrain.sample(*xy) == pytest.approx(expected)
    terrain._source_data = None
    assert terrain.sample(*xy) == pytest.approx(expected)


def test_encoded_integer_elevations_decode_before_float32_conversion(tmp_path):
    path = tmp_path / 'precise_encoded.tif'
    raw = np.arange(300000001, 300000017, dtype=np.int32).reshape(4, 4)
    with rasterio.open(path, 'w', driver='GTiff', width=4, height=4, count=1,
                       dtype='int32', crs='EPSG:32615',
                       transform=from_origin(500000, 4500000, 1, 1)) as dst:
        dst.write(raw, 1)
        dst.scales = [.001]
        dst.offsets = [-300000.]
    terrain = Terrain.load(path)
    points = [terrain.xy(r, c) for r in range(4) for c in range(4)]
    cached = terrain.sample_many(points)
    expected = raw.astype(np.float64).ravel() * .001 - 300000.
    np.testing.assert_array_equal(cached, expected)
    assert cached[0] == pytest.approx(.001, abs=1e-10)
    assert len(set(cached)) == 16
    assert terrain._source_data.dtype == np.float64
    assert terrain.data.dtype == np.float32
    np.testing.assert_allclose(terrain.data.ravel(), expected, rtol=1e-7)
    terrain._source_data = None
    assert terrain.sample_many(points) == cached
    # The reduced display must also decode before narrowing precision.
    reduced = Terrain.load(path, max_dimension=2)
    assert np.unique(reduced.data).size == 4
    assert np.all((reduced.data > .001) & (reduced.data < .016))
    assert reduced.sample_many(points) == cached


def test_float64_source_cache_preserves_native_elevation_precision(tmp_path):
    path = tmp_path / 'precise_float.tif'
    values = np.array([[1000.0000001, 1000.0000002],
                       [1000.0000003, 1000.0000004]], dtype=np.float64)
    with rasterio.open(path, 'w', driver='GTiff', width=2, height=2, count=1,
                       dtype='float64', crs='EPSG:32615',
                       transform=from_origin(500000, 4500000, 1, 1)) as dst:
        dst.write(values, 1)
    terrain = Terrain.load(path)
    points = [terrain.xy(r, c) for r in range(2) for c in range(2)]
    assert terrain.sample_many(points) == values.ravel().tolist()
    terrain._source_data = None
    assert terrain.sample_many(points) == values.ravel().tolist()


def test_source_fingerprint_cached_opt_in_and_detects_changed_source(tmp_path):
    import hashlib
    import os
    data = np.arange(400).reshape(20, 20)
    path = write_dem(tmp_path, data)
    terrain = Terrain.load(path, compute_fingerprint=True)
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert terrain.fingerprint() == expected
    assert terrain.metadata['source_sha256'] == expected
    assert terrain.metadata['fingerprint_scope'] == 'primary raster file'
    # Hash caching is intentional: this object records the already-loaded source.
    path.rename(tmp_path / 'moved.tif')
    assert terrain.fingerprint() == expected
    path = write_dem(tmp_path, data)
    terrain = Terrain.load(path)
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
    with pytest.raises(ValueError, match='changed after loading'):
        terrain.fingerprint()


@pytest.mark.parametrize('palette', ['earth', 'ras', 'topographic', 'spectral', 'gray', 'grayscale', 'viridis', 'ocean', 'inferno', 'terrain'])
def test_render_palettes_custom_stretch_and_gamma_preserve_source(tmp_path, palette):
    rr, cc = np.mgrid[:30, :40]
    data = (rr * rr + cc * cc).astype('float32')
    terrain = Terrain.load(write_dem(tmp_path, data))
    before = terrain.data.copy()
    source_z = terrain.sample(*terrain.xy(15, 20))
    rgb = terrain.rgb('Terrain', palette=palette, stretch='custom', low=100, high=1500,
                      shade_strength=.4, gamma=1.4, multidirectional=True, vertical_units='foot')
    assert rgb.shape == (30, 40, 3)
    assert rgb.dtype == np.uint8
    np.testing.assert_array_equal(terrain.data, before)
    assert terrain.sample(*terrain.xy(15, 20)) == source_z
    assert terrain.metadata['vertical_units'] == 'm'


def test_render_controls_have_effect_and_validate_bounds(tmp_path):
    rr, cc = np.mgrid[:30, :40]
    terrain = Terrain.load(write_dem(tmp_path, (rr * rr + cc * cc).astype('float32')))
    default = terrain.rgb()
    assert np.any(default != terrain.rgb(palette='viridis'))
    assert np.any(default != terrain.rgb(gamma=1.8))
    assert np.any(default != terrain.rgb(multidirectional=True))
    assert np.any(terrain.rgb('Slope') != terrain.rgb('Slope', vertical_units='foot'))
    np.testing.assert_array_equal(terrain.rgb(shade_strength=0), terrain.rgb('Elevation'))
    for options in ({'stretch': 'custom', 'low': 5, 'high': 5}, {'gamma': 0},
                    {'shade_strength': 2}, {'vertical_units': 'furlongs'}, {'palette': 'unknown'}):
        with pytest.raises(ValueError):
            terrain.rgb(**options)
    assert len(terrain._render_cache) <= 4


def test_view_stretch_uses_visible_valid_elevations_and_preserves_source(tmp_path):
    data = np.arange(72, dtype='float32').reshape(8, 9)
    data[2, 3] = np.nan
    path = write_dem(tmp_path, data)
    terrain = Terrain.load(path)
    source_bytes = path.read_bytes()
    source_z = terrain.sample(*terrain.xy(4, 6))
    original_data = terrain.data.copy()
    bounds = (2, 5, 3, 7)  # Stops are excluded; the minimum cell is NoData.
    visible = terrain.rgb('Elevation', palette='ras', stretch='view', view_bounds=bounds)
    expected = terrain.rgb('Elevation', palette='ras', stretch='custom', low=22, high=42)
    np.testing.assert_array_equal(visible, expected)
    np.testing.assert_array_equal(visible[2, 3], [24, 30, 40])
    assert terrain.rgb('Elevation', palette='ras', stretch='view', view_bounds=bounds) is visible
    assert np.any(visible != terrain.rgb('Elevation', palette='ras', stretch='view',
                                        view_bounds=(5, 8, 3, 7)))
    np.testing.assert_array_equal(terrain.data, original_data)
    assert terrain.sample(*terrain.xy(4, 6)) == source_z
    assert path.read_bytes() == source_bytes


def test_view_stretch_rounds_outward_and_clips_raster_bounds(tmp_path):
    terrain = Terrain.load(write_dem(tmp_path, np.arange(72, dtype='float32').reshape(8, 9)))
    rgb = terrain.rgb('Elevation', stretch='view', view_bounds=(-12.2, 3.1, 6.8, 100.2))
    expected = terrain.rgb('Elevation', stretch='custom', low=6, high=35)
    np.testing.assert_array_equal(rgb, expected)
    # Clipped equivalent bounds reuse the same render.
    assert terrain.rgb('Elevation', stretch='view', view_bounds=(0, 4, 6, 9)) is rgb


@pytest.mark.parametrize('bounds', [None, (20, 30, 0, 8), (2, 2, 0, 8),
                                    (3.6, 3.1, 0, 8), (2.2, 2.2, 0, 8),
                                    (0, 2, 0, 2)])
def test_view_stretch_without_visible_valid_cells_falls_back_to_full_range(tmp_path, bounds):
    data = np.arange(72, dtype='float32').reshape(8, 9)
    data[:2, :2] = np.nan
    terrain = Terrain.load(write_dem(tmp_path, data))
    expected = terrain.rgb('Elevation', stretch='minmax')
    actual = terrain.rgb('Elevation', stretch='view', view_bounds=bounds)
    np.testing.assert_array_equal(actual, expected)


def test_view_stretch_flat_visible_area_is_stable(tmp_path):
    data = np.full((8, 9), 10., dtype='float32')
    data[0, 0], data[-1, -1] = 0, 20
    terrain = Terrain.load(write_dem(tmp_path, data))
    image = terrain.rgb('Elevation', palette='gray', stretch='view', view_bounds=(2, 6, 2, 7))
    np.testing.assert_array_equal(image[3, 4], [136, 136, 136])
    assert np.isfinite(image).all()
    assert terrain.rgb('Elevation', palette='gray', stretch='view', view_bounds=(2, 6, 2, 7)) is image


@pytest.mark.parametrize('bounds', [(0, 1, 2), (0, 1, 2, float('nan')),
                                    (0, float('inf'), 2, 3), 'abcd', 12,
                                    (0, True, 0, 2)])
def test_view_stretch_rejects_invalid_bounds(tmp_path, bounds):
    terrain = Terrain.load(write_dem(tmp_path, np.ones((8, 9), dtype='float32')))
    with pytest.raises(ValueError, match='bounds'):
        terrain.rgb(stretch='view', view_bounds=bounds)
