"""Shape-quality acceptance checks on deterministic levees and bank terrain.

No private reference rasters are required. Metrics compare continuous output
with a legacy-style cell route and enforce feature adherence as well as smooth
shape; reducing vertex count alone must not make a line pass these tests.
"""
import math
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from tracertool.terrain import Terrain
from tracertool.tracing import TraceParams, trace, validate_segments, _resample


def terrain_from(tmp_path, data):
    path = tmp_path / 'quality.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=data.shape[1], height=data.shape[0],
                       count=1, dtype='float32', crs='EPSG:32615',
                       transform=from_origin(500000, 4500000, 1, 1), nodata=-9999) as dataset:
        dataset.write(np.where(np.isfinite(data), data, -9999).astype('float32'), 1)
        dataset.set_band_unit(1, 'm')
    return Terrain.load(path)


def angle_variation(cells):
    edges = np.diff(np.asarray(cells), axis=0)
    angles = np.unwrap(np.arctan2(edges[:, 1], edges[:, 0]))
    return float(np.abs(np.diff(angles)).sum())


def legacy_params(**kwargs):
    return TraceParams(smoothing=1.2, spacing=3, simplify=.5, line_smoothing=0, relax_anchors=False, **kwargs)


def smoothed_params(**kwargs):
    # The optional smoothing acceptance tests retain their explicit historical
    # settings. New-draft defaults deliberately use zero smoothing and a
    # smaller three-cell target; their acceptance checks live separately.
    return TraceParams(smoothing=2, spacing=8, simplify=1, line_smoothing=4,
                       relax_anchors=False, **kwargs)


def assert_spacing(result, fraction=.85):
    lengths = np.linalg.norm(np.diff(np.asarray(result.cells), axis=0), axis=1)
    assert np.median(lengths) >= 5
    assert lengths.max() <= 8 + 1e-7
    assert np.mean((lengths >= 5) & (lengths <= 10)) >= fraction
    assert result.metrics['spacing_median_pixels'] == pytest.approx(np.median(lengths))


def test_oblique_flat_topped_levee_is_centered_smooth_and_sparse(tmp_path):
    rr, cc = np.mgrid[:250, :250]
    center = 40 + .6 * rr
    data = 100 + 12 * np.clip((12 - np.abs(cc - center)) / 6, 0, 1)
    data += .08 * np.sin(rr * 1.7) * np.cos(cc * 1.2)
    terrain = terrain_from(tmp_path, data)
    anchors = [(20, 52), (220, 172)]
    old = trace(terrain, anchors, 'ridge', legacy_params(corridor=20))
    new = trace(terrain, anchors, 'ridge', smoothed_params(corridor=20))
    cells = np.asarray(new.cells)
    deviation = np.abs(cells[:, 1] - (40 + .6 * cells[:, 0])) / math.sqrt(1.36)
    assert deviation.mean() < 1.5
    assert deviation.max() < 3
    assert angle_variation(new.cells) < max(.1, angle_variation(old.cells) * .35)
    assert len(new.cells) < len(old.cells) * .5
    assert_spacing(new)
    validate_segments(terrain, new.coordinates)


def test_curved_levee_retains_feature_center_and_does_not_cut_curve(tmp_path):
    rr, cc = np.mgrid[:260, :240]
    def center(r):
        return 100 + 25 * np.sin((r - 20) * np.pi / 220)
    data = 100 + 10 * np.clip((12 - np.abs(cc - center(rr))) / 6, 0, 1)
    data += .05 * np.sin(rr * 2.1) * np.cos(cc * .8)
    terrain = terrain_from(tmp_path, data)
    anchors = [(20, 100), (130, 125), (240, 100)]
    old = trace(terrain, anchors, 'ridge', legacy_params(corridor=25))
    new = trace(terrain, anchors, 'ridge', smoothed_params(corridor=25))
    cells = np.asarray(new.cells)
    assert np.mean(np.abs(cells[:, 1] - center(cells[:, 0]))) < 1.75
    assert np.max(np.abs(cells[:, 1] - center(cells[:, 0]))) < 3
    assert angle_variation(new.cells) < angle_variation(old.cells) * .5
    assert all(list(anchor) in new.cells for anchor in anchors)
    assert_spacing(new)


def test_bank_slope_break_keeps_embankment_edge(tmp_path):
    rr, cc = np.mgrid[:220, :220]
    edge = 55 + .35 * rr
    data = 100 + np.clip(cc - edge, 0, 14) * .8
    terrain = terrain_from(tmp_path, data)
    anchors = [(20, 62), (200, 125)]
    new = trace(terrain, anchors, 'slope_break', smoothed_params(corridor=10))
    cells = np.asarray(new.cells)
    assert np.mean(np.abs(cells[:, 1] - (55 + .35 * cells[:, 0]))) < 1.5
    assert_spacing(new)


def test_meaningful_levee_bend_survives_regularization(tmp_path):
    rr, cc = np.mgrid[:240, :220]
    def center(r):
        return 90 + 13 * np.exp(-.5 * ((r - 120) / 13) ** 2)
    data = 100 + 10 * np.exp(-.5 * ((cc - center(rr)) / 4) ** 2)
    terrain = terrain_from(tmp_path, data)
    new = trace(terrain, [(20, 90), (220, 90)], 'ridge', smoothed_params(corridor=22))
    cells = np.asarray(new.cells)
    assert cells[:, 1].max() > 100, 'A real 13-cell crest anomaly must not be smoothed back to the chord.'
    assert np.mean(np.abs(cells[:, 1] - center(cells[:, 0]))) < 2
    assert np.max(np.abs(cells[:, 1] - center(cells[:, 0]))) < 3.5
    assert_spacing(new, fraction=.8)


def test_nodata_gap_and_fixed_corner_remain_safe(tmp_path):
    rr, cc = np.mgrid[:140, :140]
    data = 100 + 8 * np.exp(-.5 * ((cc - 70) / 5) ** 2)
    data[60:75, 65:75] = np.nan
    terrain = terrain_from(tmp_path, data)
    new = trace(terrain, [(15, 70), (120, 70)], 'ridge', smoothed_params(corridor=20))
    validate_segments(terrain, new.coordinates)
    assert new.cells[0] == [15, 70] and new.cells[-1] == [120, 70]
    assert new.metrics['spacing_exception_count'] >= 0
    # Hard guide anchors retain an intentional sharp turn, with exact source Z.
    hard = trace(terrain, [(15, 25), (45, 25), (45, 55)], 'ridge', smoothed_params(corridor=5))
    assert [45, 25] in hard.cells
    for x, y, z in hard.coordinates:
        assert z == terrain.sample(x, y)


def test_resampling_ignores_tiny_raster_corners_and_redistributes_remainder():
    points = [[i, .2 if i % 2 else 0.] for i in range(102)]
    output = np.asarray(_resample(points, 8, tolerance=.5))
    lengths = np.linalg.norm(np.diff(output, axis=0), axis=1)
    assert len(output) < 16
    assert lengths.min() > 7
    assert lengths.max() <= 8
    assert output[0].tolist() == points[0]
    assert output[-1].tolist() == points[-1]


def test_fixed_guide_reversal_is_preserved_and_flagged(tmp_path):
    terrain = terrain_from(tmp_path, np.zeros((80, 80)))
    result = trace(terrain, [(10, 20), (40, 20), (15, 25)], 'ridge', TraceParams(relax_anchors=False))
    assert [40, 20] in result.cells
    assert result.metrics['sharp_guide_indices'] == [2]
    assert any('sharper than 90' in warning for warning in result.warnings)


def test_zero_bend_tolerance_retains_detail_instead_of_silently_clamping():
    points = [[0., 0.], [1., .2], [2., 0.], [3., .2], [4., 0.]]
    exact = _resample(points, 8, tolerance=0)
    simplified = _resample(points, 8, tolerance=1)
    assert all(p in exact for p in points)
    assert simplified == [points[0], points[-1]]


def test_large_spacing_with_strict_tolerance_does_not_exhaust_recursion():
    points = [[float(i), .2 if i % 2 else 0.] for i in range(1900)]
    assert _resample(points, 2000, tolerance=0) == points


def test_wide_flat_channel_follows_middle_instead_of_shoreline(tmp_path):
    rr, cc = np.mgrid[:260, :260]
    center = 55 + .5 * rr
    # Hydroflattened floor: local second derivatives favor the bank toes,
    # whereas the broad cross profile has its minimum in the channel middle.
    data = 100 + 12 * np.clip((np.abs(cc - center) - 25) / 8, 0, 1)
    data += .015 * np.sin(rr * .7) * np.cos(cc * .9)
    terrain = terrain_from(tmp_path, data)
    result = trace(terrain, [(20, 65), (220, 165)], 'stream', smoothed_params(corridor=40))
    points = np.asarray(result.cells)
    error = np.abs(points[:, 1] - (55 + .5 * points[:, 0])) / math.sqrt(1.25)
    assert error.mean() < 3
    assert error.max() < 5
    assert_spacing(result)
