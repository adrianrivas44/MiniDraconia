"""Interpreter/OpenSSL notices are distinct from installed wheel notices."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RuntimeNotices(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.reference = self.base / 'reference'
        self.reference.mkdir()
        self.versions = {'Python': '3.11.15', 'OpenSSL': '3.5.7'}
        self.rows = []
        for name in ('Python-LICENSE.txt', 'OpenSSL-LICENSE.txt', 'OpenSSL-AUTHORS.md'):
            data = ('test-only notice fixture: ' + name + '\n').encode()
            (self.reference / name).write_bytes(data)
            self.rows.append({'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        self.save_manifest()
        spec = importlib.util.spec_from_file_location('builder_runtime_notice_test', ROOT / 'package_scripted.py')
        assert spec is not None and spec.loader is not None
        self.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.builder)

    def save_manifest(self):
        (self.reference / 'PROVENANCE.json').write_text(json.dumps({'versions': self.versions, 'files': self.rows}), encoding='utf-8')

    def test_runtime_notices_are_copied_exactly_and_recorded(self):
        collect = getattr(self.builder, 'collect_runtime_notices', None)
        self.assertTrue(callable(collect), 'builder does not collect interpreter/OpenSSL notices')
        assert collect is not None
        dest = self.base / 'output'
        result = collect(dest, reference_dir=self.reference, versions=self.versions)
        self.assertEqual(result['versions'], self.versions)
        self.assertEqual(len(result['files']), 3)
        for row in result['files']:
            self.assertEqual((dest / row['dest']).read_bytes(), (self.reference / row['name']).read_bytes())
            self.assertEqual(hashlib.sha256((dest / row['dest']).read_bytes()).hexdigest(), row['sha256'])
        copied = dest / 'interpreter-openssl' / 'PROVENANCE.json'
        self.assertEqual(copied.read_bytes(), (self.reference / 'PROVENANCE.json').read_bytes())

    def test_corrupt_runtime_notice_is_rejected_before_any_copy(self):
        (self.reference / 'OpenSSL-AUTHORS.md').write_bytes(b'corrupted notice')
        dest = self.base / 'output'
        with self.assertRaisesRegex(RuntimeError, 'runtime notice'):
            self.builder.collect_runtime_notices(dest, reference_dir=self.reference, versions=self.versions)
        self.assertFalse(dest.exists(), 'failed verification must not create a partially accepted notice folder')

    def test_different_runtime_version_is_rejected_before_copy(self):
        for component in ('Python', 'OpenSSL'):
            with self.subTest(component=component):
                actual = dict(self.versions, **{component: 'different-build'})
                dest = self.base / component
                with self.assertRaisesRegex(RuntimeError, 'runtime notice.*version'):
                    self.builder.collect_runtime_notices(dest, reference_dir=self.reference, versions=actual)
                self.assertFalse(dest.exists())

    def test_collected_notices_pass_the_unchanged_package_artifact_policy(self):
        result = self.builder.collect_runtime_notices(self.base / 'output', reference_dir=self.reference, versions=self.versions)
        for row in result['files']:
            self.assertFalse(self.builder.forbidden_artifact('THIRD-PARTY-NOTICES/' + row['dest']), row['dest'])


if __name__ == '__main__':
    unittest.main()
