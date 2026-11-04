"""Fail-closed receipt validation and Windows-equivalent asset path checks."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import test_public_assets as asset_helpers
from test_entry_startup import VALID_EVIDENCE

REPO = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExecutableReceipt(unittest.TestCase):
    def setUp(self):
        self.pkg = load('final_receipt_builder', REPO / 'package_scripted.py')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.report = Path(self.tmp.name) / 'report.json'
        self.outcome = {'outcome': 'exited', 'returncode': 0}

    def check(self, kind, value):
        self.report.write_text(json.dumps(value), encoding='utf-8')
        return self.pkg._executable_check(kind, self.outcome, self.report)[0]

    def valid_smoke(self):
        return {'schema': 1, 'mode': 'startup-smoke', 'ok': True, 'exit_code': 0,
                'failures': [], 'error': None, 'evidence': copy.deepcopy(VALID_EVIDENCE),
                'callback_exceptions': {'count': 0, 'recorded': []}}

    def test_null_and_nonobject_json_never_pass_either_mode(self):
        for kind in ('startup-smoke', 'selftest'):
            for value in (None, [], [1], '', 'ok', 0, False):
                with self.subTest(kind=kind, value=value):
                    self.assertTrue(self.check(kind, value))

    def test_valid_receipts_remain_accepted(self):
        self.assertEqual(self.check('startup-smoke', self.valid_smoke()), [])
        self.assertEqual(self.check('selftest', {'quit_code': 0, 'network_attempts': 0}), [])

    def test_smoke_requires_real_evidence_and_typed_success(self):
        for key, value in (('schema', True), ('mode', 'selftest'), ('ok', 1), ('exit_code', False),
                           ('failures', ['callback error']), ('evidence', {}), ('evidence', {'invented': True}),
                           ('callback_exceptions', {'count': False, 'recorded': []}),
                           ('callback_exceptions', {'count': 1, 'recorded': ['RuntimeError']})):
            with self.subTest(key=key, value=value):
                report = self.valid_smoke()
                report[key] = value
                self.assertTrue(self.check('startup-smoke', report))

    def test_selftest_requires_integer_zero_not_boolean(self):
        for key in ('quit_code', 'network_attempts'):
            for value in (None, False, '0', 0.0, 1):
                with self.subTest(key=key, value=value):
                    report: dict[str, object] = {'quit_code': 0, 'network_attempts': 0}
                    report[key] = value
                    self.assertTrue(self.check('selftest', report))


VARIANTS = (
    ('res/role/Draconia/note/Voice/head-02.wav', 'unapproved-audio'),
    ('RES/ROLE/Draconia/note/VOICE/head-02.WAV', 'unapproved-audio'),
    ('res/Pet/other/a.png', 'inherited-pet-asset'),
)


class WindowsAssetPathEquivalence(unittest.TestCase):
    def setUp(self):
        self.policy = load('final_asset_policy', REPO / 'full-engine/packaging/asset_policy.py')
        self.scanner = load('final_asset_scanner', REPO / 'scripts/scan_release.py')
        self.spec_helper = asset_helpers.SpecRejectsReintroduction()
        self.addCleanup(self.spec_helper.doCleanups)

    def test_case_variants_are_rejected_by_shared_policy(self):
        for path, rule in VARIANTS:
            with self.subTest(path=path):
                self.assertEqual(self.policy.violation(path), rule)
        self.assertIsNone(self.policy.violation('RES/ROLE/DRACONIA/NOTE/VOICE/HEAD-01.WAV'))
        self.assertIsNone(self.policy.violation('res/sounds/Notification.wav'))
        self.assertEqual(len(self.policy.APPROVED_AUDIO), 1)

    def test_spec_rejects_directory_case_variants(self):
        for path, rule in VARIANTS:
            with self.subTest(path=path):
                root = self.spec_helper.mini_engine([path])
                try:
                    datas = self.spec_helper.evaluate(root)
                except RuntimeError as exc:
                    self.assertIn(rule, str(exc))
                else:
                    # A differently cased resource ROOT is not collected on a case-sensitive host.
                    # It must never be in datas; Windows resolves that root to res and must reject it.
                    self.assertNotIn((root / path).resolve(), {Path(src).resolve() for src, _ in datas})

    def test_tree_and_archive_scans_reject_directory_case_variants(self):
        for path, rule in VARIANTS:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as base:
                root = Path(base) / 'source'
                target = root / path
                target.parent.mkdir(parents=True)
                target.write_bytes(b'unapproved fixture')
                archive = Path(base) / 'assets.zip'
                with zipfile.ZipFile(archive, 'w') as z:
                    z.writestr('MiniDraconia/_internal/' + path, b'unapproved fixture')
                self.assertIn(rule, {row['rule'] for row in self.scanner.scan_tree(root)['findings']})
                self.assertIn(rule, {row['rule'] for row in self.scanner.scan_archive(archive)['findings']})


if __name__ == '__main__':
    unittest.main()
