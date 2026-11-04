# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

from pathlib import Path
import importlib.util
root = Path(SPECPATH).parent
# Public-asset policy, loaded by file path (same module the builder and scanner use).
_policy_spec = importlib.util.spec_from_file_location('minidraconia_asset_policy', str(Path(SPECPATH) / 'asset_policy.py'))
asset_policy = importlib.util.module_from_spec(_policy_spec)
_policy_spec.loader.exec_module(asset_policy)
# 'licenses' (obsolete Qwen model licences) is NOT bundled: no Qwen runtime or weights ship.
# The inherited GPL LICENSE is still bundled below; source provenance stays in the repository.
datas = [(str(root / name), name) for name in ('data',)]
_violations = []
for path in sorted((root/'res').rglob('*')):
    if not path.is_file():
        continue
    rel = path.relative_to(root)
    _rule = asset_policy.violation(rel.as_posix())
    if _rule:
        _violations.append('%s %s' % (_rule, rel.as_posix()))
        continue
    if rel.parts[:2] == ('res', 'role') and len(rel.parts) > 2 and rel.parts[2] not in {'Draconia', 'sys'}:
        continue
    datas.append((str(path), str(rel.parent)))
if _violations:
    # Never silently skip: an unapproved clip or the inherited pet folder in the tree is a build error.
    raise RuntimeError('asset policy violation, refusing to build: ' + '; '.join(_violations[:20]))
datas += [(str(root/'LICENSE'), '.'), (str(root/'DyberPet/brain/alma-draconia-v6-compact-en.md'), 'DyberPet/brain')]
# Single version file of the repository, bundled at the resource root (read by DyberPet.version).
datas += [(str(root.parent/'VERSION'), '.')]
binaries = []
hiddenimports = ['pynput.mouse._win32', 'pynput.keyboard._win32']
hiddenimports += [m for m in collect_submodules('DyberPet') if m != 'DyberPet.brain.local']
# portable_entry.py starts the UI with importlib.import_module('run_DyberPet'). That
# module lives at the engine root (NOT inside the DyberPet package), so collecting
# DyberPet.* never included it and a frozen normal launch exited 1 with
# "ImportError: No module named run_DyberPet". Collect it explicitly (pathex has root).
hiddenimports += ['run_DyberPet', 'DyberPet.startup_smoke']
tmp_ret = collect_all('qfluentwidgets')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('qframelesswindow')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tendo')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('apscheduler')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [str(root / 'packaging/portable_entry.py')],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['DyberPet.brain.local', 'onnxruntime', 'kokoro_onnx', 'scipy', 'matplotlib', 'pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MiniDraconia',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MiniDraconia',
)
