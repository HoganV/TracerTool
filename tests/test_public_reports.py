"""Schema-scoped public metadata, not an arbitrary-input privacy guarantee."""
import json
import pytest
from tracertool.public_report import sanitize_report


@pytest.mark.parametrize('path', ['/srv/private/terrain.tif', r'\\server\private\terrain.tif',
                                  '../private/terrain.tif', 'private/terrain.tif',
                                  r'C:\private\terrain.tif', '/'.join(('', 'home', 'somebody', 'private.tif'))])
def test_report_only_exports_declared_primitive_metadata(path):
    report = {'counts': {'total': 1, 'unknown': path}, 'reaches': [{'id': 'public-1',
        'prediction': [[1, 2, 3]], 'reference': [[1, 2]], 'status': 'failure',
        'engine_metrics': {'effective_config': {'source_identity': {'path': path}}},
        'error': f'Cannot open {path}', 'warnings': [path], 'unknown': path}],
        'provenance': {'terrain': {'path': path}, 'platform': path, 'unknown': path},
        'unknown': path}
    clean = sanitize_report(report)
    assert report['reaches'][0]['prediction'] == [[1, 2, 3]]
    assert clean == {'counts': {'total': 1}, 'reaches': [{'id': 'public-1', 'status': 'failure'}],
                     'provenance': {}}


def test_failed_generated_summary_keeps_null_score_and_primitive_metrics():
    from tracertool.evaluation import evaluate_cases
    def fail(*args):
        raise ValueError('private details without a recognizable path')
    report = evaluate_cases([{'id': 'one', 'guides': [[0, 0], [1, 0]], 'reference': [[0, 0], [1, 0]]}], fail)
    clean = sanitize_report(report)
    assert clean['reach_summary'] == report['reach_summary']
    assert clean['counts'] == report['counts']
    assert clean['reaches'][0]['error_type'] == 'ValueError'
    assert 'error' not in clean['reaches'][0]
    assert sanitize_report(clean) == clean
    json.dumps(clean, allow_nan=False)


def test_reference_asset_descriptor_survives_but_paths_and_wrong_types_do_not():
    digest = 'a' * 64
    report = {'schema_version': 1, 'counts': {'total': '/srv/private/file'},
        'reaches': [{'id': '../private/reach', 'status': 'candidate', 'seconds': 'private/time',
                    'distances': {'symmetric': {'p95': 2., 'unknown': '/srv/private'}},
                    'error_type': '/srv/private', 'reference': [[1, 2]], 'error': 'secret'}],
        'provenance': {'assets': {'reference': {'file': '../private/reference.json', 'sha256': digest,
                                               'bytes': 123, 'path': '/srv/private'},
                                   'raster': {'file': 'terrain.tif', 'sha256': digest},
                                   'unknown': {'sha256': digest}},
                       'method': 'private/method', 'manifest_id': r'\\server\private',
                       'module_sha256': {'evaluation.py': digest, '/srv/private.py': digest}}}
    clean = sanitize_report(report)
    assert clean['provenance']['assets'] == {
        'reference': {'sha256': digest, 'bytes': 123},
        'raster': {'file': 'terrain.tif', 'sha256': digest}}
    assert clean['provenance']['module_sha256'] == {'evaluation.py': digest}
    assert clean['reaches'] == [{'status': 'candidate', 'distances': {'symmetric': {'p95': 2.}}}]
    assert clean['counts'] == {}
    assert 'private' not in json.dumps(clean)
    json.dumps(clean, allow_nan=False)
