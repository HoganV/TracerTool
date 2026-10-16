"""Public synthetic fixtures only; no downloaded geodata required."""
import importlib
import math
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def test_reach_failures_abstentions_and_thresholds_are_not_dropped():
    ev = importlib.import_module('tracertool.evaluation')
    cases = [dict(id=str(i), guides=[[0, 0], [10, 0]], reference=[[0, 0], [10, 0]]) for i in range(4)]
    def solver(guides, case_id):
        assert guides == [[0, 0], [10, 0]]
        if case_id == '1':
            raise ValueError('no route')
        return SimpleNamespace(coordinates=[[0, 1, 0], [10, 1, 0]],
                               metrics={'status': ['candidate', '', 'unresolved', 'ambiguous'][int(case_id)]}, warnings=[])
    report = ev.evaluate_cases(cases, solver, spacing=1)
    assert report['counts'] == dict(total=4, candidate=1, failure=1, abstention=1, ambiguous=1)
    assert report['candidate_coverage'] == .25
    assert report['reach_summary']['symmetric_p95']['median'] == 1
    assert report['reach_summary']['scored_reaches'] == 2
    assert not ev.threshold_passed(report, max_p95=2, max_non_candidate_fraction=0)
    assert ev.threshold_passed(report, max_p95=2, max_non_candidate_fraction=.75)
    assert not ev.threshold_passed(report, max_p95=.5, max_non_candidate_fraction=1)
    assert json.loads(json.dumps(report, allow_nan=False)) == report


import numpy as np
import pytest


@pytest.mark.parametrize('spacing', [0, -1, math.inf, math.nan])
def test_invalid_spacing_rejected_even_for_empty_evaluation(spacing):
    ev = importlib.import_module('tracertool.evaluation')
    with pytest.raises(ValueError):
        ev.evaluate_cases([], lambda *args: None, spacing)


@pytest.mark.parametrize('line', [[], [[0, 0]], [[0, 0], [0, 0]], [[0, 0], [math.nan, 2]]])
def test_invalid_line_rejected(line):
    ev = importlib.import_module('tracertool.evaluation')
    with pytest.raises(ValueError):
        ev.uniform_samples(line, 1)


def test_continuous_distances_chunking_duplicates_and_sampling_bound():
    ev = importlib.import_module('tracertool.evaluation')
    line = [[i, 0] for i in range(601)]
    line.insert(200, line[200])
    points = [[i, 3] for i in np.linspace(0, 600, 1100)]
    assert ev.point_line_distances(points, line) == pytest.approx([3] * 1100)
    # Perpendicular lines have known continuous Hausdorff maximum 10;
    # midpoint max must be within h/2, rather than silently underreported.
    metrics = ev.compare_lines([[0, 0], [10, 0]], [[0, 0], [0, 10]], 3)
    assert metrics['symmetric']['maximum'] <= 10 <= metrics['symmetric']['hausdorff_upper_bound']
    assert metrics['prediction_to_reference']['mean'] == 5
    with pytest.raises(ValueError, match='budget'):
        ev.uniform_samples([[0, 0], [2_000_000, 0]], 1)


def test_all_failed_empty_and_unknown_status_cannot_pass():
    ev = importlib.import_module('tracertool.evaluation')
    cases = [dict(id='bad', guides=[[0, 0], [1, 0]], reference=[[0, 0], [1, 0]])]
    report = ev.evaluate_cases(cases, lambda *args: SimpleNamespace(metrics={'status': 'new-status'}))
    assert report['counts']['failure'] == 1
    assert not ev.threshold_passed(report, max_non_candidate_fraction=1)
    assert not ev.threshold_passed(ev.evaluate_cases([], lambda *args: None))
    with pytest.raises(ValueError, match='Duplicate'):
        ev.evaluate_cases(cases * 2, lambda *args: None)
    for bad in [-1, math.inf, math.nan]:
        with pytest.raises(ValueError):
            ev.threshold_passed(report, max_p95=bad)


def test_fetch_policy_rejects_untrusted_hosts_and_bounds_bytes(tmp_path):
    import importlib.util
    import io
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('pilot_fetch', root / 'scripts/fetch_stream_pilot.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for bad in ('http://enterprise.gisdata.mn.gov/a', 'https://evil.test/a',
                'https://enterprise.gisdata.mn.gov@evil.test/a', 'file:///etc/passwd'):
        with pytest.raises(ValueError):
            module.validate_url(bad)
    module.validate_url('https://enterprise.gisdata.mn.gov/a')
    with pytest.raises(ValueError, match='budget'):
        module.copy_bounded(io.BytesIO(b'123456'), tmp_path / 'large', 5)
    assert not (tmp_path / 'large').exists()
    module.copy_bounded(io.BytesIO(b'12345'), tmp_path / 'ok', 5)
    assert (tmp_path / 'ok').read_bytes() == b'12345'
    (tmp_path / 'busy.partial').write_bytes(b'existing worker')
    with pytest.raises(FileExistsError):
        module.copy_bounded(io.BytesIO(b'new'), tmp_path / 'busy', 5)
    assert (tmp_path / 'busy.partial').read_bytes() == b'existing worker'


@pytest.mark.parametrize('internal_mask', [True, False])
def test_massachusetts_preparation_preserves_native_samples_and_aliases(tmp_path, internal_mask):
    import importlib.util
    import rasterio
    from rasterio.transform import from_origin
    spec = importlib.util.spec_from_file_location('pilot_fetch_ma', Path(__file__).resolve().parents[1] / 'scripts/fetch_stream_pilot.py')
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)
    source = tmp_path / 'usgs-original.tif'
    pixels = np.arange(100, dtype='float32').reshape(10, 10)
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=internal_mask), rasterio.open(source, 'w', driver='GTiff', height=10, width=10, count=1,
                       dtype='float32', crs='EPSG:26919', transform=from_origin(0, 10, 1, 1)) as ds:
        ds.write(pixels, 1)
        ds.scales, ds.offsets = [2], [3]
        ds.set_band_unit(1, 'm')
        mask = np.full((10, 10), 255, dtype='uint8')
        mask[3, 3] = 0
        ds.write_mask(mask)
    vector = dict(objectIdFieldName='OBJECTID', spatialReference={'wkid': 26919}, features=[
        dict(attributes={'OBJECTID': 1}, geometry={'paths': [[[2.5, 7.5], [4.5, 5.5]]]})])
    (tmp_path / 'reference-original.esri.json').write_text(json.dumps(vector))
    fetch.prepare_massachusetts(tmp_path, [2, 5, 5, 8])
    output = json.loads((tmp_path / 'reference.esri.json').read_text())
    assert output['features'][0]['attributes']['objectid'] == 1
    assert output['features'][0]['geometry'] == vector['features'][0]['geometry']
    with rasterio.open(tmp_path / 'terrain-crop.tif') as ds:
        assert np.array_equal(ds.read_masks(1), mask[2:5, 2:5])
        assert np.array_equal(ds.read(1), pixels[2:5, 2:5])
        assert ds.scales == (2,) and ds.offsets == (3,) and ds.units == ('m',)
        assert ds.transform == from_origin(2, 8, 1, 1)


@pytest.mark.parametrize('nodata', [None, -9999.])
def test_historical_crop_without_explicit_mask_is_byte_identical(tmp_path, nodata):
    import importlib.util
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.windows import from_bounds
    spec = importlib.util.spec_from_file_location('pilot_fetch_frozen', Path(__file__).resolve().parents[1] / 'scripts/fetch_stream_pilot.py')
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)
    pixels = np.arange(100, dtype='float32').reshape(10, 10)
    if nodata is not None:
        pixels[3, 3] = nodata
    with rasterio.open(tmp_path / 'usgs-original.tif', 'w', driver='GTiff',
                       height=10, width=10, count=1, dtype='float32', nodata=nodata,
                       crs='EPSG:26919', transform=from_origin(0, 10, 1, 1)) as ds:
        ds.write(pixels, 1)
        ds.set_band_unit(1, 'm')
    (tmp_path / 'reference-original.esri.json').write_text(json.dumps({'features': []}))
    bounds = [2, 5, 5, 8]
    # The frozen v1 algorithm, including its disclosed unit-tag omission.
    with rasterio.open(tmp_path / 'usgs-original.tif') as source:
        window = from_bounds(*bounds, source.transform).round_offsets().round_lengths()
        profile = source.profile.copy()
        profile.update(width=int(window.width), height=int(window.height), transform=source.window_transform(window))
        with rasterio.open(tmp_path / 'old.tif', 'w', **profile) as output:
            output.write(source.read(window=window))
    fetch.prepare_massachusetts(tmp_path, bounds, historical_v1=True)
    assert (tmp_path / 'terrain-crop.tif').read_bytes() == (tmp_path / 'old.tif').read_bytes()
    with rasterio.open(tmp_path / 'terrain-crop.tif') as output:
        assert output.units == (None,)
        assert output.scales == (1.,) and output.offsets == (0.,)
        assert np.array_equal(output.read_masks(1) != 0, pixels[2:5, 2:5] != nodata)


def test_cli_runs_real_synthetic_pair_and_writes_threshold_failure(tmp_path):
    import hashlib
    import os
    import subprocess
    import rasterio
    from rasterio.transform import from_origin
    root = Path(__file__).resolve().parents[1]
    raster = tmp_path / 'dem.tif'
    yy, xx = np.mgrid[:32, :32]
    with rasterio.open(raster, 'w', driver='GTiff', height=32, width=32, count=1,
                       dtype='float32', crs='EPSG:26915', transform=from_origin(0, 32, 1, 1)) as ds:
        ds.write((100 + yy * .1 + (xx - 16) ** 2 * .1).astype('float32'), 1)
    vector = tmp_path / 'reference.json'
    vector.write_text(json.dumps(dict(spatialReference={'wkid': 26915}, features=[
        dict(attributes={'objectid': 1}, geometry={'paths': [[[16.5, 28.5], [16.5, 3.5]]]})])))
    manifest = dict(schema_version=1, id='synthetic', split='development', label_role='synthetic',
                    crs='EPSG:26915', assets={key: dict(file=p.name, sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                    for key, p in [('raster', raster), ('reference', vector)]},
                    cases=[dict(id='one', feature_id=1, path_index=0, guide_indices=[0, -1])])
    source = tmp_path / 'manifest.json'
    source.write_text(json.dumps(manifest))
    output = tmp_path / 'report.json'
    command = [sys.executable, str(root / 'scripts/evaluate_streams.py'),
               '--manifest', str(source), '--data-dir', str(tmp_path), '--output', str(output),
               '--method', 'legacy', '--max-p95', '0', '--max-dimension', '32']
    run = subprocess.run(command, cwd=root, env={**os.environ, 'PYTHONPATH': str(root / 'src')}, capture_output=True, text=True)
    assert run.returncode == 2, run.stdout + run.stderr
    report = json.loads(output.read_text())
    assert report['counts']['total'] == 1
    assert report['counts']['candidate'] == 1
    assert report['provenance']['manifest_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert report['provenance']['method'] == 'legacy'
    assert report['threshold_passed'] is False
    assert report['provenance']['engine_source_sha256']
    assert report['provenance']['module_sha256']['terrain.py']
    assert report['provenance']['dependency_versions']['numpy']
    ev = importlib.import_module('tracertool.evaluation')
    _, _, cases = ev.load_pair(source, tmp_path)
    assert cases[0]['guides'] == [[16.5, 28.5], [16.5, 3.5]]
    for edit, match in [
        (lambda m: m.update(split='acceptance'), 'holdout'),
        (lambda m: m['assets']['raster'].update(file='../escape.tif'), 'escapes'),
        (lambda m: m['assets']['raster'].update(sha256='0' * 64), 'Hash mismatch'),
        (lambda m: m.update(crs='EPSG:26919'), 'CRS'),
        (lambda m: m['cases'][0].update(feature_id=999), 'Missing'),
    ]:
        changed = json.loads(json.dumps(manifest))
        edit(changed)
        source.write_text(json.dumps(changed))
        with pytest.raises(ValueError, match=match):
            ev.load_pair(source, tmp_path)


def test_paired_comparison_retains_noncomparable_reaches():
    ev = importlib.import_module('tracertool.evaluation')
    cases = [dict(id=str(i), guides=[[0, 0], [10, 0]], reference=[[0, 0], [10, 0]]) for i in range(3)]
    baseline = ev.evaluate_cases(cases, lambda *args: SimpleNamespace(coordinates=[[0, 4], [10, 4]], metrics={}, warnings=[]))
    def contender(guides, case_id):
        return SimpleNamespace(coordinates=[[0, 2], [10, 2]], metrics={'status': 'unresolved' if case_id == '2' else 'ambiguous'}, warnings=[])
    candidate = ev.evaluate_cases(cases, contender)
    result = ev.compare_reports(baseline, candidate)
    assert result['total_reaches'] == 3
    assert result['comparable_reaches'] == 2
    assert result['unscored_reaches'] == ['2']
    assert result['median_paired_p95_delta'] == -2
    assert result['median_paired_relative_gain'] == .5
    assert result['promotion_evidence'] is False
    candidate['sampling_spacing'] = 2
    with pytest.raises(ValueError, match='scoring'):
        ev.compare_reports(baseline, candidate)


def test_threshold_uses_sampling_bound_not_optimistic_midpoints():
    ev = importlib.import_module('tracertool.evaluation')
    cases = [dict(id='one', guides=[[0, 0], [10, 0]], reference=[[0, 0], [0, 10]])]
    report = ev.evaluate_cases(cases, lambda *args: SimpleNamespace(
        coordinates=[[0, 0], [10, 0]], metrics={}, warnings=[]), spacing=3)
    # Sampled p95=8.75; continuous p95=9.5. A 9-unit limit cannot pass.
    assert not ev.threshold_passed(report, max_p95=9)
    assert report['reaches'][0]['distances']['symmetric']['p95_upper_bound'] == 10


def test_numerically_degenerate_reach_is_counted_failure_and_serializable():
    ev = importlib.import_module('tracertool.evaluation')
    cases = [dict(id=str(i), guides=[[0, 0], [1, 0]],
                  reference=[[0, 0], [1, 0]]) for i in range(2)]
    def solver(guides, case_id):
        line = [[0, 0], [1, 0]] if case_id == '0' else [[0, 0], [1e-200, 0], [1, 0]]
        return SimpleNamespace(coordinates=line, metrics={}, warnings=[])
    report = ev.evaluate_cases(cases, solver)
    assert report['counts'] == dict(total=2, candidate=1, failure=1, abstention=0, ambiguous=0)
    assert report['reach_summary']['scored_reaches'] == 1
    assert 'distances' not in report['reaches'][1]
    assert not ev.threshold_passed(report, max_p95=1)
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize('bad', [math.nan, math.inf, -math.inf])
def test_nonfinite_scoring_writes_finished_cli_failure(tmp_path, monkeypatch, bad):
    ev = importlib.import_module('tracertool.evaluation')
    spec = importlib.util.spec_from_file_location('evaluation_cli', Path(__file__).resolve().parents[1] / 'scripts/evaluate_streams.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    cases = [dict(id='one', guides=[[0, 0], [1, 0]], reference=[[0, 0], [1, 0]])]
    monkeypatch.setattr(ev, 'compare_lines', lambda *args: {'symmetric': {'p95': bad, 'p95_upper_bound': bad}})
    monkeypatch.setattr(cli, 'run_pair', lambda *args: ev.evaluate_cases(cases, lambda *args:
        SimpleNamespace(coordinates=[[0, 0], [1, 0]], metrics={}, warnings=[])))
    output = tmp_path / 'report.json'
    assert cli.main(['--manifest', 'unused', '--data-dir', 'unused', '--output', str(output)]) == 2
    report = json.loads(output.read_text())
    assert report['counts']['failure'] == 1
    assert report['reach_summary']['scored_reaches'] == 0
    assert 'distances' not in report['reaches'][0]
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize('bad', [math.nan, math.inf, -math.inf])
def test_threshold_rejects_nonfinite_scores_even_without_limit(bad):
    ev = importlib.import_module('tracertool.evaluation')
    report = dict(counts={'total': 2}, candidate_coverage=1, reaches=[
        {'distances': {'symmetric': {'p95_upper_bound': value}}} for value in [.5, bad]])
    assert not ev.threshold_passed(report, max_p95=1)
    assert not ev.threshold_passed(report)


def test_uniform_arc_samples_and_continuous_segment_distances():
    ev = importlib.import_module('tracertool.evaluation')
    samples, step = ev.uniform_samples([[0, 0], [1, 0], [10, 0]], 3)
    assert step == 2.5
    assert samples[:, 0] == pytest.approx([1.25, 3.75, 6.25, 8.75])
    assert ev.point_line_distances([[5, 2], [-1, 0], [12, 0]], [[0, 0], [10, 0]]) == pytest.approx([2, 1, 2])
    result = ev.compare_lines([[0, 2], [10, 2]], [[0, 0], [1, 0], [10, 0]], spacing=1)
    assert result['symmetric']['mean'] == pytest.approx(2)
    assert result['symmetric']['p95'] == pytest.approx(2)
    assert result['symmetric']['hausdorff_upper_bound'] >= 2
    assert result['prediction_to_reference']['sampling_error_bound'] == 0.5
    # Source vertex density must not change the score.
    assert ev.compare_lines([[0, 2], [1, 2], [10, 2]], [[0, 0], [10, 0]], 1) == result
