"""Synthetic native-grid calibration and safety checks."""
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from tracertool.terrain import Terrain


def make_terrain(tmp_path, values, *, pixel=(2, 5), unit='foot', scale=.25,
                 offset=100., max_dimension=12):
    path = tmp_path / 'native.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=values.shape[1],
                       height=values.shape[0], count=1, dtype='float64',
                       crs='EPSG:32615', transform=from_origin(500000, 4500000, *pixel),
                       nodata=-9999) as dst:
        dst.write(np.where(np.isfinite(values), values, -9999), 1)
        dst.scales = [scale]
        dst.offsets = [offset]
        dst.set_band_unit(1, unit)
    return Terrain.load(path, max_dimension=max_dimension)


def test_native_window_decodes_source_not_display_with_rectangular_feet(tmp_path):
    from tracertool.analysis_grid import read_grid
    raw = np.arange(1200, dtype=float).reshape(30, 40)
    raw[8, 9] = np.nan
    terrain = make_terrain(tmp_path, raw)
    grid = read_grid(terrain, (4, 14, 5, 20), max_cells=1000)
    assert grid.data.shape == (10, 15)
    np.testing.assert_array_equal(grid.data, raw[4:14, 5:20] * .25 + 100)
    assert grid.data.dtype == np.float64
    assert grid.resolution_xy == (2., 5.)
    assert grid.vertical_to_horizontal == pytest.approx(.3048)
    assert grid.xy(0, 0) == pytest.approx((500011, 4499977.5))
    assert grid.rc(*grid.xy(3.2, 6.1)) == pytest.approx((3.2, 6.1))
    assert not grid.valid[4, 4]
    assert grid.source_identity['size'] == terrain.metadata['source_size']


def test_window_budget_invalid_bounds_cancel_and_source_change(tmp_path):
    from tracertool.analysis_grid import read_grid
    from tracertool.tracing import TraceCancelled
    import os
    terrain = make_terrain(tmp_path, np.ones((30, 40)))
    with pytest.raises(ValueError, match='memory budget'):
        read_grid(terrain, max_cells=10)
    with pytest.raises(ValueError, match='outside'):
        read_grid(terrain, (-1, 10, 0, 10))
    with pytest.raises(ValueError, match='integer'):
        read_grid(terrain, (0., 10, 0, 10))
    with pytest.raises(TraceCancelled):
        read_grid(terrain, cancel=lambda: True)
    stat = os.stat(terrain.path)
    os.utime(terrain.path, ns=(stat.st_atime_ns, stat.st_mtime_ns+1000000))
    with pytest.raises(ValueError, match='changed after loading'):
        read_grid(terrain)


def test_mask_only_source_gap_never_decoded_as_height(tmp_path):
    from tracertool.analysis_grid import read_grid
    terrain = make_terrain(tmp_path, np.ones((20, 20)))
    with rasterio.open(terrain.path, 'r+') as src:
        mask = np.full((20, 20), 255, dtype=np.uint8)
        mask[8, 9] = 0
        src.write_mask(mask)
    # Reload source identity because writing a mask may update the primary file.
    terrain = Terrain.load(terrain.path)
    grid = read_grid(terrain)
    assert not grid.valid[8, 9]
    assert np.isnan(grid.data[8, 9])


def test_external_mask_change_invalidates_analysis_identity(tmp_path):
    from tracertool.analysis_grid import read_grid, check_source_identity
    from pathlib import Path
    terrain = make_terrain(tmp_path, np.ones((20, 20)))
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(terrain.path, 'r+') as src:
            src.write_mask(np.full((20, 20), 255, dtype=np.uint8))
    terrain = Terrain.load(terrain.path)
    grid = read_grid(terrain)
    primary = Path(terrain.path).stat()
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(terrain.path, 'r+') as src:
            mask = np.full((20, 20), 255, dtype=np.uint8)
            mask[10, 10] = 0
            src.write_mask(mask)
    assert Path(terrain.path).stat().st_mtime_ns == primary.st_mtime_ns
    with pytest.raises(ValueError, match='Source changed'):
        check_source_identity(grid.source_identity)


def test_load_snapshot_is_rechecked_after_native_read(tmp_path, monkeypatch):
    import tracertool.analysis_grid as analysis
    import os
    terrain = make_terrain(tmp_path, np.ones((20, 20)))
    original_check = analysis.check_source_identity
    def checked_then_changed(identity):
        original_check(identity)
        stat = os.stat(terrain.path)
        os.utime(terrain.path, ns=(stat.st_atime_ns, stat.st_mtime_ns+1000000))
    monkeypatch.setattr(analysis, 'check_source_identity', checked_then_changed)
    with pytest.raises(ValueError, match='Source changed'):
        analysis.read_grid(terrain)


def test_load_time_external_dependency_change_is_rejected_before_fresh_read(tmp_path):
    from tracertool.analysis_grid import read_grid
    from pathlib import Path
    import os
    terrain = make_terrain(tmp_path, np.ones((20, 20)))
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(terrain.path, 'r+') as src:
            src.write_mask(np.full((20, 20), 255, dtype=np.uint8))
    terrain = Terrain.load(terrain.path)
    dependency = Path(str(terrain.path)+'.msk')
    stat = dependency.stat()
    os.utime(dependency, ns=(stat.st_atime_ns, stat.st_mtime_ns+1000000))
    with pytest.raises(ValueError, match='Source changed.*dependency'):
        read_grid(terrain)


def test_analysis_only_noise_scale_pit_fill_preserves_source_and_units(tmp_path):
    from tracertool.analysis_grid import read_grid, condition_small_pits
    rr, cc = np.mgrid[:80, :80]
    z = (80-rr)*.01 + (cc-40.)**2
    z += np.random.default_rng(42).normal(0, .02, z.shape)
    z[:, 40] = (80-np.arange(80))*.01
    z[40, 40] = z[41, 40]-.01
    terrain = make_terrain(tmp_path, z, scale=1., offset=0., unit='unspecified')
    original = read_grid(terrain)
    derived, info = condition_small_pits(original)
    assert derived.data[40, 40] == z[41, 40]
    assert info['depth_limit_source_units'] > .01
    assert info['changed_cells'] >= 1
    assert info['max_changed_depth_source_units'] <= info['depth_limit_source_units']
    assert derived.vertical_to_horizontal is None
    np.testing.assert_array_equal(original.data, z)
    np.testing.assert_array_equal(derived.valid, original.valid)
    pit = next(p for p in info['pits'] if p['native_cell'] == [40, 40])
    assert pit['decision'] == 'bounded_noise_scale_fill'
    assert pit['max_depth_source_units'] == pytest.approx(.01)


def test_conditioning_retains_deep_and_wide_depressions_and_is_unit_equivariant(tmp_path):
    from tracertool.analysis_grid import read_grid, condition_small_pits
    from dataclasses import replace
    rr, cc = np.mgrid[:80, :80]
    z = (80-rr)*.01+(cc-40.)**2
    z += np.random.default_rng(42).normal(0, .02, z.shape)
    z[:, 40] = (80-np.arange(80))*.01
    z[20, 40] -= 1.
    z[35:46, 38:43] = .32  # wide closed flat: cannot chip-fill it in stages
    grid = read_grid(make_terrain(tmp_path, z, scale=1., offset=0.))
    derived, info = condition_small_pits(grid)
    assert derived.data[20, 40] == z[20, 40]
    np.testing.assert_array_equal(derived.data[35:46, 38:43], z[35:46, 38:43])
    converted = replace(grid, data=grid.data*3.28084+120.)
    converted_derived, converted_info = condition_small_pits(converted)
    np.testing.assert_allclose(converted_derived.data, derived.data*3.28084+120.)
    assert [p['decision'] for p in info['pits']] == [p['decision'] for p in converted_info['pits']]
    assert converted_info['depth_limit_source_units'] == pytest.approx(info['depth_limit_source_units']*3.28084)


def test_conditioning_never_fills_nodata_or_connects_across_hole(tmp_path):
    from tracertool.analysis_grid import read_grid, condition_small_pits
    z = np.full((20, 20), 10.)
    z[5:15, 10] = np.nan
    z[8, 9] = 1.
    grid = read_grid(make_terrain(tmp_path, z, scale=1., offset=0.))
    derived, info = condition_small_pits(grid)
    np.testing.assert_array_equal(derived.valid, grid.valid)
    assert np.isnan(derived.data[5:15, 10]).all()
    assert derived.data[8, 9] == 1.  # missing outlet stays unknown, not filled


def test_unknown_vertical_unit_is_not_reported_as_unit_conversion(tmp_path):
    from tracertool.analysis_grid import read_grid
    terrain = make_terrain(tmp_path, np.ones((20, 20)), unit='unspecified')
    grid = read_grid(terrain)
    assert grid.vertical_to_horizontal is None
