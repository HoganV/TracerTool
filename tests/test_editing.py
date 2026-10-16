from copy import deepcopy
from dataclasses import asdict
import json
import math

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from tracertool.editing import (move_vertex, insert_vertex, delete_vertex, reverse_feature,
    split_feature, join_features, replace_segment, refresh_feature, reconstruct_anchors)
from tracertool.project import new_feature, save_project, load_project
from tracertool.terrain import Terrain
from tracertool.tracing import TraceParams, TraceResult, trace, validate_segments


@pytest.fixture
def terrain(tmp_path):
    path = tmp_path / 'terrain.tif'
    rr, cc = np.mgrid[:80, :80]
    data = 100 - rr + cc * .25
    with rasterio.open(path, 'w', driver='GTiff', width=80, height=80, count=1,
                       dtype='float32', crs='EPSG:32615', transform=from_origin(500000, 4500000, 2, 2)) as dst:
        dst.write(data.astype('float32'), 1)
        dst.set_band_unit(1, 'm')
    return Terrain.load(path)


def feature(terrain, cells=((10, 10), (20, 10), (30, 10), (40, 10)), kind='stream'):
    xyz = [[*terrain.xy(r, c), terrain.sample(*terrain.xy(r, c))] for r, c in cells]
    result = TraceResult(xyz, list(cells), anchors=[p[:2] for p in xyz])
    return new_feature('Original', kind, result, TraceParams())


def test_move_insert_delete_preserve_identity_other_xyz_and_inputs(terrain):
    original = feature(terrain)
    before = deepcopy(original)
    moved = move_vertex(terrain, original, 1, terrain.xy(20.2, 12.3))
    assert original == before
    assert moved['id'] == original['id']
    assert moved['coordinates'][0] == original['coordinates'][0]
    assert moved['coordinates'][2:] == original['coordinates'][2:]
    assert moved['coordinates'][1][2] == terrain.sample(*terrain.xy(20.2, 12.3))
    assert 'anchors' not in moved
    assert moved['metrics']['vertices'] == 4
    assert moved['provenance'][-1]['operation'] == 'move_vertex'
    inserted = insert_vertex(terrain, original, 1, terrain.xy(25, 10))
    assert inserted['coordinates'][:2] == original['coordinates'][:2]
    assert inserted['coordinates'][3:] == original['coordinates'][2:]
    restored = delete_vertex(terrain, inserted, 2)
    assert restored['coordinates'] == original['coordinates']
    json.dumps(moved, allow_nan=False)


def test_reject_degenerate_geometry_and_invalid_indices(terrain):
    original = feature(terrain)
    with pytest.raises(ValueError, match='zero-length'):
        move_vertex(terrain, original, 1, original['coordinates'][0][:2])
    with pytest.raises(ValueError, match='zero-length'):
        insert_vertex(terrain, original, 0, original['coordinates'][0][:2])
    with pytest.raises(ValueError, match='two vertices'):
        delete_vertex(terrain, feature(terrain, ((10, 10), (20, 10))), 0)
    for index in (-1, 100, 1.5, True):
        with pytest.raises(ValueError, match='vertex'):
            move_vertex(terrain, original, index, terrain.xy(25, 25))


def test_delete_and_join_cannot_cut_nodata_corners(terrain):
    terrain.data[20, 20] = np.nan
    terrain.valid[20, 20] = False
    original = feature(terrain, ((19, 20), (19, 19), (20, 19)))
    with pytest.raises(ValueError, match='NoData'):
        delete_vertex(terrain, original, 1)
    a = feature(terrain, ((15, 20), (19, 20)))
    b = feature(terrain, ((20, 19), (25, 19)))
    with pytest.raises(ValueError, match='NoData'):
        join_features(terrain, a, b, 3)


def test_reverse_refreshes_uphill_warning_and_guides(terrain):
    original = refresh_feature(terrain, feature(terrain), feature(terrain)['coordinates'], 'initial_qa')
    original['anchors'] = [p[:2] for p in original['coordinates']]
    reversed_line = reverse_feature(terrain, original)
    assert reversed_line['coordinates'] == list(reversed(original['coordinates']))
    assert reversed_line['anchors'] == list(reversed(original['anchors']))
    assert reversed_line['metrics']['elevation_gain'] == original['metrics']['elevation_loss']
    assert any('uphill' in warning for warning in reversed_line['warnings'])
    restored = reverse_feature(terrain, reversed_line)
    assert restored['coordinates'] == original['coordinates']
    assert not any('uphill' in warning for warning in restored['warnings'])


def test_split_keeps_shared_xyz_and_assigns_second_identity(terrain):
    original = feature(terrain)
    a, b = split_feature(terrain, original, 2)
    assert a['id'] == original['id']
    assert b['id'] != original['id']
    assert a['coordinates'] == original['coordinates'][:3]
    assert b['coordinates'] == original['coordinates'][2:]
    assert a['coordinates'][-1] == b['coordinates'][0]
    assert 'anchors' not in a and 'anchors' not in b
    for index in (0, 3):
        with pytest.raises(ValueError, match='internal'):
            split_feature(terrain, original, index)


@pytest.mark.parametrize('reverse_a,reverse_b', [(False, False), (True, False), (False, True), (True, True)])
def test_join_orients_endpoints_without_moving_xyz(terrain, reverse_a, reverse_b):
    a = feature(terrain, ((10, 10), (20, 10)))
    b = feature(terrain, ((21, 10), (30, 10)))
    expected = a['coordinates'] + b['coordinates']
    if reverse_a:
        a['coordinates'].reverse()
    if reverse_b:
        b['coordinates'].reverse()
    before_a, before_b = deepcopy(a), deepcopy(b)
    joined = join_features(terrain, a, b, 2)
    assert joined['coordinates'] == expected
    assert joined['id'] == a['id']
    assert a == before_a and b == before_b
    assert joined['provenance'][-1]['details']['gap'] == 2
    with pytest.raises(ValueError, match='beyond'):
        join_features(terrain, a, b, 1.9)


def test_join_shared_endpoint_and_kind_validation(terrain):
    a = feature(terrain, ((10, 10), (20, 10)))
    b = feature(terrain, ((20, 10), (30, 10)))
    assert len(join_features(terrain, a, b, 0)['coordinates']) == 3
    b['kind'] = 'ridge'
    with pytest.raises(ValueError, match='same kind'):
        join_features(terrain, a, b, 1)


def test_segment_correction_preserves_fractional_boundary_xyz_exactly(terrain):
    original = feature(terrain, ((10, 10), (20.2, 10.3), (30.1, 10.2), (40, 10)))
    # An existing retained elevation must not be silently resampled away.
    original['coordinates'][1][2] += .125
    before = deepcopy(original)
    params = TraceParams(corridor=15, spacing=2)
    result = trace(terrain, [terrain.rc(*original['coordinates'][1][:2]), (25, 14),
                            terrain.rc(*original['coordinates'][2][:2])], 'manual', params)
    changed = replace_segment(terrain, original, 1, 2, result, params)
    assert original == before
    assert changed['id'] == original['id']
    assert changed['coordinates'][0] == original['coordinates'][0]
    assert changed['coordinates'][1] == original['coordinates'][1]
    assert changed['coordinates'][-2] == original['coordinates'][2]
    assert changed['coordinates'][-1] == original['coordinates'][-1]
    assert changed['parameters'] == original['parameters']
    assert changed['provenance'][-1]['details']['parameters'] == asdict(params)
    assert changed['metrics']['elevation_mismatch_vertices'] == 1
    assert 'anchors' not in changed
    validate_segments(terrain, changed['coordinates'])


def test_correction_keeps_new_engine_diagnostics_without_claiming_whole_line_evidence(terrain):
    original = feature(terrain)
    result = TraceResult([original['coordinates'][1],
                          [*terrain.xy(25, 12), terrain.sample(*terrain.xy(25, 12))],
                          original['coordinates'][2]], [],
                         metrics={'engine': 'stream_auto', 'engine_version': 1,
                                  'status': 'ambiguous', 'diagnostics': [{'code': 'fork', 'message': 'Inspect fork'}]},
                         warnings=['Correction warning'])
    before = deepcopy(result.metrics)
    changed = replace_segment(terrain, original, 1, 2, result, TraceParams())
    details = changed['provenance'][-1]['details']
    assert details['engine'] == 'stream_auto'
    assert details['engine_version'] == 1
    assert details['metrics'] == before
    assert details['warnings'] == ['Correction warning']
    assert details['evidence_stale'] is True  # boundaries are restored, not solver output
    assert changed['engine'] == 'legacy'  # a local correction is not a whole-line retrace
    result.metrics['diagnostics'].clear()
    assert details['metrics'] == before


def test_join_retains_second_engine_evidence_in_provenance(terrain):
    a = feature(terrain, ((10, 10), (20, 10)))
    b = feature(terrain, ((20, 10), (30, 10)))
    b.update(engine='stream_auto', engine_version=1)
    b['metrics'] = {'engine': 'stream_auto', 'engine_version': 1,
                    'diagnostics': [{'code': 'fork', 'message': 'Inspect'}]}
    b['warnings'] = ['Second line warning']
    joined = join_features(terrain, a, b, 0)
    details = joined['provenance'][-1]['details']
    assert details['joined_engine'] == 'stream_auto'
    assert details['joined_engine_version'] == 1
    assert details['joined_metrics'] == b['metrics']
    assert details['joined_warnings'] == b['warnings']


def test_refresh_samples_z_and_sparse_guides_preserve_endpoints(terrain):
    original = feature(terrain, ((10.2, 10.3), (20, 10), (30, 10), (40.1, 10.2)))
    coordinates = deepcopy(original['coordinates'])
    for p in coordinates:
        p[2] = -999
    result = refresh_feature(terrain, original, coordinates, 'retrace')
    assert result['coordinates'] == original['coordinates']
    assert result['metrics']['elevation_mismatch_vertices'] == 0
    guides = reconstruct_anchors(terrain, result)
    assert guides == [original['coordinates'][0][:2], original['coordinates'][-1][:2]]
    validate_segments(terrain, guides)


def test_edited_features_round_trip_project_with_provenance(terrain, tmp_path):
    original = feature(terrain)
    changed = move_vertex(terrain, original, 1, terrain.xy(20, 12))
    path = tmp_path / 'edited.tracer.json'
    save_project(path, terrain.path, [changed], {})
    assert load_project(path)['features'][0] == changed


@pytest.mark.parametrize('operation', ['move', 'insert', 'delete', 'reverse', 'split', 'refresh'])
def test_edits_retain_engine_evidence_as_stale_separate_from_geometry_qa(terrain, operation):
    original = feature(terrain)
    evidence = {'engine': 'stream_auto', 'engine_version': 1, 'status': 'ambiguous',
                'analysis_resolution': 2, 'effective_config': {'scale': 12},
                'diagnostics': [{'code': 'ambiguous', 'message': 'Two valleys',
                                 'location': original['coordinates'][1][:2]}],
                'confidence': .2, 'domain_truncated': True, 'future_evidence': {'a': [1]}}
    original.update(engine='stream_auto', engine_version=1)
    original['metrics'].update(evidence, length=-123, spacing_min=-1)
    before = deepcopy(original)
    if operation == 'move':
        outputs = [move_vertex(terrain, original, 1, terrain.xy(20, 12))]
    elif operation == 'insert':
        outputs = [insert_vertex(terrain, original, 1, terrain.xy(25, 10))]
    elif operation == 'delete':
        outputs = [delete_vertex(terrain, original, 1)]
    elif operation == 'reverse':
        outputs = [reverse_feature(terrain, original)]
    elif operation == 'split':
        outputs = split_feature(terrain, original, 1)
    else:
        outputs = [refresh_feature(terrain, original, original['coordinates'], 'retrace')]
    for out in outputs:
        assert out['engine'] == 'stream_auto'
        assert out['metrics']['engine'] == 'stream_auto'
        assert out['metrics']['diagnostics'] == evidence['diagnostics']
        assert out['metrics']['evidence_stale'] is True
        assert out['metrics']['status'] == 'stale'
        assert out['engine_evidence']['metrics'] == before['metrics']
        assert out['engine_evidence']['stale'] is True
        assert out['metrics']['length'] > 0
        assert out['metrics']['spacing_min'] > 0
        json.dumps(out, allow_nan=False)
    assert original == before
    again = reverse_feature(terrain, outputs[0])
    assert again['engine_evidence']['metrics'] == before['metrics']


def test_edit_recomputes_spacing_and_discards_obsolete_guide_warning(terrain):
    original = feature(terrain, ((10, 10), (40, 10), (15, 15), (15, 30)), kind='ridge')
    original['metrics'].update(spacing_min=-1, spacing_median=-1,
                               spacing_exception_count=999, sharp_guide_indices=[2])
    original['warnings'] = ['Guide anchor(s) 2 create turns sharper than 90°.']
    changed = move_vertex(terrain, original, 1, terrain.xy(20, 10))
    coords = np.asarray(changed['coordinates'])
    edges = np.linalg.norm(np.diff(coords[:, :2], axis=0), axis=1)
    pixels = edges / terrain.resolution
    metrics = changed['metrics']
    assert metrics['spacing_min'] == pytest.approx(edges.min())
    assert metrics['spacing_median'] == pytest.approx(np.median(edges))
    assert metrics['spacing_max_pixels'] == pytest.approx(pixels.max())
    assert metrics['spacing_exception_count'] == int(np.count_nonzero(pixels < original["parameters"]["spacing"] * .625))
    assert metrics['spacing_long_edge_count'] == int(np.count_nonzero(pixels > original["parameters"]["spacing"]))
    assert 'sharp_guide_indices' not in metrics
    assert not any(w.startswith('Guide anchor(s)') for w in changed['warnings'])


def test_reverse_recomputes_sharp_guide_labels_without_changing_geometry(terrain):
    original = feature(terrain, ((10, 10), (40, 10), (15, 15), (15, 30)), kind='ridge')
    original['warnings'] = ['Guide anchor(s) 2 create turns sharper than 90°.']
    reversed_line = reverse_feature(terrain, original)
    assert reversed_line['coordinates'] == original['coordinates'][::-1]
    assert reversed_line['metrics']['sharp_guide_indices'] == [3]
    assert any(w.startswith('Guide anchor(s) 3 ') for w in reversed_line['warnings'])
    assert not any(w.startswith('Guide anchor(s) 2 ') for w in reversed_line['warnings'])


@pytest.mark.parametrize('protection', ['edited', 'neighbor'])
@pytest.mark.parametrize('change', ['move', 'delete'])
def test_shared_protected_junction_guard_rejects_disconnect_without_mutation(terrain, protection, change):
    from tracertool.editing import validate_shared_junction_edit
    original = feature(terrain)
    neighbor = feature(terrain, ((20, 10), (20, 20)))
    protected = original if protection == 'edited' else neighbor
    protected['fixed_anchor_indices'] = [1 if protection == 'edited' else 0]
    proposal = deepcopy(original)
    if change == 'move':
        proposal['coordinates'][1] = [*terrain.xy(20, 12), 1]
    else:
        del proposal['coordinates'][1]
    before = deepcopy([original, proposal, neighbor])
    with pytest.raises(ValueError, match='protected.*junction'):
        validate_shared_junction_edit(original, [proposal], [original, neighbor])
    assert [original, proposal, neighbor] == before


def test_shared_junction_guard_allows_unchanged_reverse_and_split(terrain):
    from tracertool.editing import validate_shared_junction_edit
    original = feature(terrain)
    original['fixed_anchor_indices'] = [1]
    neighbor = feature(terrain, ((20, 10), (20, 20)))
    validate_shared_junction_edit(original, [reverse_feature(terrain, original)], [original, neighbor])
    validate_shared_junction_edit(original, list(split_feature(terrain, original, 1)), [original, neighbor])
    # Pure edits conservatively preserve locks even without collection context.
    with pytest.raises(ValueError, match='protected.*junction'):
        delete_vertex(terrain, original, 1)


def test_protection_survives_harmless_edit_save_load_and_repeated_edit(terrain, tmp_path):
    original = feature(terrain)
    original['fixed_anchor_indices'] = [1]
    moved = move_vertex(terrain, original, 3, terrain.xy(40, 12))
    assert moved['protected_junctions'] == [original['coordinates'][1][:2]]
    path = tmp_path / 'protected.json'
    save_project(path, terrain.path, [moved], {})
    restored = load_project(path)['features'][0]
    with pytest.raises(ValueError, match='protected.*junction'):
        delete_vertex(terrain, restored, 1)


def test_protection_partition_join_correction_and_neighbor_guard(terrain):
    from tracertool.editing import validate_shared_junction_edit
    original = feature(terrain)
    original['fixed_anchor_indices'] = [0, 1, 3]
    first, second = split_feature(terrain, original, 1)
    assert first['protected_junctions'] == [p[:2] for p in original['coordinates'][:2]]
    assert second['protected_junctions'] == [original['coordinates'][i][:2] for i in (1, 3)]
    joined = join_features(terrain, first, second, 0)
    assert joined['protected_junctions'] == [original['coordinates'][i][:2] for i in (0, 1, 3)]
    replacement = TraceResult(deepcopy(joined['coordinates']), [])
    corrected = replace_segment(terrain, joined, 0, 3, replacement, TraceParams())
    assert corrected['protected_junctions'] == joined['protected_junctions']
    replacement.coordinates.pop(1)
    with pytest.raises(ValueError, match='protected.*junction'):
        replace_segment(terrain, joined, 0, 3, replacement, TraceParams())
    neighbor = feature(terrain, ((20, 10), (20, 20)))
    proposal = deepcopy(neighbor)
    proposal['coordinates'][0] = [*terrain.xy(21, 10), 1]
    with pytest.raises(ValueError, match='protected.*junction'):
        validate_shared_junction_edit(neighbor, [proposal], [neighbor, corrected])


@pytest.mark.parametrize('field,value', [
    ('engine_evidence', []), ('metrics', {'diagnostics': [None]}),
    ('metrics', {'engine': 'stream_auto'}),
])
def test_edits_reject_malformed_engine_metadata_without_mutation(terrain, field, value):
    original = feature(terrain)
    original[field] = value
    before = deepcopy(original)
    with pytest.raises(ValueError, match='engine|diagnostic'):
        move_vertex(terrain, original, 3, terrain.xy(40, 12))
    assert original == before


def test_correction_rejects_malformed_result_diagnostics(terrain):
    original = feature(terrain)
    result = TraceResult(deepcopy(original['coordinates']), [], metrics={'diagnostics': [None]})
    with pytest.raises(ValueError, match='diagnostic'):
        replace_segment(terrain, original, 0, 3, result, TraceParams())


def test_guard_rejects_silent_protection_metadata_loss(terrain):
    from tracertool.editing import validate_shared_junction_edit
    original = feature(terrain)
    original['protected_junctions'] = [original['coordinates'][1][:2]]
    neighbor = feature(terrain, ((20, 10), (20, 20)))
    proposal = deepcopy(original)
    proposal.pop('protected_junctions')
    with pytest.raises(ValueError, match='protected.*junction'):
        validate_shared_junction_edit(original, [proposal], [original, neighbor])


def test_zero_reconstructed_guide_tolerance_retains_original_bends(terrain):
    original = feature(terrain, ((10, 10), (11, 10.2), (12, 10), (13, 10.2), (14, 10)))
    guides = reconstruct_anchors(terrain, original, tolerance_pixels=0)
    assert guides == [p[:2] for p in original['coordinates']]


def test_editing_snapped_features_clears_or_remaps_guide_locks(terrain, tmp_path):
    original = feature(terrain)
    original['fixed_anchor_indices'] = [0, 1]
    reversed_line = reverse_feature(terrain, original)
    assert reversed_line['fixed_anchor_indices'] == [2, 3]
    assert reverse_feature(terrain, reversed_line)['fixed_anchor_indices'] == [0, 1]
    with pytest.raises(ValueError, match='protected.*junction'):
        move_vertex(terrain, original, 1, terrain.xy(20, 12))
    with pytest.raises(ValueError, match='protected.*junction'):
        delete_vertex(terrain, original, 1)
    changed = [move_vertex(terrain, original, 3, terrain.xy(40, 12)),
               insert_vertex(terrain, original, 1, terrain.xy(25, 10)),
               *split_feature(terrain, original, 1)]
    for index, updated in enumerate(changed):
        assert 'anchors' not in updated and 'fixed_anchor_indices' not in updated
        path = tmp_path / f'edited-{index}.tracer.json'
        save_project(path, terrain.path, [updated], {})
        assert load_project(path)['features'] == [updated]
    assert original['fixed_anchor_indices'] == [0, 1]
