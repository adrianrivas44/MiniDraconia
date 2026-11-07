"""Metadata-only public release scan (standard library only).

    python scripts/scan_release.py [--root DIR] [--zip PACKAGE.zip] [--json]
                                   [--private-markers FILE]

Checks a source tree (and/or a package ZIP's member names) for private artifacts,
key/secret signatures, files over 100 MB, symlinks and path traversal.
Matched secret values are NEVER printed or stored: only rule, path and line number.
Exit code: 0 no blocking findings, 1 blocking findings, 2 usage error.

Private markers: the scanner knows only generic private paths (Windows `X:\\Users\\...`,
`/root/`, `/home/<user>/`). A maintainer can add their own machine names, folders or
account names as literal markers, one per line, in an untracked, git-ignored file
`.release-private-markers` at the repository root (read when present), or pass
`--private-markers FILE`. Blank lines and lines starting with `#` are ignored; matching is
case-insensitive. A marker found in a tree file is a blocking `private-marker` finding; the
marker text itself is never printed. The markers file at the scanned root is not scanned.

Buckets in the report:
  findings       blocking problems.
  review         things a human must look at (e.g. private paths named in comments);
                 usually false positives in a source tree, never silently dropped.
  legal_unknown  material whose rights/licence this script CANNOT judge. Listing it
                 is not approval; nothing here asserts that any licence is compatible.
  allowed        findings explicitly allow-listed as false positives, with the reason.
"""
import argparse
import importlib.util
import json
import os
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

MAX_BYTES = 100 * 1024 * 1024
MAX_CONTENT_BYTES = 4 * 1024 * 1024

# Explicit, reviewed false positives: {(rule, relative path): reason}.
DEFAULT_ALLOW = {}

ANY_DEPTH_DIRS = {'__pycache__', '.venv', 'venv', 'profiles', 'logs', '.claude'}
TOP_LEVEL_DIRS = {'work', 'dist', 'build', 'buildtools', 'staging', 'evidence', 'profile'}
PRIVATE_SUFFIXES = {'.pem', '.key', '.p12', '.pfx', '.jks', '.keystore', '.gguf', '.onnx', '.safetensors', '.pt', '.pth', '.pyc', '.log'}
PRIVATE_NAME_PARTS = ('credentials', 'secrets', 'ollama', 'llama-server')
PRIVATE_EXACT = {'.git-credentials', '.netrc', '.pypirc', '.npmrc', '.release-private-markers'}
ARCHIVE_DIRS = {'__pycache__', '.venv', 'venv', 'profiles', 'profile', 'runtime'}
FONT_SUFFIXES = {'.ttf', '.otf', '.woff', '.woff2'}

SECRET_PATTERNS = {
    'secret-private-key': re.compile(rb'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----'),
    'secret-anthropic': re.compile(rb'sk-ant-[A-Za-z0-9_\-]{20,}'),
    'secret-openai': re.compile(rb'sk-(?!ant-)(?:proj-)?[A-Za-z0-9_\-]{32,}'),
    'secret-xai': re.compile(rb'xai-[A-Za-z0-9]{40,}'),
    'secret-github': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})'),
    'secret-aws': re.compile(rb'AKIA[0-9A-Z]{16}'),
    'secret-google': re.compile(rb'AIza[0-9A-Za-z_\-]{35}'),
    'secret-slack': re.compile(rb'xox[baprs]-[A-Za-z0-9-]{10,}'),
}
PRIVATE_PATH = re.compile(rb'(?:[A-Za-z]:[\\/]Users[\\/]|/root/|/home/[a-z0-9_-]+/)')
MARKERS_NAME = '.release-private-markers'
DEFAULT_MARKERS_FILE = Path(__file__).resolve().parents[1]/MARKERS_NAME


def load_private_markers(path):
    """Literal markers (lower-cased bytes), one per line; [] when the file is absent.
    Blank lines and `#` comments are ignored."""
    try:
        text = Path(path).read_text(encoding='utf-8')
    except FileNotFoundError:
        return []
    markers = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            marker = line.encode('utf-8').lower()
            if marker not in markers:
                markers.append(marker)
    return markers


ASSET_POLICY_FILE = Path(__file__).resolve().parents[1]/'full-engine'/'packaging'/'asset_policy.py'


def _asset_policy():
    """Shared public-asset policy (unapproved voice clips, inherited pet folder); missing file is a hard error."""
    spec = importlib.util.spec_from_file_location('minidraconia_asset_policy', ASSET_POLICY_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _blank_report():
    return {'findings': [], 'review': [], 'legal_unknown': [], 'allowed': [], 'stats': {'files': 0}}


def _add(report, bucket, rule, path, allow=None, **extra):
    item = dict(rule=rule, path=path, **extra)
    reason = (allow or {}).get((rule, path)) if bucket == 'findings' else None
    if reason:
        report['allowed'].append(dict(item, reason=reason))
    else:
        report[bucket].append(item)


def _private_name(name):
    low = name.lower()
    return (low == '.env' or low.startswith('.env.') or low.startswith('id_rsa') or low.startswith('id_ed25519')
            or low in PRIVATE_EXACT or Path(low).suffix in PRIVATE_SUFFIXES
            or any(part in low for part in PRIVATE_NAME_PARTS))


def _legal_key(relative):
    parts = PurePosixPath(relative).parts
    for i, part in enumerate(parts):
        if part == 'res' and i + 1 < len(parts) - 1:
            if parts[i + 1] == 'role' and i + 2 < len(parts) - 1:
                return '/'.join(parts[:i + 3]), 'character art/voice assets: authorship and rights are not verified here'
            return '/'.join(parts[:i + 2]), 'bundled art/audio assets: source and rights are not verified here'
        if part == 'licenses' and i + 1 < len(parts) - 1:
            return '/'.join(parts[:i + 2]), 'third-party licence folder: applicability is not assessed here'
    if PurePosixPath(relative).suffix.lower() in FONT_SUFFIXES:
        return relative, 'font file: licence is not verified here'
    return None


def scan_tree(root, allow=None, max_bytes=MAX_BYTES, markers=()):
    """`markers`: extra private literals (bytes or str, see load_private_markers)."""
    allow = DEFAULT_ALLOW if allow is None else allow
    markers = [m.encode('utf-8').lower() if isinstance(m, str) else bytes(m).lower() for m in markers if m]
    root = Path(root)
    report = _blank_report()
    policy = _asset_policy()
    legal_seen = set()
    for folder, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != '.git')
        for name in list(dirs):
            path = Path(folder)/name
            if path.is_symlink():
                _add(report, 'findings', 'symlink', path.relative_to(root).as_posix(), allow)
                dirs.remove(name)
        for name in sorted(files):
            path = Path(folder)/name
            relative = path.relative_to(root).as_posix()
            parts = PurePosixPath(relative).parts
            if relative == MARKERS_NAME:
                continue    # the maintainer's own untracked marker list (git-ignored)
            report['stats']['files'] += 1
            if path.is_symlink():
                _add(report, 'findings', 'symlink', relative, allow)
                continue
            if '..' in parts or relative.startswith('/'):
                _add(report, 'findings', 'path-traversal', relative, allow)
            if (set(parts[:-1]) & ANY_DEPTH_DIRS) or (len(parts) > 1 and parts[0] in TOP_LEVEL_DIRS) or _private_name(name):
                _add(report, 'findings', 'private-artifact', relative, allow)
            rule = policy.violation(relative)
            if rule:
                _add(report, 'findings', rule, relative, allow)
            size = path.stat().st_size
            if size > max_bytes:
                _add(report, 'findings', 'oversize', relative, allow, bytes=size)
            legal = _legal_key(relative)
            if legal and legal[0] not in legal_seen:
                legal_seen.add(legal[0])
                _add(report, 'legal_unknown', 'rights-not-verified', legal[0], reason=legal[1])
            if 0 < size <= MAX_CONTENT_BYTES:
                data = path.read_bytes()
                if b'\x00' in data[:4096]:
                    continue
                for rule, pattern in SECRET_PATTERNS.items():
                    match = pattern.search(data)
                    if match:
                        _add(report, 'findings', rule, relative, allow, line=data.count(b'\n', 0, match.start()) + 1)
                # Another private product built on this engine must not leak into the public tree.
                low_data = data.lower()
                found = [low_data.find(name.encode('utf-8')) for name in getattr(policy, 'OTHER_PRODUCT_NAMES', ())]
                found = [i for i in found if i >= 0]
                position = min(found) if found else -1
                if position >= 0:
                    _add(report, 'findings', 'other-product-input', relative, allow, line=data.count(b'\n', 0, position) + 1)
                match = PRIVATE_PATH.search(data)
                if match:
                    _add(report, 'review', 'private-path', relative, line=data.count(b'\n', 0, match.start()) + 1)
                if markers:
                    low = data.lower()
                    hits = [i for i in (low.find(m) for m in markers) if i >= 0]
                    if hits:
                        _add(report, 'findings', 'private-marker', relative, allow,
                             line=data.count(b'\n', 0, min(hits)) + 1)
    return report


def scan_archive(archive, allow=None, max_bytes=MAX_BYTES):
    """Member names and sizes only: nothing is extracted or read."""
    allow = DEFAULT_ALLOW if allow is None else allow
    report = _blank_report()
    policy = _asset_policy()
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name = info.filename
            report['stats']['files'] += 1
            parts = PurePosixPath(name).parts
            if '..' in parts or name.startswith('/') or '\\' in name or ':' in name:
                _add(report, 'findings', 'path-traversal', name, allow)
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                _add(report, 'findings', 'symlink', name, allow)
            if info.is_dir():
                continue
            if (set(parts[:-1]) & ARCHIVE_DIRS) or _private_name(parts[-1]):
                _add(report, 'findings', 'private-artifact', name, allow)
            rule = policy.violation(name)
            if rule:
                _add(report, 'findings', rule, name, allow)
            if info.file_size > max_bytes:
                _add(report, 'findings', 'oversize', name, allow, bytes=info.file_size)
    return report


def format_report(report):
    lines = ['files scanned: %d' % report['stats']['files']]
    for bucket, title in (('findings', 'BLOCKING FINDINGS'), ('review', 'REVIEW (possible false positives)'),
                          ('legal_unknown', 'LEGAL UNKNOWN (rights not verified; listing is not approval)'),
                          ('allowed', 'ALLOWED false positives')):
        items = report[bucket]
        lines.append('%s: %d' % (title, len(items)))
        for item in items:
            where = item['path'] + (':%d' % item['line'] if 'line' in item else '')
            note = item.get('reason')
            lines.append('  [%s] %s%s' % (item['rule'], where, ' -- ' + note if note else ''))
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Metadata-only public release scan.')
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]), help='tree to scan (default: this repository)')
    parser.add_argument('--zip', help='package ZIP whose member names are checked')
    parser.add_argument('--json', action='store_true', help='print the report as JSON')
    parser.add_argument('--private-markers', metavar='FILE',
                        help='extra private literals, one per line (default: %s at the repository root, '
                             'when present)' % MARKERS_NAME)
    args = parser.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir() or (args.zip and not Path(args.zip).is_file()):
        print('scan_release: root directory or zip not found', file=sys.stderr)
        return 2
    if args.private_markers and not Path(args.private_markers).is_file():
        print('scan_release: private markers file not found', file=sys.stderr)
        return 2
    markers = load_private_markers(args.private_markers or DEFAULT_MARKERS_FILE)
    reports = {'tree': scan_tree(root, markers=markers)}
    if args.zip:
        reports['archive'] = scan_archive(args.zip)
    blocking = sum(len(r['findings']) for r in reports.values())
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        for name, report in reports.items():
            print('== %s ==' % name)
            print(format_report(report))
        print('RESULT: %s' % ('BLOCKING FINDINGS' if blocking else 'no blocking findings (legal unknowns still need human review)'))
    return 1 if blocking else 0


if __name__ == '__main__':
    sys.exit(main())
