"""Portable public build of MiniDraconia (Windows, Python 3.11): SCRIPTED offline only.

Builds with a normally installed PyInstaller (optionally an explicitly supplied
external buildtools folder), verifies the result and writes a versioned,
never-overwritten ZIP:

    python package_scripted.py --preflight-only
    python package_scripted.py [--buildtools <absolute folder>] [--allow-missing-docs]

No model, inference runtime, cloud provider, credentials or user state are
packaged. Nothing here is a legal determination (see LEGAL_NOTE).
"""
from pathlib import Path, PurePosixPath
import argparse
import base64
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent
SPEC = ROOT/'full-engine'/'packaging'/'MiniDraconia.spec'
TOP = 'MiniDraconia'
REQUIRED_DOCS = ('LICENSE', 'README.md', 'RELEASE-NOTES.md')
# Qt/PySide wheels: redistributable notice files MUST be found or the build fails.
QT_NOTICE_DISTRIBUTIONS = ('PySide6', 'PySide6_Essentials', 'PySide6_Addons', 'shiboken6')
# Other runtime distributions: notices are copied when present; absence is only recorded.
OTHER_NOTICE_DISTRIBUTIONS = ('PySide6_Fluent_Widgets', 'PySideSix_Frameless_Window', 'APScheduler', 'pynput', 'tendo',
                              'darkdetect', 'six', 'tzlocal', 'tzdata', 'numpy', 'pillow', 'pywin32')
LEGAL_NOTE = ('Notice files are copied as found in the installed distributions, and the Qt 6.5.3 reference texts are the '
              'actual upstream license texts and source references (each verified against its recorded size and sha256). '
              'This is not a legal determination of license compatibility, of completeness of notices for all Qt modules '
              'or third-party code, of redistribution rights, or of franchise/character/art/voice rights.')
# Version-matched upstream license texts committed in the repository (retrieved by the maintainer from
# pinned commits). The wheel metadata of Qt 6.5.3 lists only LicenseRef-Qt-Commercial.txt, which alone is
# NOT open-source notice coverage; these texts are collected in addition and verified before use.
QT_REFERENCE_DIR = ROOT/'third_party'/'qt-6.5.3'
QT_REFERENCE_VERSION = '6.5.3'
QT_REFERENCE_PROJECTS = {'pyside/pyside-setup': ('pyside-setup', '2f27264a7a07e3d175afadbe9cb1a543df40cd2f'),
                         'qt/qtbase': ('qtbase', '372eaedc5b8c771c46acc4c96e91bbade4ca3624')}
QT_REFERENCE_REQUIRED = ('pyside-setup/LGPL-3.0-only.txt', 'pyside-setup/GPL-3.0-only.txt',
                         'qtbase/LGPL-3.0-only.txt', 'qtbase/GPL-3.0-only.txt')
QT_REFERENCE_DEST = 'qt-6.5.3-reference'
QT_REFERENCE_NOTE = ('These are actual upstream license texts and source references for Qt/PySide 6.5.3, verified by size and sha256. '
                     'This is not a finding of license compatibility, not a statement that notices are complete for all Qt modules '
                     'or third-party code in the build, and not a statement about franchise, character, art or voice permissions.')
_REFERENCE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*\.txt$')
_HEX40, _HEX64 = re.compile(r'^[0-9a-f]{40}$'), re.compile(r'^[0-9a-f]{64}$')
NOT_VERIFIED = ['human visual/animation/audio review', 'third-party and character/art/voice rights',
                'fresh-machine install from requirements.txt', 'other Windows versions or Python versions than the build host']
BUILD_ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
_NOTICE_NAME = re.compile(r'^((licen[sc]es?|copying|notice|copyright)([._-].*)?|licenseref-.+)$', re.IGNORECASE)
_CODE_SUFFIXES = {'.py', '.pyc', '.pyi', '.qml', '.dll', '.so', '.pyd', '.js', '.h', '.hpp', '.cpp', '.c', '.html', '.json', '.xml'}
_SKIP_DIRS = {'__pycache__', '.git', 'work', 'dist', 'build', 'buildtools', '.venv', 'venv'}


ASSET_POLICY_FILE = ROOT/'full-engine'/'packaging'/'asset_policy.py'

def asset_policy():
    """The public-asset policy shared with the spec and the scanner; a missing file is a hard error."""
    spec = importlib.util.spec_from_file_location('minidraconia_asset_policy', ASSET_POLICY_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def record(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            h.update(block)
    return {'sha256':h.hexdigest(),'bytes':path.stat().st_size}

def build_environment(profile, buildtools=None):
    """Environment for the PyInstaller step. `buildtools=None` keeps the historical
    repo-local <repo>/buildtools folder; pass [] for a normally installed
    PyInstaller or a list of absolute folders for external buildtools."""
    extra = [ROOT/'buildtools'] if buildtools is None else list(buildtools)
    paths = [ROOT/'full-engine'] + extra
    return dict(os.environ, APPDATA=str(profile/'appdata'), LOCALAPPDATA=str(profile/'local'), MINIDRACONIA_TEST_PROFILE=str(profile), QT_QPA_PLATFORM='offscreen', MINIDRACONIA_MUTE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=os.pathsep.join(str(p) for p in paths), PYINSTALLER_CONFIG_DIR=str(profile/'pyinstaller-config'))

def qt_models_inventory():
    """Trust exact installed Qt files only after checking their wheel RECORD."""
    from importlib.metadata import distribution
    import base64
    inventory = {}
    for package in ('PySide6_Essentials', 'PySide6_Addons'):
        dist = distribution(package)
        for entry in dist.files or ():
            relative = entry.as_posix()
            if not relative.startswith('PySide6/qml/QtQml/Models/'):
                continue
            source = Path(dist.locate_file(entry))
            if source.is_symlink() or any(p.is_symlink() for p in source.parents):
                raise RuntimeError('Symlink in installed Qt provenance: '+relative)
            item = record(source)
            digest = base64.urlsafe_b64encode(bytes.fromhex(item['sha256'])).decode().rstrip('=')
            if not entry.hash or entry.hash.mode != 'sha256' or digest != entry.hash.value or item['bytes'] != entry.size:
                raise RuntimeError('Qt wheel RECORD mismatch: '+relative)
            inventory['_internal/'+relative] = dict(item, source=str(source), distribution=dist.metadata['Name'], version=dist.version)
    if not inventory:
        raise RuntimeError('No verified Qt Models package resources')
    return inventory

def forbidden_artifact(name, path=None, qt_inventory=None):
    from pathlib import PurePosixPath
    if '\\' in name or ':' in name or name.startswith('/') or '..' in PurePosixPath(name).parts:
        return True
    if asset_policy().violation(name):
        return True
    low = '/' + name.lower()
    if Path(name).suffix.lower() in {'.gguf','.onnx','.safetensors','.pt','.pth'}:
        return True
    if any(x in low for x in ['llama-server','ollama','/runtime/','/.env','/profile/','/profiles/','credentials','secrets']):
        return True
    if path is not None:
        path = Path(path)
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            return True
    if '/models/' in low:
        inventory = qt_models_inventory() if qt_inventory is None else qt_inventory
        item = inventory.get(name)
        if item is None:
            return True
        candidate = Path(item['source']) if path is None else path
        if candidate.is_symlink() or not candidate.is_file():
            return True
        actual = record(candidate)
        return actual != {key:item[key] for key in ('sha256','bytes')}
    return False


# --- version, naming, options ---------------------------------------------------------

def read_version(root=ROOT):
    sys.path.insert(0, str(Path(root)/'full-engine'))
    try:
        from DyberPet.version import read_version as engine_read_version
        return engine_read_version(Path(root)/'full-engine')
    finally:
        sys.path.remove(str(Path(root)/'full-engine'))

def new_build_id():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]

def archive_name(version, build_id, docs_complete):
    label = '' if docs_complete else 'INCOMPLETE-DOCS-'
    return 'MiniDraconia-%s-win64-%s%s.zip' % (version, label, build_id)

def reserve_build_dirs(output_dir, work_dir, build_id):
    """Create this build's private work folder; a reused build id is refused, never overwritten."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    work = Path(work_dir)/build_id
    work.mkdir(parents=True, exist_ok=False)
    return work

def _absolute_path(value):
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError('must be an absolute path: ' + value)
    return path

def _build_id(value):
    if not BUILD_ID_PATTERN.match(value):
        raise argparse.ArgumentTypeError('build id may only use letters, digits, ".", "_" and "-"')
    return value

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Build the MiniDraconia Windows candidate ZIP (scripted offline).')
    parser.add_argument('--buildtools', action='append', default=[], type=_absolute_path, metavar='ABS_DIR',
                        help='optional external folder with PyInstaller (repeatable); added to PYTHONPATH of the build step only')
    parser.add_argument('--output-dir', type=_absolute_path, default=ROOT/'dist', help='where the versioned ZIP is written (default: <repo>/dist)')
    parser.add_argument('--work-dir', type=_absolute_path, default=ROOT/'work', help='scratch/evidence root (default: <repo>/work)')
    parser.add_argument('--build-id', type=_build_id, default=None, help='explicit unique build id (default: UTC time + random)')
    parser.add_argument('--allow-missing-docs', action='store_true', help='build even if README.md/RELEASE-NOTES.md are missing; the ZIP is labelled INCOMPLETE-DOCS')
    parser.add_argument('--preflight-only', action='store_true', help='check prerequisites and exit without building')
    parser.add_argument('--build-timeout', type=int, default=1800, help='seconds allowed for PyInstaller')
    parser.add_argument('--run-timeout', type=int, default=180, help='seconds allowed for each EXE run (smoke, selftest)')
    return parser.parse_args(argv)


# --- docs and licenses ----------------------------------------------------------------

def docs_preflight(root=ROOT):
    root = Path(root)
    missing = [name for name in REQUIRED_DOCS if not (root/name).is_file() or (root/name).stat().st_size == 0]
    return {'complete': not missing, 'missing': missing}

def require_docs(report, allow_missing):
    """True when complete. Missing docs stop the build unless explicitly allowed (then False)."""
    if report['complete']:
        return True
    if not allow_missing:
        raise RuntimeError('Required public docs missing: ' + ', '.join(report['missing']) +
                           ' (add them, or pass --allow-missing-docs to build a ZIP labelled INCOMPLETE-DOCS)')
    return False

def _notice_entries(name):
    from importlib.metadata import distribution, PackageNotFoundError
    try:
        dist = distribution(name)
    except PackageNotFoundError:
        raise RuntimeError("Distribution '%s' is not installed; cannot collect its license notice files" % name)
    found = []
    for entry in dist.files or ():
        parts = PurePosixPath(entry.as_posix()).parts
        file_name = parts[-1]
        in_license_dir = any(part.lower() in ('licenses', 'license') for part in parts[:-1])
        looks_like_notice = bool(_NOTICE_NAME.match(file_name)) and Path(file_name).suffix.lower() not in _CODE_SUFFIXES
        if in_license_dir or looks_like_notice:
            source = Path(dist.locate_file(entry))
            if source.is_file() and Path(file_name).suffix.lower() not in {'.py', '.pyc', '.pyi'}:
                found.append((entry, source))
    return dist, found

def collect_license_notices(names, dest_dir):
    """Copy redistributable notice files of each installed distribution; fail clearly if none."""
    dest_dir = Path(dest_dir)
    result = {}
    for name in names:
        dist, found = _notice_entries(name)
        if not found:
            raise RuntimeError("Distribution '%s' ships no license/notice files that can be bundled" % name)
        items = []
        canonical = '%s-%s' % (re.sub(r'[^A-Za-z0-9.]+', '_', dist.metadata['Name']), dist.version)
        for entry, source in found:
            if source.is_symlink():
                raise RuntimeError('Symlink in installed notice file: ' + entry.as_posix())
            item = record(source)
            if entry.hash and entry.hash.mode == 'sha256':
                digest = base64.urlsafe_b64encode(bytes.fromhex(item['sha256'])).decode().rstrip('=')
                if digest != entry.hash.value:
                    raise RuntimeError('Notice file differs from its wheel RECORD: ' + entry.as_posix())
            relative = canonical + '/' + entry.as_posix()
            target = dest_dir/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            items.append(dict(item, distribution=dist.metadata['Name'], version=dist.version, dest=relative, name=entry.as_posix()))
        result[name] = items
    return result

def _reference_symlink_free(path, base):
    """True when neither the file nor any folder between `base` and it is a symlink."""
    current = Path(path)
    while True:
        if current.is_symlink():
            return False
        if current == base or current.parent == current:
            return True
        current = current.parent

def verify_qt_reference(reference_dir=None, installed_versions=None):
    """Verify the committed Qt reference texts; returns one dict per verified file or raises RuntimeError.

    Every file must be listed in PROVENANCE.json with the pinned project/commit/version, its exact size and
    sha256. Unlisted files, symlinks, traversal and a version different from the installed Qt are refused.
    There is no blanket allow-list: only what PROVENANCE.json names, after the checks, is trusted.
    """
    reference = Path(QT_REFERENCE_DIR if reference_dir is None else reference_dir)
    if reference.is_symlink() or not reference.is_dir():
        raise RuntimeError('Qt reference notices folder is missing or a symlink: ' + str(reference))
    for name, version in (installed_versions or {}).items():
        if version != QT_REFERENCE_VERSION:
            raise RuntimeError('Installed %s is %s but the reference notices are for Qt %s' % (name, version, QT_REFERENCE_VERSION))
    provenance = reference/'PROVENANCE.json'
    if provenance.is_symlink():
        raise RuntimeError('Qt reference PROVENANCE.json is a symlink')
    try:
        entries = json.loads(provenance.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise RuntimeError('Qt reference PROVENANCE.json unreadable: %s' % type(exc).__name__)
    if not isinstance(entries, list) or not entries or not all(isinstance(e, dict) for e in entries):
        raise RuntimeError('Qt reference PROVENANCE.json is empty or malformed')
    verified, seen = [], set()
    for entry in entries:
        name = entry.get('file')
        project = entry.get('project')
        if project not in QT_REFERENCE_PROJECTS or not isinstance(name, str):
            raise RuntimeError('Qt reference entry has an unknown project or file: %r' % (project,))
        folder, commit = QT_REFERENCE_PROJECTS[project]
        parts = name.split('/')
        if (len(parts) != 2 or parts[0] != folder or not _REFERENCE_NAME.match(parts[1]) or '\\' in name
                or ':' in name or name.startswith('/')):
            raise RuntimeError('Qt reference entry has an unsafe or invalid file name: %r' % (name,))
        if name in seen:
            raise RuntimeError('Qt reference entry duplicate: ' + name)
        seen.add(name)
        if entry.get('version') != QT_REFERENCE_VERSION or entry.get('commit') != commit:
            raise RuntimeError('Qt reference entry %s is not version %s at the pinned commit' % (name, QT_REFERENCE_VERSION))
        url = 'https://raw.githubusercontent.com/%s/%s/LICENSES/%s' % (project, commit, parts[1])
        if entry.get('url') != url:
            raise RuntimeError('Qt reference entry %s has an unexpected source URL' % name)
        size, digest = entry.get('bytes'), entry.get('sha256')
        if not isinstance(size, int) or isinstance(size, bool) or not isinstance(digest, str) or not _HEX64.match(digest):
            raise RuntimeError('Qt reference entry %s has no valid size/sha256' % name)
        source = reference/folder/parts[1]
        if not _reference_symlink_free(source, reference) or not _reference_symlink_free(reference/folder, reference):
            raise RuntimeError('Symlink in Qt reference notices: ' + name)
        if not source.is_file():
            raise RuntimeError('Qt reference file missing or not a file: ' + name)
        actual = record(source)
        if actual['bytes'] != size:
            raise RuntimeError('Qt reference file size differs from PROVENANCE.json: %s (%d != %d)' % (name, actual['bytes'], size))
        if actual['sha256'] != digest:
            raise RuntimeError('Qt reference file sha256 differs from PROVENANCE.json: ' + name)
        verified.append({'project': project, 'version': entry['version'], 'commit': commit, 'name': name, 'url': url,
                         'bytes': size, 'sha256': digest, 'source': str(source)})
    for required in QT_REFERENCE_REQUIRED:
        if required not in seen:
            raise RuntimeError('Qt reference is missing a required open-source license text: ' + required)
    for folder, dirs, files in os.walk(reference, followlinks=False):
        for name in dirs:
            if os.path.islink(os.path.join(folder, name)):
                raise RuntimeError('Symlink in Qt reference notices: ' + name)
        for file_name in files:
            relative = (Path(folder)/file_name).relative_to(reference).as_posix()
            if relative != 'PROVENANCE.json' and relative not in seen:
                raise RuntimeError('Qt reference file is not listed in PROVENANCE.json: ' + relative)
    return sorted(verified, key=lambda item: item['name'])

def collect_qt_reference_notices(dest_dir, reference_dir=None, installed_versions=None):
    """Verify, then copy the reference texts and PROVENANCE.json under <dest>/qt-6.5.3-reference/; re-hash the copies."""
    reference = Path(QT_REFERENCE_DIR if reference_dir is None else reference_dir)
    items = verify_qt_reference(reference, installed_versions)
    root = Path(dest_dir)/QT_REFERENCE_DEST
    files = []
    for item in items:
        relative = QT_REFERENCE_DEST + '/' + item['name']
        target = Path(dest_dir)/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item['source'], target)
        if record(target) != {'sha256': item['sha256'], 'bytes': item['bytes']}:
            raise RuntimeError('Qt reference copy differs from the verified source: ' + item['name'])
        files.append({key: item[key] for key in ('name', 'project', 'version', 'commit', 'url', 'bytes', 'sha256')} | {'dest': relative})
    prov_target = root/'PROVENANCE.json'
    shutil.copyfile(reference/'PROVENANCE.json', prov_target)
    provenance = dict(record(prov_target), dest=QT_REFERENCE_DEST + '/PROVENANCE.json')
    return {'version': QT_REFERENCE_VERSION, 'files': files, 'provenance': provenance, 'note': QT_REFERENCE_NOTE}

def qt_notice_problems(names=None, reference_dir=None):
    """Preflight list for the Qt notice gate: wheel notices AND the verified, version-matched reference texts."""
    problems, versions = [], {}
    for name in (QT_NOTICE_DISTRIBUTIONS if names is None else names):
        try:
            dist, found = _notice_entries(name)
        except RuntimeError as exc:
            problems.append(str(exc))
            continue
        versions[name] = dist.version
        if not found:
            problems.append("No bundled license/notice files found for '%s'" % name)
    try:
        verify_qt_reference(reference_dir, versions)
    except RuntimeError as exc:
        problems.append('Qt reference notices (open-source license texts) not verified: %s' % exc)
    return problems

def collect_optional_notices(names, dest_dir):
    found, missing = {}, []
    for name in names:
        try:
            found.update(collect_license_notices([name], dest_dir))
        except RuntimeError as exc:
            missing.append({'distribution': name, 'reason': str(exc)})
    return found, missing


# --- tree, archive and verification -----------------------------------------------------

def hash_tree(root, qt_inventory=None, classify=True):
    """sha256/bytes of every file (relative POSIX names, sorted). Rejects forbidden artifacts and symlinks."""
    root = Path(root)
    result = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            if os.path.islink(os.path.join(folder, name)):
                raise RuntimeError('Forbidden symlink in package tree: ' + name)
        for file_name in files:
            path = Path(folder)/file_name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or (classify and forbidden_artifact(relative, path, qt_inventory)):
                raise RuntimeError('Forbidden packaged inference/profile artifact: ' + relative)
            result[relative] = record(path)
    return dict(sorted(result.items()))

def create_archive(root, expected, archive, compress=True):
    root = Path(root)
    method = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(archive, 'x', method, compresslevel=6 if compress else None) as z:
        for name in sorted(expected):
            info = zipfile.ZipInfo(TOP + '/' + name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = method
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            with (root/name).open('rb') as source, z.open(info, 'w', force_zip64=True) as target:
                shutil.copyfileobj(source, target, 1024*1024)

def _unsafe_member(name):
    return ('\\' in name or ':' in name or name.startswith('/') or '..' in PurePosixPath(name).parts
            or not name.startswith(TOP + '/'))

def verify_archive(archive, expected, extract_dir, qt_inventory=None):
    """Validate member names, CRC and content hashes by extracting into a NEW folder; returns the extracted root."""
    extract_dir = Path(extract_dir)
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        names = [info.filename for info in infos]
        if len(set(names)) != len(names):
            raise RuntimeError('ZIP has duplicate member names')
        for info in infos:
            if _unsafe_member(info.filename):
                raise RuntimeError('ZIP has an unsafe member name: ' + info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise RuntimeError('ZIP has a symlink member: ' + info.filename)
        bad = z.testzip()
        if bad is not None:
            raise RuntimeError('ZIP CRC check failed (corrupt member): ' + bad)
        extract_dir.mkdir(parents=True, exist_ok=False)
        base = extract_dir.resolve()
        for info in infos:
            if info.is_dir():
                continue
            target = (extract_dir/PurePosixPath(info.filename)).resolve()
            if not target.is_relative_to(base):
                raise RuntimeError('ZIP member escapes the extraction folder: ' + info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as source, target.open('wb') as out:
                shutil.copyfileobj(source, out, 1024*1024)
    extracted = extract_dir/TOP
    actual = hash_tree(extracted, qt_inventory, classify=qt_inventory is not None)
    if actual != expected:
        differing = sorted(set(actual) ^ set(expected) | {k for k in actual.keys() & expected.keys() if actual[k] != expected[k]})
        raise RuntimeError('Extracted content mismatch (%d differing files), e.g. %s' % (len(differing), differing[:5]))
    return extracted

def source_inputs(root=ROOT):
    """sha256 of every source file that feeds the build (no caches, no outputs)."""
    root = Path(root)
    found = {}
    def add(path):
        found[path.relative_to(root).as_posix()] = record(path)
    for top in ('full-engine', 'scripts', 'tests', 'third_party'):
        for folder, dirs, files in os.walk(root/top):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for name in files:
                if not name.endswith('.pyc'):
                    add(Path(folder)/name)
    for name in ('VERSION', 'LICENSE', 'README.md', 'RELEASE-NOTES.md', 'requirements.txt', 'requirements-dev.txt', 'package_scripted.py', '.gitignore'):
        if (root/name).is_file():
            add(root/name)
    return dict(sorted(found.items()))


# --- isolated execution of the extracted EXE -------------------------------------------------

def isolated_run_environment(base, system_root=None, inherited=None):
    """Clean environment: no developer Python/PATH/secrets; fresh profile, APPDATA and temp inside `base`."""
    inherited = os.environ if inherited is None else inherited
    system_root = system_root or inherited.get('SystemRoot') or inherited.get('SYSTEMROOT')
    if not system_root:
        raise RuntimeError('SystemRoot is required to run the Windows EXE')
    base = Path(base)
    temp = base/'temp'
    temp.mkdir(parents=True, exist_ok=True)
    return {'SystemRoot': system_root, 'WINDIR': system_root, 'PATH': system_root + '\\System32;' + system_root,
            'APPDATA': str(base/'appdata'), 'LOCALAPPDATA': str(base/'local'), 'USERPROFILE': str(base/'home'),
            'TEMP': str(temp), 'TMP': str(temp), 'MINIDRACONIA_TEST_PROFILE': str(base/'profile')}

def run_executable(cmd, env, cwd, timeout):
    """Run for real; report the actual outcome (exited / timeout / not-started), never raise on failure."""
    outcome = {'command': [Path(cmd[0]).name] + [str(c) for c in cmd[1:]], 'returncode': None, 'stdout_tail': '', 'stderr_tail': ''}
    try:
        proc = subprocess.Popen(cmd, env=env, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace')
    except OSError as exc:
        return dict(outcome, outcome='not-started', error='%s: %s' % (type(exc).__name__, exc))
    try:
        out, err = proc.communicate(timeout=timeout)
        outcome.update(outcome='exited', returncode=proc.returncode)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        outcome.update(outcome='timeout', timeout_s=timeout)
    outcome.update(stdout_tail=(out or '')[-4000:], stderr_tail=(err or '')[-4000:])
    return outcome


# --- preflight ---------------------------------------------------------------------------

def read_pins(path):
    """(name, version) for every `name==version` requirement that applies on this platform."""
    pins = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        spec, _, marker = line.split('#', 1)[0].partition(';')
        match = re.match(r'^\s*([A-Za-z0-9_.-]+)\s*==\s*([^\s]+)\s*$', spec)
        if not match:
            continue
        if marker.strip() and "sys_platform" in marker and "win32" in marker and sys.platform != 'win32':
            continue
        pins.append((match.group(1), match.group(2)))
    return pins

def preflight(options):
    problems = []
    if sys.platform != 'win32':
        problems.append('Windows is required to build and run the EXE (found %s)' % sys.platform)
    if sys.version_info[:2] != (3, 11):
        problems.append('Python 3.11 is the only supported build interpreter (found %d.%d)' % sys.version_info[:2])
    for folder in (options.output_dir, options.work_dir):
        if Path(folder).resolve().is_relative_to((ROOT/'full-engine').resolve()):
            problems.append('output/work folders must be outside full-engine: ' + str(folder))
    added = [str(p) for p in options.buildtools]
    sys.path[:0] = added
    try:
        import importlib.util
        if importlib.util.find_spec('PyInstaller') is None:
            problems.append('PyInstaller not found: install requirements-dev.txt or pass --buildtools <absolute folder>')
    except (ImportError, ValueError) as exc:
        problems.append('PyInstaller import check failed: %s' % type(exc).__name__)
    finally:
        for p in added:
            sys.path.remove(p)
    from importlib.metadata import version, PackageNotFoundError
    for name, pinned in read_pins(ROOT/'requirements.txt'):
        try:
            installed = version(name)
        except PackageNotFoundError:
            problems.append('%s==%s is pinned but not installed' % (name, pinned))
            continue
        if installed != pinned:
            problems.append('%s installed %s but requirements.txt pins %s' % (name, installed, pinned))
    try:
        qt_models_inventory()
    except Exception as exc:
        problems.append('Qt RECORD provenance gate: %s' % exc)
    problems += qt_notice_problems()
    docs = docs_preflight()
    if not docs['complete'] and not options.allow_missing_docs:
        problems.append('Required public docs missing: ' + ', '.join(docs['missing']) + ' (or pass --allow-missing-docs)')
    return problems


# --- build -------------------------------------------------------------------------------------

def _write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2), encoding='utf-8')

def _receipt_problems(kind, report):
    if not isinstance(report, dict):
        return ['%s: report must be a JSON object' % kind]
    if kind == 'selftest':
        if any(type(report.get(key)) is not int or report[key] != 0 for key in ('quit_code', 'network_attempts')):
            return ['selftest: quit_code and network_attempts must be integer zero']
        return []
    if kind != 'startup-smoke':
        return ['unknown executable check: %s' % kind]
    callbacks = report.get('callback_exceptions')
    valid = (type(report.get('schema')) is int and report['schema'] == 1
             and report.get('mode') == 'startup-smoke' and report.get('ok') is True
             and type(report.get('exit_code')) is int and report['exit_code'] == 0
             and report.get('failures') == [] and report.get('error') is None
             and isinstance(callbacks, dict) and type(callbacks.get('count')) is int
             and callbacks['count'] == 0 and callbacks.get('recorded') == [])
    if not valid:
        return ['startup-smoke: missing, invalid or unsuccessful report fields']
    # Reuse the producer's pure evidence validator; importing this module does not import Qt.
    spec = importlib.util.spec_from_file_location('minidraconia_smoke_receipt', ROOT/'full-engine'/'DyberPet'/'startup_smoke.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return ['startup-smoke: ' + reason for reason in module.evaluate(report.get('evidence'))]


def _executable_check(kind, outcome, report_path):
    """Decide pass/fail from the real process outcome and the report the EXE itself wrote."""
    failures = []
    if outcome['outcome'] != 'exited' or outcome['returncode'] != 0:
        failures.append('%s: process %s, return code %s' % (kind, outcome['outcome'], outcome.get('returncode')))
    report = None
    if Path(report_path).is_file():
        try:
            report = json.loads(Path(report_path).read_text(encoding='utf-8'))
        except ValueError:
            failures.append('%s: report is not valid JSON' % kind)
    else:
        failures.append('%s: the EXE wrote no report' % kind)
    failures += _receipt_problems(kind, report)
    return failures, report

def build(options):
    version = read_version()
    problems = preflight(options)
    if problems:
        print('preflight FAILED:\n  - ' + '\n  - '.join(problems), file=sys.stderr)
        return 2
    docs = docs_preflight()
    docs_complete = require_docs(docs, options.allow_missing_docs)
    build_id = options.build_id or new_build_id()
    work = reserve_build_dirs(options.output_dir, options.work_dir, build_id)
    evidence = work/'evidence'
    evidence.mkdir()
    profile = work/'build-profile'
    profile.mkdir()
    env = build_environment(profile, buildtools=options.buildtools)
    cmd = [sys.executable, '-B', '-m', 'PyInstaller', '--noconfirm', '--workpath', str(work/'pyi-build'),
           '--distpath', str(work/'pyi-dist'), str(SPEC)]
    done = subprocess.run(cmd, env=env, cwd=str(work), capture_output=True, text=True, timeout=options.build_timeout)
    _write_json(evidence/'pyinstaller.json', {'command': [Path(cmd[0]).name] + cmd[1:], 'rc': done.returncode, 'stdout': done.stdout, 'stderr': done.stderr})
    print('pyinstaller rc', done.returncode, flush=True)
    if done.returncode:
        raise RuntimeError('PyInstaller failed; see ' + str(evidence/'pyinstaller.json'))
    source = work/'pyi-dist'/TOP
    if not (source/(TOP + '.exe')).is_file():
        raise RuntimeError('PyInstaller did not produce ' + TOP + '.exe')

    from importlib.metadata import version as dist_version, PackageNotFoundError
    qt_inventory = qt_models_inventory()
    _write_json(evidence/'qt-provenance.json', qt_inventory)
    notices_dir = source/'THIRD-PARTY-NOTICES'
    qt_notices = collect_license_notices(QT_NOTICE_DISTRIBUTIONS, notices_dir)
    qt_installed = {name: dist_version(name) for name in QT_NOTICE_DISTRIBUTIONS}
    qt_reference = collect_qt_reference_notices(notices_dir, installed_versions=qt_installed)
    other_notices, notices_missing = collect_optional_notices(OTHER_NOTICE_DISTRIBUTIONS, notices_dir)
    for name in REQUIRED_DOCS:
        if (ROOT/name).is_file() and (ROOT/name).stat().st_size:
            shutil.copyfile(ROOT/name, source/name)
    shutil.copyfile(ROOT/'VERSION', source/'VERSION')
    if not docs_complete:
        (source/'DOCS-INCOMPLETE.txt').write_text('This candidate was built without: ' + ', '.join(docs['missing']) + '\n', encoding='utf-8')

    installed = {}
    for name, _ in read_pins(ROOT/'requirements.txt'):
        try:
            installed[name] = dist_version(name)
        except PackageNotFoundError:
            pass
    probe = subprocess.run([sys.executable, '-B', '-c', 'import PyInstaller; print(PyInstaller.__version__)'], env=env, cwd=str(work),
                           capture_output=True, text=True, timeout=120)
    pyinstaller_version = probe.stdout.strip() if probe.returncode == 0 else 'unknown'
    inputs = {
        'version': version, 'build_id': build_id, 'docs': docs, 'legal_note': LEGAL_NOTE,
        'python': sys.version.split()[0], 'platform': sys.platform, 'pyinstaller': pyinstaller_version,
        'external_buildtools_used': bool(options.buildtools), 'installed_requirements': installed,
        'source_files': source_inputs(),
        'license_notices': {k: [{key: i[key] for key in ('name', 'dest', 'sha256', 'bytes', 'version')} for i in v]
                            for k, v in {**qt_notices, **other_notices}.items()},
        'license_notices_not_found': notices_missing,
        'qt_reference_notices': qt_reference,
    }
    _write_json(source/'BUILD-INPUTS.json', inputs)
    files = hash_tree(source, qt_inventory)
    _write_json(source/'PACKAGE-MANIFEST.json', {
        'product': 'MiniDraconia SCRIPTED offline', 'version': version, 'build_id': build_id, 'candidate': True,
        'stable_accepted': False, 'byo_cloud': 'not implemented', 'legal_note': LEGAL_NOTE,
        'files': files, 'note': 'Lists every file in this folder except PACKAGE-MANIFEST.json itself.'})
    expected = hash_tree(source, qt_inventory)
    archive = Path(options.output_dir)/archive_name(version, build_id, docs_complete)
    create_archive(source, expected, archive)
    extracted = verify_archive(archive, expected, work/'extracted install dir', qt_inventory)
    print('zip verified', archive.name, len(expected), 'files', flush=True)

    results, failures = {}, []
    for kind, flag in (('startup-smoke', '--startup-smoke'), ('selftest', '--selftest-scripted')):
        base = work/('run-' + kind)
        scratch = base/'cwd with space'
        scratch.mkdir(parents=True)
        run_env = isolated_run_environment(base)
        if kind == 'selftest':
            run_env['MINIDRACONIA_MUTE'] = '1'
        report_path = evidence/(kind + '.json')
        outcome = run_executable([str(extracted/(TOP + '.exe')), flag, '--report', str(report_path)], run_env, scratch, options.run_timeout)
        problems_found, report = _executable_check(kind, outcome, report_path)
        failures += problems_found
        results[kind] = {'process': outcome, 'report': report, 'passed': not problems_found}
        print(kind, 'passed' if not problems_found else 'FAILED', flush=True)

    result = {'status': 'PASSED' if not failures else 'FAILED', 'failures': failures, 'zip': archive.name,
              **record(archive), 'files': len(expected), 'version': version, 'build_id': build_id,
              'docs_complete': docs_complete, 'runs': results, 'not_verified': NOT_VERIFIED}
    _write_json(Path(str(archive) + '.build.json'), result)
    Path(str(archive) + '.sha256').write_text('%s  %s\n' % (result['sha256'], archive.name), encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('status', 'zip', 'sha256', 'bytes', 'files')}), flush=True)
    return 0 if not failures else 1

def main(argv=None):
    options = parse_args(argv)
    if options.preflight_only:
        problems = preflight(options)
        print('preflight ' + ('FAILED:\n  - ' + '\n  - '.join(problems) if problems else 'ok'))
        return 2 if problems else 0
    return build(options)

if __name__=='__main__':
    sys.exit(main())
