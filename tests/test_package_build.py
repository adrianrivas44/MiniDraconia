"""Public portable build tooling: pure-stdlib behaviour of package_scripted.py.

The Qt wheel RECORD gate and the original artifact-classification tests stay in
test_scripted_product.py (unmodified). These tests cover what was added to make
the builder public and portable.
"""
import hashlib
import importlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_builder():
    spec = importlib.util.spec_from_file_location('package_scripted_under_test', REPO / 'package_scripted.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.pkg = load_builder()


class PublicBuildEnvironment(TempCase):
    def test_no_private_absolute_paths_in_the_builder(self):
        spec = importlib.util.spec_from_file_location('scan_release_for_builder', REPO / 'scripts' / 'scan_release.py')
        scan = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scan)
        data = (REPO / 'package_scripted.py').read_bytes()
        match = scan.PRIVATE_PATH.search(data)
        self.assertIsNone(match, 'private path in builder: %r' % (match.group(0) if match else None))
        for marker in ('/root/', 'C:\\Users', '/home/'):
            self.assertNotIn(marker, data.decode('utf-8'), 'private path marker in builder: ' + marker)

    def test_default_environment_does_not_add_buildtools_unless_asked(self):
        env = self.pkg.build_environment(self.base / 'p', buildtools=[])
        self.assertEqual(env['PYTHONPATH'].split(os.pathsep), [str(REPO / 'full-engine')])

    def test_explicit_external_buildtools_are_added_after_the_engine(self):
        external = self.base / 'ext tools'
        env = self.pkg.build_environment(self.base / 'p', buildtools=[external])
        self.assertEqual(env['PYTHONPATH'].split(os.pathsep), [str(REPO / 'full-engine'), str(external)])

    def test_build_environment_isolates_user_state(self):
        env = self.pkg.build_environment(self.base / 'p', buildtools=[])
        self.assertTrue(env['MINIDRACONIA_TEST_PROFILE'].startswith(str(self.base / 'p')))
        self.assertEqual(env['PYTHONDONTWRITEBYTECODE'], '1')
        self.assertTrue(env['PYINSTALLER_CONFIG_DIR'].startswith(str(self.base / 'p')))

    def test_cli_defaults_and_buildtools_option(self):
        opts = self.pkg.parse_args(['--buildtools', str(self.base / 'bt'), '--build-id', 'abc123'])
        self.assertEqual(opts.buildtools, [self.base / 'bt'])
        self.assertEqual(opts.build_id, 'abc123')
        self.assertFalse(opts.allow_missing_docs)
        self.assertFalse(opts.preflight_only)

    def test_cli_rejects_relative_buildtools_and_bad_build_ids(self):
        for argv in (['--buildtools', 'relative'], ['--build-id', '../x'], ['--build-id', 'a b'], ['--build-id', '']):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                self.pkg.parse_args(argv)


class CleanRunEnvironment(TempCase):
    def test_no_developer_python_or_path_leaks(self):
        env = self.pkg.isolated_run_environment(self.base / 'iso', system_root='C:\\Windows',
                                                inherited={'PYTHONPATH': 'dev', 'PYTHONHOME': 'x', 'PATH': 'C:\\Python311',
                                                           'API_KEY': 'secret', 'VIRTUAL_ENV': 'v'})
        for name in ('PYTHONPATH', 'PYTHONHOME', 'API_KEY', 'VIRTUAL_ENV'):
            self.assertNotIn(name, env)
        self.assertNotIn('Python311', env['PATH'])
        self.assertEqual(env['SystemRoot'], 'C:\\Windows')

    def test_profile_temp_and_appdata_are_fresh_and_inside_the_isolation_dir(self):
        iso = self.base / 'iso'
        env = self.pkg.isolated_run_environment(iso, system_root='C:\\Windows', inherited={})
        for name in ('MINIDRACONIA_TEST_PROFILE', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP'):
            self.assertTrue(Path(env[name]).is_relative_to(iso), name)
        self.assertFalse(Path(env['MINIDRACONIA_TEST_PROFILE']).exists(), 'profile must not pre-exist for the smoke freshness rule')
        self.assertTrue(Path(env['TEMP']).is_dir())

    def test_offscreen_and_mute_are_not_pre_set_for_smoke_runs(self):
        env = self.pkg.isolated_run_environment(self.base / 'iso', system_root='C:\\Windows', inherited={})
        self.assertNotIn('QT_QPA_PLATFORM', env)


class RunExecutable(TempCase):
    def script(self, body):
        path = self.base / 'fake exe.py'
        path.write_text(textwrap.dedent(body), encoding='utf-8')
        return [sys.executable, str(path)]

    def test_zero_exit(self):
        outcome = self.pkg.run_executable(self.script('print("hi")'), dict(os.environ), self.base, timeout=30)
        self.assertEqual(outcome['outcome'], 'exited')
        self.assertEqual(outcome['returncode'], 0)

    def test_nonzero_exit_is_reported_not_raised(self):
        outcome = self.pkg.run_executable(self.script('import sys; sys.exit(7)'), dict(os.environ), self.base, timeout=30)
        self.assertEqual((outcome['outcome'], outcome['returncode']), ('exited', 7))

    def test_hang_is_killed_and_reported_as_timeout(self):
        outcome = self.pkg.run_executable(self.script('import time; time.sleep(60)'), dict(os.environ), self.base, timeout=1)
        self.assertEqual(outcome['outcome'], 'timeout')
        self.assertIsNone(outcome['returncode'])

    def test_cwd_and_environment_are_honoured(self):
        cwd = self.base / 'with space'
        cwd.mkdir()
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        outcome = self.pkg.run_executable(self.script('import os; print(os.getcwd()); print("PYTHONPATH" in os.environ)'),
                                          env, cwd, timeout=30)
        lines = outcome['stdout_tail'].split()
        self.assertIn('False', lines)
        self.assertIn(str(cwd), outcome['stdout_tail'])

    def test_missing_executable_is_a_failed_outcome(self):
        outcome = self.pkg.run_executable([str(self.base / 'nope.exe')], dict(os.environ), self.base, timeout=5)
        self.assertEqual(outcome['outcome'], 'not-started')


class ArchiveSafety(TempCase):
    def tree(self):
        root = self.base / 'MiniDraconia'
        (root / 'sub dir').mkdir(parents=True)
        (root / 'a.txt').write_text('alpha', encoding='utf-8')
        (root / 'sub dir' / 'b.bin').write_bytes(b'\x00\x01')
        return root

    def test_create_validate_and_extract_round_trip(self):
        root = self.tree()
        expected = self.pkg.hash_tree(root)
        archive = self.base / 'out' / 'x.zip'
        archive.parent.mkdir()
        self.pkg.create_archive(root, expected, archive)
        extracted = self.pkg.verify_archive(archive, expected, self.base / 'extract dir')
        self.assertEqual(self.pkg.hash_tree(extracted), expected)

    def test_archive_is_never_overwritten(self):
        root = self.tree()
        expected = self.pkg.hash_tree(root)
        archive = self.base / 'x.zip'
        self.pkg.create_archive(root, expected, archive)
        with self.assertRaises(FileExistsError):
            self.pkg.create_archive(root, expected, archive)

    def test_traversal_absolute_and_backslash_members_rejected(self):
        for name in ('MiniDraconia/../evil.txt', '/abs.txt', 'MiniDraconia\\win.txt', 'C:/drive.txt', '../up.txt'):
            if '\\' in name and os.sep == '\\':
                continue  # zipfile itself rewrites backslashes to '/' on Windows
            with self.subTest(name=name):
                archive = self.base / (hashlib.sha1(name.encode()).hexdigest() + '.zip')
                with zipfile.ZipFile(archive, 'w') as z:
                    z.writestr(name, 'x')
                with self.assertRaisesRegex(RuntimeError, 'unsafe'):
                    self.pkg.verify_archive(archive, {}, self.base / ('x' + archive.stem))

    def test_symlink_member_rejected(self):
        archive = self.base / 'link.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            info = zipfile.ZipInfo('MiniDraconia/link')
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, 'target')
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            self.pkg.verify_archive(archive, {}, self.base / 'x1')

    def test_duplicate_member_rejected(self):
        archive = self.base / 'dup.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('MiniDraconia/a.txt', 'one')
            with self.assertWarns(UserWarning):
                z.writestr('MiniDraconia/a.txt', 'two')
        with self.assertRaisesRegex(RuntimeError, 'duplicate'):
            self.pkg.verify_archive(archive, {}, self.base / 'x2')

    def test_content_mismatch_and_extra_or_missing_files_rejected(self):
        root = self.tree()
        expected = self.pkg.hash_tree(root)
        archive = self.base / 'ok.zip'
        self.pkg.create_archive(root, expected, archive)
        wrong = json.loads(json.dumps(expected))
        wrong['a.txt']['sha256'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'mismatch'):
            self.pkg.verify_archive(archive, wrong, self.base / 'x3')
        missing = {k: v for k, v in expected.items() if k != 'a.txt'}
        with self.assertRaisesRegex(RuntimeError, 'mismatch'):
            self.pkg.verify_archive(archive, missing, self.base / 'x4')

    def test_crc_corruption_detected(self):
        root = self.tree()
        expected = self.pkg.hash_tree(root)
        archive = self.base / 'crc.zip'
        self.pkg.create_archive(root, expected, archive, compress=False)
        data = bytearray(archive.read_bytes())
        index = data.find(b'alpha')
        data[index] ^= 0xFF
        archive.write_bytes(bytes(data))
        with self.assertRaisesRegex(RuntimeError, 'CRC|corrupt'):
            self.pkg.verify_archive(archive, expected, self.base / 'x5')

    def test_forbidden_artifacts_cannot_enter_the_tree_hash(self):
        root = self.tree()
        (root / 'weights.gguf').write_bytes(b'0')
        with self.assertRaisesRegex(RuntimeError, 'Forbidden'):
            self.pkg.hash_tree(root, qt_inventory={})

    def test_symlink_in_tree_rejected(self):
        root = self.tree()
        try:
            os.symlink(root / 'a.txt', root / 'ln.txt')
        except (OSError, NotImplementedError):
            self.skipTest('symlinks not creatable here')
        with self.assertRaisesRegex(RuntimeError, 'Forbidden|symlink'):
            self.pkg.hash_tree(root, qt_inventory={})


class OutputNaming(TempCase):
    def test_archive_name_is_versioned_and_deterministic_per_build_id(self):
        a = self.pkg.archive_name('1.0.0-rc.1', 'b001', docs_complete=True)
        self.assertEqual(a, 'MiniDraconia-1.0.0-rc.1-win64-b001.zip')
        self.assertEqual(a, self.pkg.archive_name('1.0.0-rc.1', 'b001', docs_complete=True))

    def test_incomplete_docs_are_visible_in_the_name(self):
        self.assertIn('INCOMPLETE-DOCS', self.pkg.archive_name('1.0.0-rc.1', 'b001', docs_complete=False))

    def test_reusing_a_build_id_is_refused(self):
        out, work = self.base / 'dist', self.base / 'work'
        self.pkg.reserve_build_dirs(out, work, 'b001')
        with self.assertRaises(FileExistsError):
            self.pkg.reserve_build_dirs(out, work, 'b001')

    def test_default_build_id_is_unique_and_safe(self):
        a, b = self.pkg.new_build_id(), self.pkg.new_build_id()
        self.assertNotEqual(a, b)
        self.assertRegex(a, r'^[A-Za-z0-9._-]+$')


class DocsPreflight(TempCase):
    def test_missing_docs_are_reported_explicitly(self):
        report = self.pkg.docs_preflight(self.base)
        self.assertFalse(report['complete'])
        self.assertEqual(set(report['missing']), {'LICENSE', 'README.md', 'RELEASE-NOTES.md'})

    def test_complete_when_all_present_and_nonempty(self):
        for name in ('LICENSE', 'README.md', 'RELEASE-NOTES.md'):
            (self.base / name).write_text('text', encoding='utf-8')
        self.assertTrue(self.pkg.docs_preflight(self.base)['complete'])

    def test_empty_doc_counts_as_missing(self):
        for name in ('LICENSE', 'README.md', 'RELEASE-NOTES.md'):
            (self.base / name).write_text('text', encoding='utf-8')
        (self.base / 'README.md').write_text('', encoding='utf-8')
        self.assertEqual(self.pkg.docs_preflight(self.base)['missing'], ['README.md'])

    def test_build_refuses_missing_docs_without_the_explicit_flag(self):
        with self.assertRaisesRegex(RuntimeError, 'docs'):
            self.pkg.require_docs(self.pkg.docs_preflight(self.base), allow_missing=False)
        self.assertFalse(self.pkg.require_docs(self.pkg.docs_preflight(self.base), allow_missing=True))


def make_distribution(site, name, version, files):
    info = site / f'{name}-{version}.dist-info'
    info.mkdir(parents=True)
    (info / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n', encoding='utf-8')
    records = []
    for relative, content in files.items():
        target = site / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
        records.append(f'{relative},,')
    (info / 'RECORD').write_text('\n'.join(records) + '\n', encoding='utf-8')
    importlib.invalidate_caches()


class LicenseNotices(TempCase):
    def setUp(self):
        super().setUp()
        self.site = self.base / 'site'
        self.site.mkdir()
        sys.path.insert(0, str(self.site))
        self.addCleanup(sys.path.remove, str(self.site))

    def test_notice_files_are_found_copied_and_hashed(self):
        make_distribution(self.site, 'fakeqt', '1.2.3', {
            'fakeqt/LICENSE.LGPLv3': 'lgpl text', 'fakeqt/code.py': 'x', 'fakeqt-1.2.3.dist-info/licenses/NOTICE': 'notice'})
        dest = self.base / 'out'
        found = self.pkg.collect_license_notices(['fakeqt'], dest)
        self.assertEqual(len(found['fakeqt']), 2)
        for item in found['fakeqt']:
            copied = dest / item['dest']
            self.assertTrue(copied.is_file())
            self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(), item['sha256'])
        self.assertNotIn('fakeqt/code.py', json.dumps(found))

    def test_distribution_without_notice_fails_clearly(self):
        make_distribution(self.site, 'bareqt', '1.0', {'bareqt/code.py': 'x'})
        with self.assertRaisesRegex(RuntimeError, 'bareqt.*license'):
            self.pkg.collect_license_notices(['bareqt'], self.base / 'out')

    def test_uninstalled_distribution_fails_clearly(self):
        with self.assertRaisesRegex(RuntimeError, 'notinstalled.*not installed'):
            self.pkg.collect_license_notices(['notinstalled'], self.base / 'out')

    def test_required_set_covers_the_qt_stack(self):
        required = {name.lower().replace('-', '_') for name in self.pkg.QT_NOTICE_DISTRIBUTIONS}
        self.assertTrue({'pyside6', 'pyside6_essentials', 'pyside6_addons', 'shiboken6'} <= required)

    def test_manifest_never_claims_license_compatibility(self):
        text = (REPO / 'package_scripted.py').read_text(encoding='utf-8').lower()
        self.assertNotIn('license-compatible', text)
        self.assertIn('not a legal', text)


class SourceInputs(TempCase):
    def test_inputs_are_hashed_sorted_and_skip_caches(self):
        root = self.base / 'repo'
        (root / 'full-engine' / 'DyberPet' / '__pycache__').mkdir(parents=True)
        (root / 'full-engine' / 'DyberPet' / 'a.py').write_text('a', encoding='utf-8')
        (root / 'full-engine' / 'DyberPet' / '__pycache__' / 'a.pyc').write_bytes(b'c')
        (root / 'VERSION').write_bytes(b'1.0.0-rc.1\n')
        (root / 'package_scripted.py').write_text('#', encoding='utf-8')
        inputs = self.pkg.source_inputs(root)
        self.assertEqual(list(inputs), sorted(inputs))
        self.assertIn('full-engine/DyberPet/a.py', inputs)
        self.assertIn('VERSION', inputs)
        self.assertFalse([k for k in inputs if '__pycache__' in k])
        self.assertEqual(inputs['VERSION']['sha256'], hashlib.sha256(b'1.0.0-rc.1\n').hexdigest())


class PreflightOnly(TempCase):
    def test_preflight_only_cli_fails_clearly_off_windows_without_building(self):
        if sys.platform == 'win32':
            self.skipTest('Windows host: preflight outcome depends on installed packages')
        result = subprocess.run([sys.executable, '-B', str(REPO / 'package_scripted.py'), '--preflight-only',
                                 '--output-dir', str(self.base / 'dist'), '--work-dir', str(self.base / 'work')],
                                capture_output=True, text=True, timeout=60, cwd=str(self.base))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('preflight', (result.stdout + result.stderr).lower())
        self.assertFalse((self.base / 'dist').exists(), 'preflight must not create output')


if __name__ == '__main__':
    unittest.main()
