"""Real solver publication boundaries must retain the loaded source snapshot."""
import copy
import os

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from test_app import qt_app, terrain_path, window, wait_idle
from tracertool.stream_auto import trace_auto
from tracertool.terrain import Terrain


def rewrite(path):
    before = os.stat(path)
    with rasterio.open(path, 'r+') as src:
        data = src.read(1)
        src.write(data + 1, 1)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))


def real_result(window):
    window.set_tool('stream')
    window.anchors = [(8, 40), (70, 40)]
    return trace_auto(window.terrain, window.anchors)


@pytest.mark.parametrize('boundary', ['install', 'accept'])
def test_changed_source_cannot_publish_real_auto(window, boundary):
    result = real_result(window)
    if boundary == 'accept':
        window.install_preview(result)
    before = copy.deepcopy((window.features, window.history, window.future))
    coordinates = copy.deepcopy(result.coordinates)
    rewrite(window.terrain.path)
    if boundary == 'install':
        with pytest.raises(ValueError, match='[Cc]hanged'):
            window.install_preview(result)
        assert window.preview is None
    else:
        window.accept_preview()
        assert 'changed' in window.test_errors.pop().lower()
        assert window.preview is result
    assert (window.features, window.history, window.future) == before
    assert result.coordinates == coordinates


def vrt_terrain(tmp_path):
    from rasterio.shutil import copy as raster_copy
    rows, cols = np.mgrid[:60, :60]
    data = (60 - rows + (cols - 30) ** 2).astype('float32')
    path = tmp_path / 'source.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=60, height=60, count=1,
                       dtype='float32', crs='EPSG:32615',
                       transform=from_origin(500000, 4500000, 1, 1), nodata=-9999) as src:
        src.write(data, 1)
    vrt = tmp_path / 'source.vrt'
    raster_copy(path, vrt, driver='VRT')
    return path, vrt


def test_vrt_load_captures_dependencies_and_rejects_changed_cached_z(tmp_path):
    path, vrt = vrt_terrain(tmp_path)
    terrain = Terrain.load(vrt)
    assert terrain._source_data is not None
    rewrite(path)
    with pytest.raises(ValueError, match='[Cc]hanged'):
        terrain.check_source_unchanged()
    assert str(path) in {item['path'] for item in terrain.metadata['source_dependencies']}


def test_vrt_dependency_changed_before_solve_is_rejected(tmp_path):
    path, vrt = vrt_terrain(tmp_path)
    terrain = Terrain.load(vrt)
    rewrite(path)
    with pytest.raises(ValueError, match='[Cc]hanged'):
        trace_auto(terrain, [(8, 30), (50, 30)])


@pytest.mark.parametrize('cached', [True, False])
def test_sampling_refuses_changed_load_snapshot(tmp_path, cached):
    path, vrt = vrt_terrain(tmp_path)
    terrain = Terrain.load(vrt)
    if not cached:
        terrain._source_data = None
    rewrite(path)
    with pytest.raises(ValueError, match='[Cc]hanged'):
        terrain.sample_many([terrain.xy(8, 30)])


def test_ui_rejects_changed_vrt_dependency_before_solver_dispatch(window, tmp_path, monkeypatch):
    path, vrt = vrt_terrain(tmp_path)
    window.install_terrain(window.load_terrain_image(vrt))
    window.set_tool('stream')
    window.stream_engine.setCurrentIndex(window.stream_engine.findData('stream_auto'))
    window.anchors = [(8, 30), (50, 30)]
    calls = []
    def solve(*args, **kwargs):
        calls.append(True)
        return trace_auto(*args, **kwargs)
    monkeypatch.setattr('tracertool.stream_auto.trace_auto', solve)
    rewrite(path)
    before = copy.deepcopy((window.features, window.history))
    window.trace_preview()
    wait_idle(window)
    assert 'changed' in window.test_errors.pop().lower()
    assert not calls
    assert window.preview is None
    assert (window.features, window.history) == before


def test_preview_rejects_new_solver_identity_against_old_load_snapshot(window, tmp_path):
    path, vrt = vrt_terrain(tmp_path)
    window.install_terrain(window.load_terrain_image(vrt))
    window.set_tool('stream')
    window.anchors = [(8, 30), (50, 30)]
    rewrite(path)
    # A fresh solver result must not validate the old window's cached source Z.
    fresh = Terrain.load(vrt)
    result = trace_auto(fresh, window.anchors)
    before = copy.deepcopy((window.features, window.history, result.coordinates))
    with pytest.raises(ValueError, match='[Cc]hanged'):
        window.install_preview(result)
    assert (window.features, window.history, result.coordinates) == before
    assert window.preview is None


def test_native_auto_path_next_to_display_masked_hole_is_accepted(window, tmp_path):
    path, _ = vrt_terrain(tmp_path)
    with rasterio.open(path, 'r+') as src:
        data = src.read(1)
        data[30, 31] = -9999
        src.write(data, 1)
    window.install_terrain(window.load_terrain_image(path, max_dimension=10))
    window.set_tool('stream')
    terrain = window.terrain
    guides = [(500030.5, 4499991.5), (500030.5, 4499949.5)]
    window.anchors = [terrain.rc(*xy) for xy in guides]
    result = trace_auto(terrain, window.anchors, fixed_anchor_indices={0, 1})
    assert not terrain.valid[5, 5]
    assert all(p[0] == 500030.5 for p in result.coordinates)
    window.install_preview(result)
    window.accept_preview()
    assert len(window.features) == 1
    assert window.features[0]['coordinates'] == result.coordinates
    assert [p[2] for p in result.coordinates] == terrain.sample_many([p[:2] for p in result.coordinates])


@pytest.mark.parametrize('bad_z', [float('nan'), float('inf')])
def test_native_validator_still_rejects_nonfinite_xyz(window, bad_z):
    result = real_result(window)
    result.coordinates[0][2] = bad_z
    with pytest.raises(ValueError, match='finite'):
        window.install_preview(result)
    assert window.preview is None


@pytest.mark.parametrize('boundary', ['load', 'sample'])
def test_read_rejects_dependency_change_during_read(tmp_path, monkeypatch, boundary):
    path, vrt = vrt_terrain(tmp_path)
    terrain = Terrain.load(vrt) if boundary == 'sample' else None
    if terrain is not None:
        terrain._source_data = None
    real_open = rasterio.open
    class ChangingSource:
        def __init__(self, source):
            self.source = source
        def __getattr__(self, name):
            return getattr(self.source, name)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.source.close()
        def read(self, *args, **kwargs):
            data = self.source.read(*args, **kwargs)
            before = os.stat(path)
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
            return data
    monkeypatch.setattr('tracertool.terrain.rasterio.open',
                        lambda *a, **kw: ChangingSource(real_open(*a, **kw)))
    with pytest.raises(ValueError, match='[Cc]hanged'):
        if terrain is None:
            Terrain.load(vrt)
        else:
            terrain.sample_many([terrain.xy(8, 30)])
