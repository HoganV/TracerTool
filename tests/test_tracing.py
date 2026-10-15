import json
import math
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from tracertool.terrain import Terrain
from tracertool.tracing import TraceParams, trace, trace_downstream, _segment_cells


def dem(tmp_path, data, crs='EPSG:32615'):
    path = tmp_path / 'trace.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=data.shape[1], height=data.shape[0],
                       count=1, dtype='float32', crs=crs,
                       transform=from_origin(500000, 4500000, 1, 1), nodata=-9999) as dst:
        dst.write(np.where(np.isfinite(data), data, -9999).astype('float32'), 1)
        dst.set_band_unit(1, 'm')
    return Terrain.load(path)


@pytest.mark.parametrize('kind,sign', [('stream', 1), ('ridge', -1)])
def test_follows_curving_valley_or_ridge(tmp_path, kind, sign):
    rr, cc = np.mgrid[:120, :120]
    center = 60 + 10 * np.sin((rr - 10) * np.pi / 100)
    data = sign * ((cc - center) ** 2 / 8) + (120 - rr) * .1
    terrain = dem(tmp_path, data)
    result = trace(terrain, [(10, 60), (110, 60)], kind, TraceParams(corridor=22))
    cells = np.array(result.cells)
    expected = 60 + 10 * np.sin((cells[:, 0] - 10) * np.pi / 100)
    assert np.mean(abs(cells[:, 1] - expected)) < 2.5
    assert cells[0].tolist() == [10, 60]
    assert cells[-1].tolist() == [110, 60]
    assert np.linalg.norm(np.diff(cells, axis=0), axis=1).max() <= TraceParams().spacing + 1e-6
    assert result.coordinates[0][:2] == list(terrain.xy(10, 60))
    assert result.coordinates[0][2] == terrain.sample(*terrain.xy(10, 60))
    json.dumps(result.metrics, allow_nan=False)


def test_slope_break_tracks_change_in_slope(tmp_path):
    rr, cc = np.mgrid[:100, :100]
    edge = 45 + 8 * np.sin((rr - 10) * np.pi / 80)
    data = np.maximum(0, cc - edge) * 4
    terrain = dem(tmp_path, data)
    result = trace(terrain, [(10, 45), (90, 45)], 'slope_break', TraceParams(corridor=20))
    cells = np.array(result.cells)
    expected = 45 + 8 * np.sin((cells[:, 0] - 10) * np.pi / 80)
    assert np.mean(abs(cells[:, 1] - expected)) < 3


def test_routes_around_nodata_and_simplification_cannot_cross(tmp_path):
    data = np.zeros((60, 60))
    data[22:38, 28:32] = np.nan
    terrain = dem(tmp_path, data)
    result = trace(terrain, [(30, 10), (30, 50)], 'stream',
                   TraceParams(corridor=18, simplify=15, spacing=20))
    for a, b in zip(result.cells[:-1], result.cells[1:]):
        assert all(terrain.valid[r, c] for r, c in _segment_cells(a, b))
    assert max(abs(r - 30) for r, c in result.cells) >= 8
    with pytest.raises(ValueError, match='NoData'):
        trace(terrain, [(30, 10), (30, 50)], 'manual')


def test_impenetrable_barrier_and_diagonal_corner(tmp_path):
    data = np.zeros((30, 30))
    data[:, 15] = np.nan
    terrain = dem(tmp_path, data)
    with pytest.raises(ValueError, match='No valid route'):
        trace(terrain, [(15, 5), (15, 25)], 'ridge')
    data = np.full((4, 4), np.nan)
    data[1, 1] = data[2, 2] = 0
    terrain = dem(tmp_path, data)
    with pytest.raises(ValueError, match='No valid route'):
        trace(terrain, [(1, 1), (2, 2)], 'stream')


def test_retains_all_anchors_manual_spacing_and_z(tmp_path):
    data = np.arange(2500).reshape(50, 50)
    terrain = dem(tmp_path, data)
    anchors = [(5, 5), (20, 30), (40, 10)]
    result = trace(terrain, anchors, 'manual', TraceParams(spacing=4))
    for anchor in anchors:
        assert list(anchor) in result.cells
    cells = np.array(result.cells)
    assert np.linalg.norm(np.diff(cells, axis=0), axis=1).max() <= 4.000001
    for x, y, z in result.coordinates:
        assert z == terrain.sample(x, y)
    assert result.metrics['length'] == pytest.approx(math.hypot(15, 25) + math.hypot(20, 20))


def test_validates_crs_anchors_and_parameters(tmp_path):
    terrain = dem(tmp_path, np.zeros((20, 20)), crs='EPSG:4326')
    with pytest.raises(ValueError, match='projected'):
        trace(terrain, [(2, 2), (10, 10)], 'stream')
    terrain = dem(tmp_path, np.zeros((20, 20)))
    for params in (TraceParams(spacing=0), TraceParams(smoothing=-1), TraceParams(corridor=float('nan'))):
        with pytest.raises(ValueError):
            trace(terrain, [(2, 2), (10, 10)], 'stream', params)
    with pytest.raises(ValueError, match='outside'):
        trace(terrain, [(-2, 2), (10, 10)], 'ridge')
    with pytest.raises(ValueError, match='different'):
        trace(terrain, [(2, 2), (2, 2)], 'ridge')


def test_uphill_stream_warning(tmp_path):
    data = np.tile(np.arange(40), (40, 1))
    result = trace(dem(tmp_path, data), [(20, 5), (20, 35)], 'stream')
    assert any('uphill' in message for message in result.warnings)
    assert result.metrics['elevation_gain'] > 0


def test_downhill_descent_stops_at_edge_and_pit(tmp_path):
    rr, cc = np.mgrid[:40, :40]
    terrain = dem(tmp_path, 100 - rr + (cc - 20) ** 2)
    result = trace_downstream(terrain, (5, 20), TraceParams(smoothing=0))
    assert result.cells[-1] == [39, 20]
    assert result.metrics['elevation_gain'] == 0
    assert any('edge' in message for message in result.warnings)
    terrain = dem(tmp_path, (rr - 20) ** 2 + (cc - 20) ** 2)
    with pytest.raises(ValueError, match='pit'):
        trace_downstream(terrain, (20, 20))


def test_corridor_is_hard_limit(tmp_path):
    rr, cc = np.mgrid[:60, :60]
    terrain = dem(tmp_path, -100 * np.exp(-((cc - 42) ** 2) / 8) + 0. * rr)
    result = trace(terrain, [(5, 30), (55, 30)], 'stream', TraceParams(corridor=5))
    assert all(abs(c - 30) <= 5 for r, c in result.cells)


def test_edited_segments_exactly_check_holes_and_corners(tmp_path):
    from tracertool.tracing import validate_segments
    data = np.zeros((40, 40))
    data[20, 20] = np.nan
    terrain = dem(tmp_path, data)
    # Endpoints are valid, but one intervening pixel is not.
    with pytest.raises(ValueError, match='crosses NoData'):
        validate_segments(terrain, [terrain.xy(20, 5), terrain.xy(20, 35)])
    # Touching a missing cell only at its corner is also disallowed.
    with pytest.raises(ValueError, match='crosses NoData'):
        validate_segments(terrain, [terrain.xy(19, 20), terrain.xy(20, 19)])
    assert validate_segments(terrain, [terrain.xy(18, 5), terrain.xy(18, 35)]) is None
    with pytest.raises(ValueError, match='finite'):
        validate_segments(terrain, [(float('nan'), 10), (20, 20)])


def test_rectangular_pixels_preserve_native_distance_and_disclose_controls(tmp_path):
    path = tmp_path / 'rectangular.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=30, height=30,
                       count=1, dtype='float32', crs='EPSG:32615',
                       transform=from_origin(500000, 4500000, 2, 5)) as dst:
        dst.write(np.zeros((30, 30), dtype='float32'), 1)
        dst.set_band_unit(1, 'm')
    terrain = Terrain.load(path)
    result = trace(terrain, [(5, 5), (15, 5)], 'stream')
    assert result.metrics['length'] == pytest.approx(50)
    assert result.metrics['corridor_map_units_xy'] == [60, 150]
    assert any('rectangular pixels' in warning for warning in result.warnings)


def test_trace_retains_native_guide_anchors_and_cancels( tmp_path):
    from tracertool.tracing import TraceCancelled
    terrain = dem(tmp_path, np.zeros((40, 40)))
    result = trace(terrain, [(5.2, 5.1), (20.1, 18.2), (35, 30)], 'manual')
    assert result.anchors == [list(terrain.xy(5.2, 5.1)), list(terrain.xy(20.1, 18.2)), list(terrain.xy(35, 30))]
    with pytest.raises(TraceCancelled, match='cancelled'):
        trace(terrain, [(5, 5), (35, 35)], 'stream', cancel=lambda: True)
    calls = [0]
    def cancel_during_work():
        calls[0] += 1
        return calls[0] >= 6
    with pytest.raises(TraceCancelled):
        trace(terrain, [(5, 5), (35, 35)], 'stream', cancel=cancel_during_work)
    assert calls[0] == 6


def test_manual_distinct_subcell_anchors_and_repeated_cells_preserved(tmp_path):
    terrain = dem(tmp_path, np.arange(1600).reshape(40, 40))
    points = [(5.1, 5.1), (5.4, 5.4)]
    result = trace(terrain, points, 'manual', TraceParams(spacing=30))
    assert result.cells == [list(p) for p in points]
    assert result.anchors == [list(terrain.xy(*p)) for p in points]
    repeated = [(5.1, 5.1), (10.2, 10.2), (5.4, 5.4)]
    result = trace(terrain, repeated, 'manual', TraceParams(spacing=30))
    assert result.cells == [list(p) for p in repeated]
    assert [p[:2] for p in result.coordinates] == [list(terrain.xy(*p)) for p in repeated]
    for x, y, z in result.coordinates:
        assert z == terrain.sample(x, y)
