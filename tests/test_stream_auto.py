"""Experimental reach solver tests: synthetic evidence, never validation claims."""
import json
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from tracertool.terrain import Terrain
from tracertool.tracing import TraceParams


def terrain_from(tmp_path, data, *, max_dimension=2400, pixel=(1, 1),
                 unit='m', scale=1., offset=0.):
    path = tmp_path / 'stream.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=data.shape[1],
                       height=data.shape[0], count=1, dtype='float64',
                       crs='EPSG:32615', transform=from_origin(500000, 4500000, *pixel),
                       nodata=-9999) as dst:
        dst.write(np.where(np.isfinite(data), data, -9999), 1)
        dst.scales = [scale]
        dst.offsets = [offset]
        dst.set_band_unit(1, unit)
    return Terrain.load(path, max_dimension=max_dimension)


def test_native_global_reach_follows_meander_outside_legacy_corridor(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:140, :140]
    center = 60 + 30 * np.sin((rr - 10) * np.pi / 120)
    terrain = terrain_from(tmp_path, .4 * (140-rr) + .5 * (cc-center)**2)
    result = trace_auto(terrain, [(10, 60), (130, 60)])
    cells = np.asarray(result.cells)
    expected = 60 + 30*np.sin((cells[:, 0]-10)*np.pi/120)
    assert np.mean(abs(cells[:, 1]-expected)) < 2.5
    assert cells[:, 1].max() > 85
    assert result.metrics['engine'] == 'stream_auto'
    assert result.metrics['engine_version'] == 1
    assert result.metrics['status'] == 'candidate'
    assert result.metrics['analysis_resolution'] == 1.
    assert result.metrics['effective_config']['conditioning'] == 'none'
    json.dumps(result.metrics, allow_nan=False)
    for x, y, z in result.coordinates:
        assert z == terrain.sample(x, y)


@pytest.mark.parametrize('barrier', [False, True])
def test_unresolved_whole_source_is_never_repeated(tmp_path, monkeypatch, barrier):
    from tracertool import stream_auto
    data = np.zeros((710, 710))
    if barrier:
        data[355, :] = np.nan
    terrain = terrain_from(tmp_path, data)
    seen = []
    real = stream_auto._trace_domain
    def inspect(*args, **kwargs):
        bounds = args[5] if len(args) > 5 else kwargs.get('bounds')
        assert bounds not in seen, 'Repeated native domain cannot resolve the same failure'
        seen.append(bounds)
        return real(*args, **kwargs)
    monkeypatch.setattr(stream_auto, '_trace_domain', inspect)
    with pytest.raises(ValueError, match='Unresolved'):
        stream_auto.trace_auto(terrain, [(5, 355), (705, 355)])
    assert len(seen) <= 2


def test_joint_soft_guides_select_branch_and_protected_guide_stays_exact(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:100, :110]
    left = 50-22*np.sin((rr-5)*np.pi/90)
    right = 50+22*np.sin((rr-5)*np.pi/90)
    data = .3*(100-rr)+np.minimum((cc-left)**2, (cc-right)**2)
    terrain = terrain_from(tmp_path, data)
    soft = trace_auto(terrain, [(5, 50), (50, 67), (95, 50)])
    middle = np.asarray(soft.cells)
    assert middle[(middle[:, 0] > 40) & (middle[:, 0] < 60), 1].mean() > 67
    assert [50., 67.] not in soft.cells
    hard = trace_auto(terrain, [(5, 50), (50.2, 67.3), (95, 50)], fixed_anchor_indices=[1])
    assert list(terrain.xy(50.2, 67.3)) in [p[:2] for p in hard.coordinates]
    assert hard.fixed_anchor_indices == [1]
    assert hard.metrics['effective_config']['guide_solver'] == 'joint_layered_dijkstra'


def test_large_source_uses_disclosed_bounded_native_reach_domain(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:900, :900]
    terrain = terrain_from(tmp_path, (900-rr)*.2+(cc-450.)**2)
    result = trace_auto(terrain, [(400, 450), (500, 450)])
    cfg = result.metrics['effective_config']
    assert cfg['domain_truncated'] is True
    assert cfg['domain_bounds'] != [0, 900, 0, 900]
    assert any(d['code'] == 'domain_truncated' for d in result.metrics['diagnostics'])
    assert result.metrics['status'] == 'ambiguous'
    assert result.metrics['analysis_resolution'] == 1.


def test_initial_margin_shrinks_before_rejecting_fitting_native_reach(tmp_path, monkeypatch):
    import tracertool.stream_auto as auto
    from types import SimpleNamespace
    from affine import Affine
    terrain = SimpleNamespace(metadata={'original_height': 2500, 'original_width': 2000},
                              _source_transform=Affine(1, 0, 0, 0, -1, 2500),
                              xy=lambda r, c: (c+.5, 2500-r-.5))
    seen = []
    def domain(*args):
        seen.append(args[-1])
        raise ValueError('entered fitting window')
    monkeypatch.setattr(auto, '_trace_domain', domain)
    with pytest.raises(ValueError, match='entered fitting window'):
        auto.trace_auto(terrain, [(100, 200), (1471, 1123)])
    r0, r1, c0, c1 = seen[0]
    assert (r1-r0)*(c1-c0) <= auto.MAX_CELLS
    assert r0 <= 52 and r1 >= 1520 and c0 <= 152 and c1 >= 1172


def test_native_reach_over_old_cell_cap_uses_measured_bounded_budget(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:1000, :1000]
    terrain = terrain_from(tmp_path, (1000-rr)*.2+(cc-500.)**2)
    result = trace_auto(terrain, [(250, 500), (750, 500)])
    cfg = result.metrics['effective_config']
    r0, r1, c0, c1 = cfg['domain_bounds']
    assert (r1-r0)*(c1-c0) > 500_000
    assert cfg['estimated_peak_analysis_bytes'] < 4*1024**3
    assert cfg['domain_truncated']
    assert result.coordinates[0][:2] == list(terrain.xy(250, 500))
    assert result.coordinates[-1][:2] == list(terrain.xy(750, 500))


def test_flat_floor_is_ambiguous_but_featureless_flat_is_unresolved(tmp_path):
    from tracertool.stream_auto import trace_auto
    flat = terrain_from(tmp_path, np.ones((70, 70)))
    with pytest.raises(ValueError, match='[Uu]nresolved.*flat'):
        trace_auto(flat, [(5, 35), (65, 35)])
    rr, cc = np.mgrid[:70, :70]
    terrain = terrain_from(tmp_path, np.maximum(0, abs(cc-35)-6.)**2)
    result = trace_auto(terrain, [(5, 35), (65, 35)])
    assert result.metrics['status'] == 'ambiguous'
    assert any(d['code'] == 'flat' for d in result.metrics['diagnostics'])


def test_auto_discloses_small_pit_treatment_and_exports_raw_z(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:80, :80]
    z = (80-rr)*.01 + (cc-40.)**2
    z += np.random.default_rng(42).normal(0, .02, z.shape)
    z[:, 40] = (80-np.arange(80))*.01
    z[40, 40] = z[41, 40]-.01
    terrain = terrain_from(tmp_path, z, unit='unspecified')
    result = trace_auto(terrain, [(5, 40), (40, 40), (75, 40)], fixed_anchor_indices=[1])
    cfg = result.metrics['effective_config']
    assert cfg['conditioning'] == 'bounded_noise_scale_pits'
    assert cfg['conditioning_summary']['changed_cells'] >= 1
    assert any(d['code'] == 'pit_conditioned' for d in result.metrics['diagnostics'])
    assert result.metrics['status'] == 'ambiguous'
    for x, y, elevation in result.coordinates:
        assert elevation == terrain.sample(x, y)
    assert [*terrain.xy(40, 40), z[40, 40]] in result.coordinates
    json.dumps(result.metrics, allow_nan=False)


def test_true_sink_is_distinct_from_flat_and_boundary_outlet(tmp_path):
    from tracertool.analysis_grid import read_grid
    from tracertool.stream_auto import drainage, trace_auto
    rr, cc = np.mgrid[:70, :70]
    z = (70-rr)*.2+(cc-35.)**2
    z[35, 35] -= 20
    terrain = terrain_from(tmp_path, z)
    hydro = drainage(read_grid(terrain))
    assert hydro['sink'][35, 35]
    assert not hydro['flat'][35, 35]
    assert not hydro['sink'][-1, 35]
    # An uphill least-cost continuation is not a drainage solution for this pit.
    with pytest.raises(ValueError, match='[Uu]nresolved.*sink'):
        trace_auto(terrain, [(5, 35), (35, 35), (65, 35)], fixed_anchor_indices=[1])


def test_cannot_escape_material_basin_by_skipping_its_lowest_cell(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:70, :70]
    z = (70-rr)*.2+(cc-35.)**2
    z[34:37, 34:37] = 2.
    z[35, 35] = 0.
    terrain = terrain_from(tmp_path, z)
    guides = [(33, 36), (34, 36), (35, 36), (36, 36), (37, 36)]
    with pytest.raises(ValueError, match='[Uu]nresolved.*sink'):
        trace_auto(terrain, guides, fixed_anchor_indices=list(range(len(guides))))


def test_flat_bottomed_material_basin_is_not_mistaken_for_safe_flat(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:80, :80]
    z = (80-rr)*.2+(cc-40.)**2
    z[30:40, 38:43] = 0.
    terrain = terrain_from(tmp_path, z)
    with pytest.raises(ValueError, match='[Uu]nresolved.*sink'):
        trace_auto(terrain, [(5, 40), (35, 40), (75, 40)], fixed_anchor_indices=[1])


def test_d8_routes_outlet_connected_flat_without_altering_source(tmp_path):
    from tracertool.analysis_grid import read_grid
    from tracertool.stream_auto import drainage
    z = np.full((9, 9), 20.)
    z[2:7, 4] = 10.
    z[7:, 4] = [9., 8.]
    grid = read_grid(terrain_from(tmp_path, z))
    hydro = drainage(grid)
    receiver = hydro['receiver'].ravel()
    index, visited = 2*9+4, set()
    while receiver[index] >= 0:
        assert index not in visited
        visited.add(index)
        index = int(receiver[index])
    assert index == 8*9+4
    assert hydro['accumulation'][8, 4] >= 7
    np.testing.assert_array_equal(grid.data, z)


def test_d8_confluence_accumulates_both_tributaries(tmp_path):
    from tracertool.analysis_grid import read_grid
    from tracertool.stream_auto import drainage
    z = np.full((12, 13), np.nan)
    for r in range(1, 5):
        z[r, 2:11] = 30-r+np.abs(np.arange(2, 11)-6)*.01
    z[5:11, 6] = np.arange(25, 19, -1)
    terrain = terrain_from(tmp_path, z)
    hydro = drainage(read_grid(terrain))
    receiver = hydro['receiver'].ravel()
    left, right = 4*13+5, 4*13+7
    assert receiver[left] == receiver[right] == 4*13+6
    assert hydro['accumulation'][10, 6] >= 36
    assert hydro['accumulation'][10, 6] > hydro['accumulation'][4, 6]


def test_native_source_nodata_chords_remain_impassable_after_sparse_output(tmp_path):
    from tracertool.stream_auto import trace_auto
    from tracertool.tracing import _segment_cells
    rr, cc = np.mgrid[:90, :90]
    z = (90-rr)*.2+(cc-45.)**2
    z[40:50, 44:47] = np.nan
    terrain = terrain_from(tmp_path, z, max_dimension=15)
    anchors = [terrain.rc(500045.5, 4499994.5), terrain.rc(500045.5, 4499914.5)]
    result = trace_auto(terrain, anchors, TraceParams(spacing=100, simplify=100))
    t = terrain._source_transform
    native = [[(p[1]-t.f)/t.e-.5, (p[0]-t.c)/t.a-.5] for p in result.coordinates]
    for a, b in zip(native[:-1], native[1:]):
        assert all(np.isfinite(z[r, c]) for r, c in _segment_cells(a, b))
    assert max(abs(c-45) for r, c in native) >= 2
    z[:, 45] = np.nan
    terrain = terrain_from(tmp_path, z)
    with pytest.raises(ValueError, match='NoData'):
        trace_auto(terrain, [(10, 40), (80, 50)])


def test_native_route_is_display_independent_and_legacy_knobs_are_ignored(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:100, :100]
    z = .3*(100-rr)+(cc-(45+18*np.sin((rr-5)*np.pi/90)))**2
    full = terrain_from(tmp_path, z)
    reduced = Terrain.load(full.path, max_dimension=20)
    xy = [full.xy(5, 45), full.xy(95, 45)]
    one = trace_auto(full, [full.rc(*p) for p in xy], TraceParams(spacing=5))
    two = trace_auto(reduced, [reduced.rc(*p) for p in xy],
                     TraceParams(spacing=1, corridor=10000, smoothing=50,
                                 terrain_weight=0, line_smoothing=50, simplify=.15))
    np.testing.assert_allclose(one.coordinates, two.coordinates)
    assert one.metrics['analysis_resolution'] == two.metrics['analysis_resolution'] == 1.


def test_cancel_during_native_read_and_solve(tmp_path):
    from tracertool.stream_auto import trace_auto
    from tracertool.tracing import TraceCancelled
    rr, cc = np.mgrid[:200, :200]
    terrain = terrain_from(tmp_path, (200-rr)*.2+(cc-100.)**2)
    with pytest.raises(TraceCancelled):
        trace_auto(terrain, [(5, 100), (195, 100)], cancel=lambda: True)
    calls = [0]
    def cancel():
        calls[0] += 1
        return calls[0] == 25
    with pytest.raises(TraceCancelled):
        trace_auto(terrain, [(5, 100), (195, 100)], cancel=cancel)
    assert calls[0] == 25


def test_rectangular_feet_calibration_and_unchanged_source_z(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:80, :80]
    raw = (80-rr)*.25+(cc-40.)**2
    terrain = terrain_from(tmp_path, raw, pixel=(2, 5), unit='foot', scale=.25, offset=-10.)
    result = trace_auto(terrain, [(5, 40), (75, 40)])
    assert result.metrics['analysis_resolution_xy'] == [2., 5.]
    assert result.metrics['effective_config']['vertical_to_horizontal'] == pytest.approx(.3048)
    assert result.metrics['length'] == pytest.approx(350.)
    for x, y, z in result.coordinates:
        assert z == terrain.sample(x, y)
    assert result.metrics['vertical_units'] == 'foot'


def test_cancellation_interrupts_global_solver_loop(tmp_path):
    from tracertool.analysis_grid import read_grid
    from tracertool.stream_auto import drainage, _solve
    from tracertool.tracing import TraceCancelled
    rr, cc = np.mgrid[:100, :100]
    grid = read_grid(terrain_from(tmp_path, 100-rr+(cc-50.)**2))
    calls = [0]
    def cancel():
        calls[0] += 1
        return calls[0] >= 2
    with pytest.raises(TraceCancelled):
        _solve(grid, np.ones((100, 100)), drainage(grid), [((1, 50), 0.)], [(99, 50)], cancel)
    assert calls[0] == 2


def test_output_spacing_change_does_not_change_raw_route_evidence(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:80, :80]
    terrain = terrain_from(tmp_path, 80-rr+(cc-40.)**2)
    a = trace_auto(terrain, [(5, 40), (75, 40)], TraceParams(spacing=1))
    b = trace_auto(terrain, [(5, 40), (75, 40)], TraceParams(spacing=15))
    assert len(a.cells) > len(b.cells)
    assert a.metrics['relative_support'] == b.metrics['relative_support']
    assert a.metrics['alternative_cost_ratio'] == b.metrics['alternative_cost_ratio']


def test_invalid_fixed_indices_and_geographic_crs_are_rejected(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:30, :30]
    terrain = terrain_from(tmp_path, 30-rr+(cc-15.)**2)
    for fixed in ([True], [2], [-1], [1.5]):
        with pytest.raises(ValueError, match='indices'):
            trace_auto(terrain, [(5, 15), (25, 15)], fixed_anchor_indices=fixed)
    from rasterio.crs import CRS
    terrain.crs = CRS.from_epsg(4326)
    with pytest.raises(ValueError, match='projected'):
        trace_auto(terrain, [(5, 15), (25, 15)])


def test_adaptive_domain_expands_around_native_barrier(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:900, :900]
    z = (900-rr)*.2+(cc-450.)**2
    z[450, 390:511] = np.nan
    terrain = terrain_from(tmp_path, z)
    result = trace_auto(terrain, [(400, 450), (500, 450)])
    bounds = result.metrics['effective_config']['domain_bounds']
    assert bounds[2] < 390 and bounds[3] > 511
    assert result.metrics['status'] == 'ambiguous'


def test_equal_parallel_channels_report_relative_choice_uncertainty(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:100, :110]
    bend = 22*np.sin((rr-5)*np.pi/90)
    terrain = terrain_from(tmp_path, .3*(100-rr)+np.minimum((cc-50-bend)**2, (cc-50+bend)**2))
    result = trace_auto(terrain, [(5, 50), (95, 50)])
    assert result.metrics['status'] == 'ambiguous'
    assert any(d['code'] == 'alternative_route' for d in result.metrics['diagnostics'])


def test_inclined_plane_does_not_invent_channel_from_roundoff(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:100, :100]
    terrain = terrain_from(tmp_path, 100.+rr*.123+cc*.234)
    with pytest.raises(ValueError, match='[Uu]nresolved'):
        trace_auto(terrain, [(5, 20), (95, 20)])


def test_channel_elsewhere_does_not_justify_flat_reach(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:100, :100]
    z = 100.+np.maximum(0, cc-70.)**2
    z[:, :50] = 100.
    terrain = terrain_from(tmp_path, z)
    with pytest.raises(ValueError, match='[Uu]nresolved'):
        trace_auto(terrain, [(10, 10), (90, 10)])


def test_rectangular_horizontal_reach_spacing_is_in_map_units(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:80, :100]
    terrain = terrain_from(tmp_path, (100-cc)*.25+(rr-40.)**2,
                           pixel=(2, 5))
    params = TraceParams(spacing=4)
    result = trace_auto(terrain, [(40, 5), (40, 95)], params)
    target = params.spacing*terrain.resolution
    segments = np.linalg.norm(np.diff(np.asarray(result.coordinates)[:, :2], axis=0), axis=1)
    assert segments.max() <= target + 1e-8
    assert segments.min() >= .9*target
    assert result.metrics['effective_config']['output_spacing_map_units'] == target


def test_source_replaced_after_native_analysis_never_returns_cached_z(tmp_path, monkeypatch):
    import os
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:60, :60]
    terrain = terrain_from(tmp_path, 60-rr+(cc-30.)**2)
    original = terrain.sample_many
    def sample_then_change(coordinates):
        values = original(coordinates)
        stat = os.stat(terrain.path)
        os.utime(terrain.path, ns=(stat.st_atime_ns, stat.st_mtime_ns+1000000))
        return values
    monkeypatch.setattr(terrain, 'sample_many', sample_then_change)
    with pytest.raises(ValueError, match='Source changed'):
        trace_auto(terrain, [(5, 30), (55, 30)])


def test_nodata_edge_terminal_is_unknown_not_a_true_sink(tmp_path):
    from tracertool.analysis_grid import read_grid
    from tracertool.stream_auto import drainage
    rr, cc = np.mgrid[:50, :50]
    z = 50-rr+(cc-25.)**2
    z[25, 24:27] = np.nan
    hydro = drainage(read_grid(terrain_from(tmp_path, z)))
    assert hydro['receiver'][24, 25] == -1
    assert not hydro['sink'][24, 25]
    assert hydro['boundary'][24, 25]


def test_protected_guides_in_same_native_cell_are_not_silently_dropped(tmp_path):
    from tracertool.stream_auto import trace_auto
    rr, cc = np.mgrid[:60, :60]
    terrain = terrain_from(tmp_path, 60-rr+(cc-30.)**2)
    with pytest.raises(ValueError, match='different native'):
        trace_auto(terrain, [(5, 30), (20.1, 30), (20.2, 30), (55, 30)],
                   fixed_anchor_indices=[1, 2])
