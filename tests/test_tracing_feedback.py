"""New-draft acceptance on synthetic terrain, without private reference data.

These checks measure feature error in cells, not survey or hydrologic accuracy.
The optional historical smoothing checks remain in test_quality.py.
"""
from dataclasses import replace
import json
import math

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from tracertool.terrain import Terrain
from tracertool.tracing import (
    TraceParams, default_params, trace, trace_downstream, validate_segments,
)


def make_terrain(tmp_path, data, *, resolution=1., crs='EPSG:32615', units='m', name='feedback'):
    path = tmp_path / f'{name}.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=data.shape[1], height=data.shape[0],
                       count=1, dtype='float32', crs=crs, nodata=-9999,
                       transform=from_origin(500000, 4500000, resolution, resolution)) as dst:
        dst.write(np.where(np.isfinite(data), data, -9999).astype('float32'), 1)
        dst.set_band_unit(1, units)
    # Preserve the deliberately wide allocation test's full synthetic grid.
    return Terrain.load(path, max_dimension=max(data.shape))


def curved_feature(kind):
    rows, cols = np.mgrid[:180, :150]
    center = 70 + 6 * np.sin((rows - 20) * np.pi / 140)
    if kind == 'slope_break':
        data = np.maximum(0, cols - center) * 4
    else:
        data = (cols - center) ** 2 / 8 * (1 if kind == 'stream' else -1)
    return data + (180 - rows) * .1


@pytest.mark.parametrize('kind', ['stream', 'ridge', 'slope_break'])
@pytest.mark.parametrize('resolution,crs,units', [(1., 'EPSG:2277', 'ft'), (30., 'EPSG:32615', 'm')])
def test_default_rough_guides_find_curved_feature_at_fine_and_coarse_resolutions(
        tmp_path, kind, resolution, crs, units):
    terrain = make_terrain(tmp_path, curved_feature(kind), resolution=resolution, crs=crs, units=units)
    rough = [(20, 78), (90, 84), (160, 78)]  # All three guides miss the feature by eight cells.
    params = default_params(terrain, kind)
    fixed = trace(terrain, rough, kind, replace(params, relax_anchors=False))
    result = trace(terrain, rough, kind)
    cells, fixed_cells = np.asarray(result.cells), np.asarray(fixed.cells)
    error = abs(cells[:, 1] - (70 + 6 * np.sin((cells[:, 0] - 20) * np.pi / 140)))
    fixed_error = abs(fixed_cells[:, 1] - (70 + 6 * np.sin((fixed_cells[:, 0] - 20) * np.pi / 140)))
    assert error.mean() < .5
    assert error.max() <= 1.1
    assert error.mean() < fixed_error.mean() * .35
    assert result.metrics['relaxed_guide_count'] == 3
    assert result.metrics['guide_displacement_max_pixels'] <= params.corridor
    assert result.cells[0] != list(rough[0]) and result.cells[-1] != list(rough[-1])
    assert result.anchors == [list(terrain.xy(*point)) for point in rough]
    assert result.metrics['spacing_median_pixels'] > 2.8
    assert result.metrics['spacing_max_pixels'] <= 3 + 1e-8
    assert result.metrics['corridor_map_units'] == 12 * resolution
    assert result.metrics['working_resolution'] == resolution
    assert result.metrics['vertical_units'] == units
    assert params.smoothing == params.line_smoothing == 0
    assert params.spacing * terrain.resolution == 3 * resolution
    assert params.simplify * terrain.resolution == .75 * resolution
    for x, y, z in result.coordinates:
        assert z == terrain.sample(x, y)
    validate_segments(terrain, result.coordinates)
    json.dumps(result.metrics, allow_nan=False)


@pytest.mark.parametrize('kind', ['stream', 'ridge'])
def test_search_radius_does_not_override_small_spacing_or_blur_narrow_feature(tmp_path, kind):
    rows, cols = np.mgrid[:220, :180]
    data = 100 + (1 if kind == 'ridge' else -1) * 12 * np.exp(-.5 * ((cols - 90) / 3) ** 2)
    data += .01 * (220 - rows)
    terrain = make_terrain(tmp_path, data)
    counts = []
    for radius in (12., 50., 300., 2501., 1e200):
        with np.errstate(over='raise', invalid='raise'):
            result = trace(terrain, [(20, 98), (200, 98)], kind, TraceParams(corridor=radius))
        cells = np.asarray(result.cells)
        assert np.max(abs(cells[:, 1] - 90)) <= 1
        assert 2.9 <= result.metrics['spacing_median_pixels'] <= 3
        assert result.metrics['spacing_max_pixels'] <= 3 + 1e-8
        assert result.metrics['target_spacing_pixels'] == 3
        assert result.metrics['corridor_map_units'] == radius
        assert result.metrics['spacing_long_edge_count'] == 0
        counts.append(len(cells))
        validate_segments(terrain, result.coordinates)
        json.dumps(result.metrics, allow_nan=False)
    assert max(counts) - min(counts) <= 1


@pytest.mark.parametrize('relax', [False, True])
def test_extreme_search_radius_covers_raster_without_radius_sized_allocation(tmp_path, monkeypatch, relax):
    import tracertool.tracing as tracing
    terrain = make_terrain(tmp_path, np.zeros((40, 2600)))
    real_cost = tracing._cost
    windows = []
    def inspect_cost(terrain, bounds, *args, **kwargs):
        windows.append(bounds)
        r0, r1, c0, c1 = bounds
        assert 0 <= r0 < r1 <= terrain.height
        assert 0 <= c0 < c1 <= terrain.width
        return real_cost(terrain, bounds, *args, **kwargs)
    monkeypatch.setattr(tracing, '_cost', inspect_cost)
    with np.errstate(over='raise', invalid='raise'):
        result = trace(terrain, [(5, 5), (35, 5)], 'stream',
                       TraceParams(corridor=1e200, relax_anchors=relax))
    # Both former 250-cell UI and 2,000-cell core limits are surpassed. The
    # search window stops at the raster, not at a hidden parameter maximum.
    assert (0, 40, 0, 2600) in windows
    assert result.cells[0] == [5, 5] and result.cells[-1] == [35, 5]
    assert result.metrics['length'] == pytest.approx(30)
    assert result.metrics['corridor_map_units'] == 1e200
    json.dumps(result.metrics, allow_nan=False)


@pytest.mark.parametrize('kind', ['stream', 'ridge', 'slope_break'])
def test_flat_ground_keeps_guides_and_dense_guides_do_not_restart_spacing(tmp_path, kind):
    terrain = make_terrain(tmp_path, np.zeros((130, 100)))
    sparse = trace(terrain, [(10, 50), (110, 50)], kind)
    dense = trace(terrain, [(10, 50), (25, 50), (45, 50), (70, 50), (110, 50)], kind)
    assert dense.cells == sparse.cells
    assert len(dense.cells) == math.ceil(100 / 3) + 1
    assert all(col == 50 for row, col in dense.cells)
    assert dense.metrics['relaxed_guide_count'] == 0
    assert dense.metrics['spacing_exception_count'] == 0
    assert dense.metrics['spacing_min_pixels'] == pytest.approx(100 / 34)


@pytest.mark.parametrize('fixed_indices', [[0, 2], [1]])
def test_explicit_fixed_connections_survive_relaxation_and_final_resampling(tmp_path, fixed_indices):
    rows, cols = np.mgrid[:180, :140]
    terrain = make_terrain(tmp_path, (cols - 70) ** 2 / 8 + (180 - rows) * .1)
    guides = [(20, 78), (90, 78), (160, 78)]
    result = trace(terrain, guides, 'stream', TraceParams(spacing=3.7),
                   fixed_anchor_indices=fixed_indices)
    for index in fixed_indices:
        assert list(guides[index]) in result.cells
        xyz = next(point for point in result.coordinates if point[:2] == list(terrain.xy(*guides[index])))
        assert xyz[2] == terrain.sample(*xyz[:2])
    assert result.fixed_anchor_indices == fixed_indices
    assert result.metrics['fixed_anchor_indices'] == fixed_indices
    assert result.metrics['relaxed_guide_count'] == 3 - len(fixed_indices)
    assert result.metrics['spacing_max_pixels'] <= 3.7 + 1e-8
    validate_segments(terrain, result.coordinates)


def test_explicit_fixed_connection_indices_follow_consolidated_adjacent_guides(tmp_path):
    rows, cols = np.mgrid[:180, :140]
    terrain = make_terrain(tmp_path, (cols - 70) ** 2 / 8 + .1 * rows)
    guides = [(20, 78), (20.1, 78.1), (90, 78), (160, 78)]
    result = trace(terrain, guides, 'stream', fixed_anchor_indices=[1, 3])
    assert len(result.anchors) == 3
    assert result.fixed_anchor_indices == [0, 2]
    assert result.cells[0] == [20, 78] and result.cells[-1] == [160, 78]
    legacy = trace(terrain, guides, 'stream', TraceParams(relax_anchors=False))
    assert legacy.fixed_anchor_indices == []  # The parameter already fixes all guides.


def test_core_fixed_connections_roundtrip_without_ui_metadata(tmp_path):
    from tracertool.project import new_feature, save_project, load_project
    rows, cols = np.mgrid[:100, :100]
    terrain = make_terrain(tmp_path, (cols - 50) ** 2 / 8 + .1 * rows)
    params = default_params(terrain)
    result = trace(terrain, [(10, 58), (50, 58), (90, 58)], 'stream', params,
                   fixed_anchor_indices=[0, 2])
    feature = new_feature('Fixed connections', 'stream', result, params)
    destination = tmp_path / 'connections.tracer.json'
    save_project(destination, terrain.path, [feature], {})
    loaded = load_project(destination)['features'][0]
    assert loaded['fixed_anchor_indices'] == [0, 2]
    assert loaded['anchors'] == result.anchors
    assert loaded['coordinates'] == result.coordinates


@pytest.mark.parametrize('index', [True, -1, 3, 1.5, float('nan'), '1'])
def test_fixed_connection_indices_are_validated(tmp_path, index):
    terrain = make_terrain(tmp_path, np.zeros((40, 40)))
    with pytest.raises(ValueError, match='Fixed anchor indices'):
        trace(terrain, [(5, 5), (20, 20), (35, 35)], 'stream', fixed_anchor_indices=[index])


@pytest.mark.parametrize('kind', ['stream', 'ridge', 'slope_break'])
def test_isolated_pit_does_not_push_guides_across_otherwise_flat_ground(tmp_path, kind):
    data = np.zeros((120, 120))
    data[60, 65] = -100
    terrain = make_terrain(tmp_path, data)
    result = trace(terrain, [(20, 50), (60, 50), (100, 50)], kind)
    assert result.metrics['relaxed_guide_count'] == 0
    assert all(col == 50 for row, col in result.cells)
    assert all(point[2] == 0 for point in result.coordinates)


def test_slope_break_does_not_move_guides_to_arbitrary_parabolic_shoulders(tmp_path):
    rows, cols = np.mgrid[:120, :120]
    terrain = make_terrain(tmp_path, (cols - 60) ** 2 * .2 + (120 - rows) * .1)
    result = trace(terrain, [(20, 60), (60, 60), (100, 60)], 'slope_break')
    # This continuous parabola has no discrete bank. The route can follow a
    # local slope-change shoulder, but it must not relocate rough endpoints
    # on the strength of a monotonic response with no located feature peak.
    assert result.metrics['relaxed_guide_count'] == 0
    assert result.cells[0] == [20, 60] and result.cells[-1] == [100, 60]
    assert max(abs(col - 60) for row, col in result.cells) <= 3
    validate_segments(terrain, result.coordinates)


def test_guide_relaxation_cannot_jump_across_nodata_to_better_feature(tmp_path):
    rows, cols = np.mgrid[:120, :120]
    data = (cols - 60) ** 2 / 8 + (120 - rows) * .1
    data[:, 55] = np.nan
    terrain = make_terrain(tmp_path, data)
    result = trace(terrain, [(20, 50), (60, 50), (100, 50)], 'stream')
    assert all(col < 55 for row, col in result.cells)
    validate_segments(terrain, result.coordinates)
    with pytest.raises(ValueError, match='No valid route'):
        trace(terrain, [(20, 50), (100, 60)], 'stream', TraceParams(corridor=1e200))


def test_default_stream_preserves_real_pit_and_warns_about_uphill_exit(tmp_path):
    rows, cols = np.mgrid[:120, :120]
    terrain = make_terrain(tmp_path, (rows - 60) ** 2 + (cols - 60) ** 2)
    guided = trace(terrain, [(20, 68), (60, 68), (100, 68)], 'stream')
    assert guided.metrics['elevation_gain'] > 1500
    assert any('uphill' in message for message in guided.warnings)
    for x, y, z in guided.coordinates:
        assert z == terrain.sample(x, y)
    downhill = trace_downstream(terrain, (20, 68))
    assert downhill.cells[-1] == [60, 60]
    assert downhill.coordinates[-1][2] == 0
    assert downhill.metrics['elevation_gain'] == 0
    assert any('pit or flat' in message for message in downhill.warnings)


@pytest.mark.parametrize('radius', [float('inf'), float('nan'), -1., 0.])
def test_unbounded_radius_still_rejects_invalid_values(tmp_path, radius):
    terrain = make_terrain(tmp_path, np.zeros((40, 40)))
    with pytest.raises(ValueError, match='finite|at least 1'):
        trace(terrain, [(5, 5), (35, 35)], 'stream', TraceParams(corridor=radius))
