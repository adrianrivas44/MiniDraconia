"""scripts/scan_release.py: metadata-only public tree and package check."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'scripts' / 'scan_release.py'


def load():
    spec = importlib.util.spec_from_file_location('scan_release_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Built at runtime so this test file itself never contains a scannable signature.
FAKE_ANTHROPIC = 'sk' + '-ant-' + 'A' * 40
FAKE_GITHUB = 'gh' + 'p_' + 'B' * 36
FAKE_PRIVATE_KEY = '-----BEGIN ' + 'OPENSSH PRIVATE KEY-----\nabc\n-----END ' + 'OPENSSH PRIVATE KEY-----\n'


class ScanTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scan = load()

    def put(self, relative, content='x', binary=False):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if binary:
            path.write_bytes(content)
        else:
            path.write_text(content, encoding='utf-8')
        return path

    def rules(self, report, bucket='findings'):
        return {(item['rule'], item['path']) for item in report[bucket]}

    def test_clean_tree_has_no_findings(self):
        self.put('full-engine/DyberPet/a.py', 'print(1)\n')
        self.put('README.md', 'hello')
        report = self.scan.scan_tree(self.root)
        self.assertEqual(report['findings'], [])

    def test_private_artifacts_are_rejected_by_name(self):
        for name in ('.env', '.env.local', 'id_rsa', 'server.pem', 'cert.pfx', 'credentials.json', 'secrets.yaml',
                     'full-engine/models/w.gguf', 'x/w.onnx', 'x/w.safetensors', 'x/w.pt', 'x/w.pth',
                     'ollama.exe', 'llama-server.exe', 'a/__pycache__/m.pyc', 'work/b.txt', 'dist/z.zip', 'buildtools/p.py',
                     'logs/app.log', 'profiles/u/state.json', '.venv/pyvenv.cfg'):
            self.put(name, 'x')
        found = {path for _, path in self.rules(self.scan.scan_tree(self.root))}
        for name in ('.env', '.env.local', 'id_rsa', 'server.pem', 'cert.pfx', 'credentials.json', 'secrets.yaml',
                     'full-engine/models/w.gguf', 'x/w.onnx', 'x/w.safetensors', 'x/w.pt', 'x/w.pth',
                     'ollama.exe', 'llama-server.exe', 'a/__pycache__/m.pyc', 'work/b.txt', 'dist/z.zip', 'buildtools/p.py',
                     'logs/app.log', 'profiles/u/state.json', '.venv/pyvenv.cfg'):
            self.assertIn(name, found)

    def test_key_signatures_are_found_and_values_never_printed(self):
        self.put('a.py', f'KEY = "{FAKE_ANTHROPIC}"\n')
        self.put('b.txt', FAKE_PRIVATE_KEY)
        self.put('c.md', f'token {FAKE_GITHUB}\n')
        report = self.scan.scan_tree(self.root)
        self.assertEqual({p for _, p in self.rules(report)}, {'a.py', 'b.txt', 'c.md'})
        dumped = json.dumps(report) + self.scan.format_report(report)
        for secret in (FAKE_ANTHROPIC, FAKE_GITHUB, 'abc\n', 'A' * 40, 'B' * 36):
            self.assertNotIn(secret, dumped)
        self.assertTrue(all('line' in item for item in report['findings'] if item['rule'].startswith('secret-')))

    def test_oversize_files_are_rejected(self):
        big = self.put('video.bin', b'', binary=True)
        with big.open('wb') as stream:
            stream.truncate(101 * 1024 * 1024)
        self.put('ok.bin', b'12345', binary=True)
        found = self.rules(self.scan.scan_tree(self.root))
        self.assertIn(('oversize', 'video.bin'), found)
        self.assertNotIn(('oversize', 'ok.bin'), found)

    def test_private_paths_are_warnings_to_review_not_blockers(self):
        self.put('notes.py', '# see D:/Aiu/Lab/Draconia/x and /root/projects/y\n')
        report = self.scan.scan_tree(self.root)
        self.assertEqual(report['findings'], [])
        self.assertIn(('private-path', 'notes.py'), self.rules(report, 'review'))

    def test_legal_unknowns_are_listed_separately_and_never_asserted_ok(self):
        self.put('full-engine/res/role/Draconia/a.png', b'png', binary=True)
        self.put('full-engine/res/sounds/s.wav', b'wav', binary=True)
        self.put('full-engine/licenses/qwen/LICENSE', 'text')
        self.put('f/font.ttf', b'ttf', binary=True)
        report = self.scan.scan_tree(self.root)
        unknown = {path for _, path in self.rules(report, 'legal_unknown')}
        self.assertTrue({'full-engine/res/role/Draconia', 'full-engine/res/sounds', 'full-engine/licenses/qwen', 'f/font.ttf'} <= unknown)
        self.assertEqual(report['findings'], [])
        self.assertNotIn('compatible', self.scan.format_report(report).lower().replace('not verified', ''))

    def test_symlinks_are_findings(self):
        target = self.put('real.txt', 'x')
        try:
            os.symlink(target, self.root / 'link.txt')
        except (OSError, NotImplementedError):
            self.skipTest('symlinks not creatable here')
        self.assertIn(('symlink', 'link.txt'), self.rules(self.scan.scan_tree(self.root)))

    def test_git_directory_is_not_scanned_as_content(self):
        self.put('.git/config', 'x')
        self.assertEqual(self.scan.scan_tree(self.root)['findings'], [])

    def test_allowlist_marks_a_false_positive_with_a_reason(self):
        self.put('docs/example.md', f'example {FAKE_ANTHROPIC}\n')
        report = self.scan.scan_tree(self.root, allow={('secret-anthropic', 'docs/example.md'): 'documented fake'})
        self.assertEqual(report['findings'], [])
        self.assertEqual(report['allowed'][0]['reason'], 'documented fake')


class ScanArchive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.scan = load()

    def test_member_names_are_checked_without_extracting(self):
        archive = self.base / 'p.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('MiniDraconia/ok.txt', 'x')
            z.writestr('MiniDraconia/../evil.txt', 'x')
            z.writestr('/abs.txt', 'x')
            z.writestr('MiniDraconia/models/w.gguf', 'x')
            z.writestr('MiniDraconia/.env', 'x')
        report = self.scan.scan_archive(archive)
        rules = {item['rule'] for item in report['findings']}
        self.assertTrue({'path-traversal', 'private-artifact'} <= rules)
        self.assertEqual(sum(1 for i in report['findings'] if i['rule'] == 'path-traversal'), 2)

    def test_qt_item_models_directory_is_not_inference_weights(self):
        archive = self.base / 'q.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('MiniDraconia/_internal/PySide6/qml/QtQml/Models/modelsplugin.dll', 'x')
        self.assertEqual(self.scan.scan_archive(archive)['findings'], [])


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(SCRIPT), *args], capture_output=True, text=True, timeout=120)

    def test_exit_codes_and_no_value_echo(self):
        with tempfile.TemporaryDirectory() as base:
            Path(base, 'a.py').write_text(f'K = "{FAKE_ANTHROPIC}"\n', encoding='utf-8')
            bad = self.run_cli('--root', base)
            self.assertEqual(bad.returncode, 1)
            self.assertNotIn(FAKE_ANTHROPIC, bad.stdout + bad.stderr)
            Path(base, 'a.py').write_text('K = 1\n', encoding='utf-8')
            self.assertEqual(self.run_cli('--root', base).returncode, 0)

    def test_missing_root_is_usage_error(self):
        self.assertEqual(self.run_cli('--root', '/nonexistent-root-for-scan').returncode, 2)


if __name__ == '__main__':
    unittest.main()
