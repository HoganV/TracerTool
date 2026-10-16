"""Experimental Auto desktop boundary and source-integrity acceptance."""
import copy
import sys
import types
import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_app import qt_app, terrain_path, window, wait_idle, accept_line, map_position
from tracertool.tracing import TraceResult


def auto_result(terrain, anchors):
    cells = [list(a) for a in anchors]
    coordinates = [[*terrain.xy(*a), terrain.sample(*terrain.xy(*a))] for a in anchors]
    return TraceResult(coordinates, cells, {
        'engine': 'stream_auto', 'engine_version': 1, 'status': 'ambiguous',
        'analysis_resolution': 1., 'effective_config': {'scale': 3},
        'diagnostics': [{'code': 'weak_evidence', 'message': 'Review weak terrain evidence',
                         'location': coordinates[0][:2]}]}, [])


def select_auto(window):
    window.set_tool('stream')
    window.stream_engine.setCurrentIndex(window.stream_engine.findData('stream_auto'))


def test_shared_protected_junction_blocks_vertex_move_and_feature_delete(window):
    original = accept_line(window)
    neighbor = copy.deepcopy(original)
    neighbor['id'] = 'protected-neighbor'
    neighbor['fixed_anchor_indices'] = [0]
    window.features.append(neighbor)
    before = copy.deepcopy(window.features)
    history = copy.deepcopy(window.history)
    window.preferences['editing']['snap_enabled'] = False
    window.move_vertex(0, 10, 42)
    assert window.features == before
    assert window.history == history
    assert 'protected junction' in window.test_errors.pop()
    window.delete_feature()
    assert window.features == before
    assert window.history == history
    assert 'protected junction' in window.test_errors.pop()


def test_restored_edit_rechecks_engine_before_dispatch(window, monkeypatch):
    original = accept_line(window)
    window.begin_retrace()
    window.features[0]['engine_version'] = 99
    monkeypatch.setattr('tracertool.app.trace', lambda *a, **k: pytest.fail('unsupported dispatch'))
    window.trace_preview(); wait_idle(window)
    assert window.preview is None
    assert 'engine' in window.test_errors.pop().lower()
    window.clear_draft()


def test_draft_unknown_version_rejected(window):
    settings = window.settings()
    settings['draft'] = {'kind': 'stream', 'engine': 'stream_auto', 'engine_version': 99}
    with pytest.raises(ValueError, match='engine'):
        window.validate_settings(settings)


def test_packaged_smoke_runs_real_auto_and_preserves_success_message(qt_app, monkeypatch, capsys):
    from tracertool import app, stream_auto
    calls = []
    real = stream_auto.trace_auto
    def checked(*args, **kwargs):
        result = real(*args, **kwargs)
        calls.append(result)
        return result
    monkeypatch.setattr(stream_auto, 'trace_auto', checked)
    assert app.smoke_test(qt_app) == 0
    assert calls and calls[0].metrics['engine'] == 'stream_auto'
    assert 'TracerTool smoke test passed' in capsys.readouterr().out


def test_shared_junction_retrace_rejected_without_history_change(window):
    original = accept_line(window)
    neighbor = copy.deepcopy(original)
    neighbor['id'] = 'protected-neighbor'
    neighbor['fixed_anchor_indices'] = [0]
    window.features.append(neighbor)
    window.begin_retrace()
    result = auto_result(window.terrain, [(10, 42), (70, 40)])
    window.install_preview(result)
    before, history = copy.deepcopy(window.features), copy.deepcopy(window.history)
    window.accept_preview()
    assert window.features == before and window.history == history
    assert 'protected junction' in window.test_errors.pop()
    window.clear_draft()


def test_real_auto_on_reduced_display_grid_retains_native_xyz(window, terrain_path):
    import numpy as np
    window.install_terrain(window.load_terrain_image(terrain_path, max_dimension=20))
    select_auto(window)
    terrain = window.terrain
    assert terrain.metadata['resampled']
    before = terrain.data.copy()
    native = [[500040.5, 4499991.5], [500040.5, 4499929.5]]
    window.anchors = [terrain.rc(*p) for p in native]
    window._anchor_exact = dict(enumerate(native))
    window._fixed_anchor_indices = {0, 1}
    window.trace_preview(); wait_idle(window)
    assert window.preview is not None, window.test_errors
    result = window.preview
    assert result.metrics['analysis_resolution'] == 1
    assert result.coordinates[0][:2] == native[0]
    assert result.coordinates[-1][:2] == native[-1]
    assert [p[2] for p in result.coordinates] == terrain.sample_many([p[:2] for p in result.coordinates])
    window.accept_preview()
    assert window.features[0]['engine'] == 'stream_auto'
    np.testing.assert_array_equal(terrain.data, before)


@pytest.mark.parametrize('operation', ['insert', 'delete', 'reverse', 'split', 'join'])
def test_all_edit_install_paths_use_junction_guard(window, monkeypatch, operation):
    from tracertool import editing
    original = accept_line(window)
    if operation == 'join':
        neighbor = copy.deepcopy(original)
        neighbor['id'] = 'join-neighbor'
        window.features.append(neighbor)
        window.refresh_features()
        for i in range(window.feature_list.count()):
            window.feature_list.item(i).setSelected(True)
    before, history = copy.deepcopy(window.features), copy.deepcopy(window.history)
    calls = []
    def reject(feature, replacements, features):
        calls.append((feature, replacements, features))
        raise ValueError('protected junction test rejection')
    monkeypatch.setattr(editing, 'validate_shared_junction_edit', reject)
    window.selected_vertex = 1
    if operation == 'insert':
        window.insert_vertex(0, 9, 41)
    elif operation == 'delete':
        window.delete_vertex()
    elif operation == 'reverse':
        window.reverse_line()
    elif operation == 'split':
        window.split_line()
    else:
        window.join_lines()
    assert calls
    assert window.features == before and window.history == history
    assert 'protected junction' in window.test_errors.pop()


def test_auto_is_opt_in_dispatches_lazily_without_kind_or_legacy_fallback(window, monkeypatch):
    assert window.stream_engine.currentData() == 'legacy'
    select_auto(window)
    calls = []
    def solver(terrain, anchors, params=None, cancel=None, fixed_anchor_indices=None):
        calls.append((terrain, anchors, params, fixed_anchor_indices))
        return auto_result(terrain, anchors)
    monkeypatch.setitem(sys.modules, 'tracertool.stream_auto', types.SimpleNamespace(trace_auto=solver))
    monkeypatch.setattr('tracertool.app.trace', lambda *a, **k: pytest.fail('silent legacy fallback'))
    window.add_anchor(8, 40); window.add_anchor(70, 40)
    window.trace_preview(); wait_idle(window)
    assert len(calls) == 1 and window.preview is not None
    assert window.preview.metrics['status'] == 'ambiguous'
    assert window.settings()['stream_engine'] == 'stream_auto'
    assert window.settings()['draft']['engine'] == 'stream_auto'
    assert not window.param_widgets['corridor'].isEnabled()
    assert window.param_widgets['spacing'].isEnabled()
    assert 'weak terrain evidence' in window.qa_label.text()
    assert 'Analysis resolution' in window.metrics_label.text()
    window.clear_draft()


def test_engine_settings_roundtrip_and_retrace_uses_feature_engine(window, tmp_path, monkeypatch):
    select_auto(window)
    monkeypatch.setitem(sys.modules, 'tracertool.stream_auto', types.SimpleNamespace(trace_auto=lambda t, a, *args, **kw: auto_result(t, a)))
    window.add_anchor(8, 40); window.add_anchor(70, 40)
    saved = tmp_path / 'auto.tracer.json'
    window.project_path = str(saved)
    assert window.save()
    window.open_project(str(saved)); wait_idle(window)
    assert window.stream_engine.currentData() == 'stream_auto'
    assert window.settings()['draft']['engine'] == 'stream_auto'
    window.trace_preview(); wait_idle(window)
    window.accept_preview()
    original = copy.deepcopy(window.features[0])
    assert original['engine'] == 'stream_auto'
    window.stream_engine.setCurrentIndex(0)
    window.begin_retrace()
    assert window.trace_engine() == 'stream_auto'
    window.trace_preview(); wait_idle(window)
    window.accept_preview()
    assert window.features[0]['metrics']['status'] == 'ambiguous'
    assert window.features[0]['metrics']['diagnostics'] == original['metrics']['diagnostics']
    window.undo()
    assert window.features == [original]


@pytest.mark.parametrize('engine,version', [('unknown', 1), ('stream_auto', 2)])
def test_unsupported_feature_engine_cannot_retrace_or_correct(window, engine, version):
    feature = accept_line(window)
    window.features[0]['engine'], window.features[0]['engine_version'] = engine, version
    window.begin_retrace()
    assert window.edit_target is None and not window.anchors
    assert window.test_errors and 'engine' in window.test_errors[-1].lower()
    window.test_errors.clear()
    window.begin_segment()
    assert window.canvas.mode != 'segment'
    window.test_errors.clear()


def test_unknown_draft_engine_is_rejected_before_install(window):
    settings = window.settings()
    settings['stream_engine'] = 'future_solver'
    with pytest.raises(ValueError, match='engine'):
        window.validate_settings(settings)
    settings['stream_engine'] = 'legacy'
    settings['draft'] = {'kind': 'stream', 'engine': 'future_solver'}
    with pytest.raises(ValueError, match='engine'):
        window.validate_settings(settings)


def test_auto_fixed_fractional_endpoints_restored_even_without_cell_match(window):
    select_auto(window)
    window.anchors = [(8.25, 40.2), (70.2, 40.3)]
    window._anchor_exact = {i: list(window.terrain.xy(*a)) for i, a in enumerate(window.anchors)}
    window._fixed_anchor_indices = {0, 1}
    result = auto_result(window.terrain, [(8, 40), (70, 40)])
    result.cells = [[8.1, 40], [70.1, 40]]
    window.install_preview(result)
    assert result.coordinates[0][:2] == window._anchor_exact[0]
    assert result.coordinates[-1][:2] == window._anchor_exact[1]
    assert result.metrics['status'] == 'ambiguous'
    window.clear_draft()


def test_auto_core_failure_never_falls_back_or_changes_accepted_geometry(window, monkeypatch):
    original = accept_line(window)
    select_auto(window)
    def fail(*a, **kw):
        raise ValueError('No safe source-native route')
    monkeypatch.setitem(sys.modules, 'tracertool.stream_auto', types.SimpleNamespace(trace_auto=fail))
    monkeypatch.setattr('tracertool.app.trace', lambda *a, **k: pytest.fail('fallback'))
    window.add_anchor(10, 42); window.add_anchor(65, 42)
    window.trace_preview(); wait_idle(window)
    assert window.preview is None and window.features == [original]
    assert 'No safe' in window.test_errors[-1]
    window.test_errors.clear()
    window.clear_draft()


def test_cancelled_and_stale_auto_jobs_cannot_install_preview(window, monkeypatch):
    select_auto(window)
    entered, release = threading.Event(), threading.Event()
    def solver(t, anchors, *a, **kw):
        entered.set()
        assert release.wait(5)
        return auto_result(t, anchors)
    monkeypatch.setitem(sys.modules, 'tracertool.stream_auto', types.SimpleNamespace(trace_auto=solver))
    window.add_anchor(8, 40); window.add_anchor(70, 40)
    window.trace_preview()
    assert entered.wait(5)
    window.cancel_job()
    release.set(); wait_idle(window)
    assert window.preview is None and not window.features
    release.clear(); entered.clear()
    window.trace_preview()
    assert entered.wait(5)
    window.invalidate_preview()
    release.set(); wait_idle(window)
    assert window.preview is None
    window.clear_draft()


def test_locked_canvas_allows_navigation_but_never_geometry_signals(window):
    window.set_tool('stream')
    window.add_anchor(8, 40); window.add_anchor(70, 40)
    before = copy.deepcopy(window.anchors)
    canvas = window.canvas
    canvas.locked = True
    signals = []
    canvas.anchorAdded.connect(lambda *a: signals.append(a))
    canvas.vertexInsertRequested.connect(lambda *a: signals.append(a))
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=map_position(window, 30, 40))
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=map_position(window, 40, 40))
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    canvas.scale(2, 2)
    assert canvas.transform().m11() > 1
    QTest.keyClick(canvas, Qt.Key.Key_F)
    assert canvas.transform().m11() < 10
    assert not signals and window.anchors == before
    canvas.locked = False
    window.clear_draft()


def test_auto_preview_rejects_source_nodata_segment(window, monkeypatch):
    select_auto(window)
    result = auto_result(window.terrain, [(8, 40), (70, 40)])
    original = window.terrain.sample_many
    def sample_many(self, points):
        points = list(points)
        values = original(points)
        return [None if 30 <= window.terrain.rc(x, y)[0] <= 40 else z
                for (x, y), z in zip(points, values)]
    monkeypatch.setattr(type(window.terrain), 'sample_many', sample_many)
    with pytest.raises(ValueError, match='NoData|invalid|nodata'):
        window.install_preview(result)
    assert window.preview is None


def test_auto_ignores_legacy_force_guides_control(window):
    select_auto(window)
    window.relax_guides.setChecked(False)
    window.anchors = [(8, 40), (70, 40)]
    window._anchor_exact = {0: list(window.terrain.xy(8.2, 40.3))}
    result = auto_result(window.terrain, window.anchors)
    before = copy.deepcopy(result.coordinates)
    window.install_preview(result)
    assert result.coordinates == before
    window.clear_draft()


def test_real_auto_preview_accept_correct_undo_and_retrace_evidence(window):
    select_auto(window)
    window.add_anchor(8, 40); window.add_anchor(70, 40)
    window.trace_preview(); wait_idle(window)
    assert window.preview is not None, window.test_errors
    assert window.preview.metrics['engine'] == 'stream_auto'
    window.accept_preview()
    original = copy.deepcopy(window.features[0])
    assert original['engine'] == 'stream_auto'
    window.begin_segment(); window.pick_segment_boundary(1)
    window.pick_segment_boundary(len(original['coordinates']) - 2)
    window.trace_preview(); wait_idle(window)
    assert window.preview is not None, window.test_errors
    window.accept_preview()
    corrected = copy.deepcopy(window.features[0])
    assert corrected['coordinates'][0] == original['coordinates'][0]
    assert corrected['coordinates'][-1] == original['coordinates'][-1]
    assert corrected['metrics']['status'] == 'stale'
    window.undo(); assert window.features == [original]
    window.redo(); assert window.features == [corrected]
    window.select_feature(corrected['id'])
    window.begin_retrace(); window.trace_preview(); wait_idle(window)
    window.accept_preview()
    retraced = window.features[0]
    assert not retraced['metrics'].get('evidence_stale', False)
    assert not retraced.get('engine_evidence', {}).get('stale', False)


def test_auto_selection_never_changes_manual_dispatch_or_source_arrays(window, monkeypatch):
    select_auto(window)
    window.clear_draft()
    original = window.terrain.data.copy()
    def fail(*a, **kw):
        pytest.fail('Auto solver called for Manual line')
    monkeypatch.setitem(sys.modules, 'tracertool.stream_auto', types.SimpleNamespace(trace_auto=fail))
    feature = accept_line(window, kind='manual')
    assert feature['engine'] == 'legacy'
    assert window.settings()['stream_engine'] == 'stream_auto'
    import numpy as np
    np.testing.assert_array_equal(window.terrain.data, original)
    assert len(window.features) == 1


def test_auto_can_trace_distinct_native_guides_inside_one_working_cell(window, monkeypatch):
    select_auto(window)
    window.preferences['editing']['raster_snap'] = False
    window.add_anchor(8.1, 40.1); window.add_anchor(8.4, 40.4)
    monkeypatch.setitem(sys.modules, 'tracertool.stream_auto', types.SimpleNamespace(trace_auto=lambda t, a, *args, **kw: auto_result(t, a)))
    window.trace_preview(); wait_idle(window)
    assert window.preview is not None, window.test_errors
    window.clear_draft()
