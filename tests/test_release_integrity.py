"""Release archives must be bounded, attributable and data-free."""
import importlib.util
import subprocess
from pathlib import Path
from zipfile import ZipFile, ZipInfo
import pytest

ROOT = Path(__file__).resolve().parents[1]

def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_portable_inventory_rejects_duplicates(tmp_path):
    verify = script('verify_portable')
    path = tmp_path / 'bad.zip'
    with ZipFile(path, 'w') as archive:
        archive.writestr('TracerTool/readme.txt', 'a')
        with pytest.warns(UserWarning):
            archive.writestr('TracerTool/readme.txt', 'b')
    with ZipFile(path) as archive, pytest.raises(ValueError, match='duplicate'):
        verify.validate_inventory(archive)


@pytest.mark.parametrize('name', ['../evil', 'TracerTool/../evil', 'TracerTool/input.shp',
                                 'TracerTool/data.gpkg', 'TracerTool/dem.tif', 'evil.exe',
                                 'TracerTool/C:/evil', 'TracerTool\\..\\evil'])
def test_portable_inventory_rejects_unsafe_or_data_members(tmp_path, name):
    verify = script('verify_portable')
    path = tmp_path / 'bad.zip'
    with ZipFile(path, 'w') as archive:
        archive.writestr(name, 'a')
    with ZipFile(path) as archive, pytest.raises(ValueError):
        verify.validate_inventory(archive)


def test_portable_inventory_bounded_and_no_symlink(tmp_path):
    verify = script('verify_portable')
    path = tmp_path / 'bad.zip'
    info = ZipInfo('TracerTool/link')
    info.create_system = 3
    info.external_attr = (0o120777 << 16)
    with ZipFile(path, 'w') as archive:
        archive.writestr(info, 'target')
    with ZipFile(path) as archive, pytest.raises(ValueError, match='symlink'):
        verify.validate_inventory(archive)
    with ZipFile(path, 'w') as archive:
        archive.writestr('TracerTool/readme.txt', 'abc')
    with ZipFile(path) as archive, pytest.raises(ValueError, match='size'):
        verify.validate_inventory(archive, max_bytes=2)


def test_release_snapshot_covers_config_and_build_scripts():
    build = script('build_portable')
    snapshot = build.release_snapshot(ROOT)
    assert len(snapshot['git_commit']) == 40
    assert len(snapshot['git_tree']) == 40
    for path in ['pyproject.toml', 'scripts/tracertool.spec', 'scripts/rasterio_runtime.py',
                 'src/tracertool/tracing.py', 'docs/USER_GUIDE.md']:
        assert len(snapshot['files'][path]) == 64


@pytest.mark.parametrize('alias', ['TracerTool/./a', 'TracerTool//a', 'TracerTool/a.',
                                  'TracerTool/a ', 'TracerTool/CON', 'TracerTool/A'])
def test_extraction_aliases_rejected(tmp_path, alias):
    verify = script('verify_portable')
    path = tmp_path / 'alias.zip'
    with ZipFile(path, 'w') as archive:
        archive.writestr('TracerTool/a', 'first')
        archive.writestr(alias, 'second')
    with ZipFile(path) as archive, pytest.raises(ValueError):
        verify.validate_inventory(archive)


def test_provenance_requires_strict_smoke_and_full_identity():
    verify = script('verify_portable')
    info = {'frozen_smoke_passed': 'false', 'release_snapshot': {'git_commit': 'a'*40}}
    with pytest.raises(ValueError):
        verify.validate_provenance(info, 'a'*40)
    info['frozen_smoke_passed'] = True
    with pytest.raises(ValueError):
        verify.validate_provenance(info, 'a'*40)
    info['release_snapshot'].update(git_tree='b'*40, files={'pyproject.toml': 'c'*64})
    verify.validate_provenance(info, 'a'*40)
    with pytest.raises(ValueError):
        verify.validate_provenance(info, 'd'*40)


def test_dirty_release_inputs_rejected(tmp_path):
    build = script('build_portable')
    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)
    git('init')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.invalid')
    (tmp_path/'README.md').write_text('original')
    git('add', 'README.md')
    git('commit', '-m', 'initial')
    build.require_clean_source(tmp_path)
    (tmp_path/'README.md').write_text('changed')
    with pytest.raises(ValueError, match='clean'):
        build.require_clean_source(tmp_path)


def test_untracked_documentation_not_copied(tmp_path):
    build = script('build_portable')
    (tmp_path/'docs').mkdir()
    (tmp_path/'docs'/'tracked.md').write_text('public')
    (tmp_path/'docs'/'untracked.md').write_text('must not ship')
    for name in ('LICENSE', 'README.md', 'CHANGELOG.md', 'AI_DISCLOSURE.md',
                 'CONTRIBUTING.md', 'SECURITY.md', 'THIRD_PARTY_NOTICES.md'):
        (tmp_path/name).write_text('public')
    output = tmp_path/'output'
    output.mkdir()
    build.collect_documentation(tmp_path, output, tracked={'docs/tracked.md'})
    assert (output/'docs'/'tracked.md').exists()
    assert not (output/'docs'/'untracked.md').exists()
