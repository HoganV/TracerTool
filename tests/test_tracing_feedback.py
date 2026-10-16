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


@pytest.mark.parametrize('kind,sign', [('ridge', 1), ('stream', -1)])
@pytest.mark.parametrize('short_feature_length', [1., 2., 3.])
@pytest.mark.parametrize('anomaly_row', [20, 85, 150])
def test_rough_guides_stay_on_continuing_landform_instead_of_isolated_shoulder_feature(
        tmp_path, kind, sign, short_feature_length, anomaly_row):
    rows, cols = np.mgrid[:180, :160]
    # A broad 10-unit levee/channel continues throughout the raster. A tiny
    # 0.5-unit bump/pit sits on the neighboring flat: its sharp local curvature
    # must not pull one rough guide 45 cells away from the continuous feature.
    continuous = 10 * np.clip((16 - abs(cols - 90)) / 8, 0, 1)
    isolated = .5 * np.exp(-.5 * ((cols - 45) / 1.5) ** 2)
    isolated *= np.exp(-.5 * ((rows - anomaly_row) / short_feature_length) ** 2)
    terrain = make_terrain(tmp_path, 100 + sign * (continuous + isolated))
    result = trace(terrain, [(20, 72), (85, 72), (150, 72)], kind, TraceParams(corridor=30))
    cells = np.asarray(result.cells)
    assert np.max(abs(cells[:, 1] - 90)) <= 1
    assert result.cells[0] == [20, 90] and result.cells[-1] == [150, 90]
    assert result.metrics['relaxed_guide_count'] == 3
    assert result.metrics['length'] == pytest.approx(130, abs=1)
    assert result.metrics['spacing_median_pixels'] >= 2.9
    assert result.metrics['spacing_max_pixels'] <= 3 + 1e-8
    # The original elevations remain intact; a constant-height crest or
    # channel floor must not develop an endpoint climb/drop into the shoulder.
    assert np.ptp(np.asarray(result.coordinates)[:, 2]) < .01
    validate_segments(terrain, result.coordinates)


@pytest.mark.parametrize('kind,sign', [('ridge', -1), ('stream', 1)])
@pytest.mark.parametrize('first,last', [(0, 99), (3, 96)])
def test_longitudinal_evidence_can_be_one_sided_at_raster_edges(tmp_path, kind, sign, first, last):
    rows, cols = np.mgrid[:100, :100]
    terrain = make_terrain(tmp_path, sign * (cols - 50) ** 2 / 8 + (100 - rows) * .1)
    result = trace(terrain, [(first, 58), (last, 58)], kind)
    assert result.cells[0][0] == first and result.cells[-1][0] == last
    if kind == 'stream':  # Exact regression reported for the parabolic valley.
        assert result.cells[0] == [first, 50]
        assert result.cells[-1] == [last, 50]
    assert result.metrics['relaxed_guide_count'] == 2
    assert max(abs(col - 50) for row, col in result.cells) <= 1
    validate_segments(terrain, result.coordinates)


@pytest.mark.parametrize('kind,sign', [('ridge', -1), ('stream', 1)])
def test_longitudinal_evidence_uses_valid_side_beside_nodata(tmp_path, kind, sign):
    rows, cols = np.mgrid[:100, :100]
    data = sign * (cols - 50) ** 2 / 8 + (100 - rows) * .1
    # Valid terrain beyond these thin barriers must not be included in a
    # candidate's longitudinal support on the other side of the gap.
    data[[2, 97], :] = np.nan
    terrain = make_terrain(tmp_path, data)
    result = trace(terrain, [(3, 58), (96, 58)], kind)
    assert result.cells[0][0] == 3 and result.cells[-1][0] == 96
    if kind == 'stream':
        assert result.cells[0] == [3, 50]
        assert result.cells[-1] == [96, 50]
    assert result.metrics['relaxed_guide_count'] == 2
    assert max(abs(col - 50) for row, col in result.cells) <= 1
    validate_segments(terrain, result.coordinates)


@pytest.mark.parametrize('disconnected_cost', [0., 1000.])
def test_longitudinal_score_cannot_average_through_nodata_gaps(disconnected_cost):
    from tracertool.tracing import _profile_support_cost
    mask = np.ones((17, 7), dtype=bool)
    mask[[4, 8], :] = False
    cost = np.full(mask.shape, disconnected_cost)
    cost[5:8, :] = 5
    cost[~mask] = np.inf
    score = _profile_support_cost(cost, mask, [[6, 3]], np.array([1., 0.]), np.arange(-5., 6.))
    assert score.tolist() == [5.]


def test_longitudinal_score_stops_at_nodata_corner_even_when_probe_cells_are_valid():
    from tracertool.tracing import _profile_support_cost
    mask = np.ones((11, 11), dtype=bool)
    mask[5, 6] = False
    cost = np.full(mask.shape, 7.)
    cost[6:, 6:] = 0
    cost[~mask] = np.inf
    # The diagonal probe centers all land in valid cells. The segment toward
    # their attractive zero-cost region touches the missing cell's corner.
    score = _profile_support_cost(cost, mask, [[5, 5]], np.array([1., 1.]) / math.sqrt(2),
                                  np.arange(-4., 5.))
    assert score.tolist() == [7.]


@pytest.mark.parametrize('radius', [float('inf'), float('nan'), -1., 0.])
def test_unbounded_radius_still_rejects_invalid_values(tmp_path, radius):
    terrain = make_terrain(tmp_path, np.zeros((40, 40)))
    with pytest.raises(ValueError, match='finite|at least 1'):
        trace(terrain, [(5, 5), (35, 35)], 'stream', TraceParams(corridor=radius))
