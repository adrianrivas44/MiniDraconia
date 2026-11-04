"""Requirements, .gitignore and the standard-library test runner."""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RETIRED = {'kokoro-onnx', 'kokoro_onnx', 'onnxruntime', 'scipy', 'soundfile', 'phonemizer', 'espeakng-loader',
           'espeakng_loader', 'pytest', 'joblib', 'protobuf', 'flatbuffers'}


def requirement_names(path):
    names = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if not line or line.startswith('-'):
            continue
        match = re.match(r'^([A-Za-z0-9_.-]+)\s*(==|>=|~=|<)?\s*([^;\s,]*)', line)
        names[match.group(1).lower().replace('_', '-')] = (match.group(2), match.group(3), line)
    return names


class Requirements(unittest.TestCase):
    def test_runtime_pins_match_the_verified_environment(self):
        names = requirement_names(REPO / 'requirements.txt')
        expected = {'pyside6': '6.5.3', 'pyside6-essentials': '6.5.3', 'pyside6-addons': '6.5.3', 'shiboken6': '6.5.3',
                    'pyside6-fluent-widgets': '1.5.4', 'pysidesix-frameless-window': '0.8.2', 'apscheduler': '3.11.3',
                    'pynput': '1.8.2', 'tendo': '0.3.0', 'darkdetect': '0.8.0', 'six': '1.17.0',
                    'tzlocal': '5.4.4', 'tzdata': '2026.5', 'numpy': '1.26.4', 'pillow': '12.3.0', 'pywin32': '312'}
        for name, version in expected.items():
            self.assertIn(name, names)
            self.assertEqual(names[name][:2], ('==', version), name)

    def test_pywin32_is_windows_only(self):
        self.assertRegex(requirement_names(REPO / 'requirements.txt')['pywin32'][2], r"sys_platform\s*==\s*['\"]win32['\"]")

    def test_retired_inference_stack_is_not_required(self):
        for filename in ('requirements.txt', 'requirements-dev.txt'):
            self.assertFalse(RETIRED & set(requirement_names(REPO / filename)), filename)

    def test_dev_requirements_include_runtime_and_the_verified_pyinstaller_pin(self):
        text = (REPO / 'requirements-dev.txt').read_text(encoding='utf-8')
        self.assertIn('-r requirements.txt', text)
        operator, version, line = requirement_names(REPO / 'requirements-dev.txt')['pyinstaller']
        # 6.16.0 is the version verified from the copied dist metadata. An exact pin is the tightest
        # bound; any other form must still carry an upper bound. Nothing unbounded passes.
        if operator == '==':
            self.assertEqual(version, '6.16.0', line)
        else:
            self.assertRegex(line, r'<\s*\d', 'PyInstaller must be pinned or have an upper bound: ' + line)

    def test_no_private_paths_or_indexes_in_requirements(self):
        for filename in ('requirements.txt', 'requirements-dev.txt'):
            text = (REPO / filename).read_text(encoding='utf-8')
            for marker in ('--index-url', '--extra-index-url', 'file:', 'D:\\', '/root/', '@ http'):
                self.assertNotIn(marker, text, (filename, marker))


def git_unavailable_reason():
    """None when `git --version` really runs; otherwise the actual failure.

    A `which` hit is not availability: a git.exe that exists but is denied (or broken) must
    be reported as the real reason for the skip, never as a silent pass.
    """
    try:
        done = subprocess.run(['git', '--version'], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return 'git did not run: %s: %s' % (type(exc).__name__, exc)
    if done.returncode != 0 or not done.stdout.startswith('git version'):
        return 'git --version failed: rc=%s %s' % (done.returncode, (done.stderr or done.stdout).strip()[:200])
    return None


class GitIgnore(unittest.TestCase):
    """.gitignore semantics, checked in a DISPOSABLE repository.

    The source archive has no .git and the real repo's config is never touched: the
    .gitignore under test is copied into a fresh temporary repo.
    """

    @classmethod
    def setUpClass(cls):
        reason = git_unavailable_reason()
        if reason:
            raise unittest.SkipTest('NOT RUN: ' + reason)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.repo = Path(cls.tmp.name) / 'fixture-repo'
        cls.repo.mkdir()
        cls.env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_DIR=str(cls.repo / '.git'), GIT_WORK_TREE=str(cls.repo))
        init = subprocess.run(['git', 'init', '-q'], capture_output=True, text=True, cwd=str(cls.repo), env=cls.env, timeout=60)
        if init.returncode != 0:
            raise AssertionError('git is runnable but could not init a disposable repo: ' + init.stderr)
        shutil.copyfile(REPO / '.gitignore', cls.repo / '.gitignore')

    def ignored(self, paths):
        # NUL-delimited UTF-8 avoids Windows newline translation, locale encoding and Git quoting.
        payload = b'\0'.join(path.encode('utf-8') for path in paths) + b'\0'
        result = subprocess.run(['git', 'check-ignore', '--no-index', '-z', '--stdin'], input=payload,
                                capture_output=True, cwd=str(self.repo), env=self.env, timeout=60)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return {path.decode('utf-8') for path in result.stdout.split(b'\0') if path}

    def test_spaces_and_unicode_paths_round_trip_losslessly(self):
        ignored = ['logs/untracked file.log', '\u65e5\u5fd7/\u8bb0\u5f55.log']
        required = 'full-engine/res/icons/\u4e2d\u6587 name.png'
        self.assertEqual(self.ignored(ignored + [required]), set(ignored))

    def test_fixture_is_not_the_real_repository(self):
        self.assertNotEqual(self.repo.resolve(), REPO.resolve())
        self.assertFalse(self.repo.resolve().is_relative_to(REPO.resolve()))

    def test_personal_state_and_build_outputs_are_ignored(self):
        ignored = self.ignored(['.env', '.env.local', 'work/x', 'dist/a.zip', 'build/x', 'buildtools/p.py', '.venv/x',
                                'a/__pycache__/m.pyc', 'x.log', 'profiles/u.json', 'credentials.json', 'secrets.json',
                                'x.pem', 'id_rsa', '.claude/settings.local.json', 'evidence/x.json', 'staging/x'])
        for path in ('.env', '.env.local', 'work/x', 'dist/a.zip', 'build/x', 'buildtools/p.py', '.venv/x', 'a/__pycache__/m.pyc',
                     'x.log', 'profiles/u.json', 'credentials.json', 'secrets.json', 'x.pem', 'id_rsa'):
            self.assertIn(path, ignored, path)

    def test_required_product_data_and_resources_are_not_ignored(self):
        required = []
        for top in ('full-engine/DyberPet', 'full-engine/data', 'full-engine/config', 'full-engine/licenses',
                    'full-engine/res', 'full-engine/packaging', 'tests', 'scripts', 'third_party'):
            base = REPO / top
            if base.is_dir():
                required += [str(p.relative_to(REPO).as_posix()) for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
        required += [name for name in ('LICENSE', 'VERSION', 'requirements.txt', 'requirements-dev.txt', 'package_scripted.py',
                                       'full-engine/LICENSE', 'full-engine/run_DyberPet.py') if (REPO / name).is_file()]
        self.assertGreater(len(required), 1000)
        self.assertEqual(sorted(self.ignored(required)), [])


class GitAvailabilityProbe(unittest.TestCase):
    def test_a_which_hit_alone_is_not_availability(self):
        from unittest import mock
        denied = subprocess.CompletedProcess(['git', '--version'], 1, '', 'Access is denied.')
        with mock.patch.object(subprocess, 'run', return_value=denied):
            self.assertIn('Access is denied', git_unavailable_reason())
        with mock.patch.object(subprocess, 'run', side_effect=PermissionError(13, 'Access is denied')):
            self.assertIn('PermissionError', git_unavailable_reason())
        ok = subprocess.CompletedProcess(['git', '--version'], 0, 'git version 2.45.0\n', '')
        with mock.patch.object(subprocess, 'run', return_value=ok):
            self.assertIsNone(git_unavailable_reason())

    def test_git_tests_do_not_need_a_dot_git_in_the_source_tree(self):
        # The class builds its own repo; it must not call git with cwd=REPO.
        source = Path(__file__).read_text(encoding='utf-8')
        body = source[source.index('class GitIgnore'):source.index('class GitAvailabilityProbe')]
        self.assertNotIn('cwd=str(REPO)', body)


class TestRunner(unittest.TestCase):
    def test_runner_sets_a_fresh_profile_before_imports_and_reports_counts(self):
        runner = REPO / 'scripts' / 'run_tests.py'
        self.assertTrue(runner.is_file(), 'scripts/run_tests.py missing')
        with tempfile.TemporaryDirectory() as base:
            suite = Path(base) / 'suite'
            suite.mkdir()
            (suite / 'test_probe.py').write_text(
                'import os, unittest\n'
                'PROFILE = os.environ.get("MINIDRACONIA_TEST_PROFILE", "")\n'
                'class T(unittest.TestCase):\n'
                '    def test_profile_is_absolute_and_fresh(self):\n'
                '        self.assertTrue(os.path.isabs(PROFILE))\n'
                '        self.assertFalse(os.listdir(PROFILE))\n'
                '    def test_env(self):\n'
                '        self.assertEqual(os.environ["QT_QPA_PLATFORM"], "offscreen")\n'
                '        self.assertEqual(os.environ["MINIDRACONIA_MUTE"], "1")\n'
                '    @unittest.skip("reason here")\n'
                '    def test_skipped(self): pass\n', encoding='utf-8')
            env = {k: v for k, v in os.environ.items() if k not in ('MINIDRACONIA_TEST_PROFILE', 'QT_QPA_PLATFORM', 'MINIDRACONIA_MUTE')}
            result = subprocess.run([sys.executable, '-B', str(runner), '--start-dir', str(suite)], capture_output=True, text=True,
                                    env=env, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertRegex(result.stdout, r'ran=3\b')
            self.assertRegex(result.stdout, r'skipped=1\b')
            self.assertRegex(result.stdout, r'failures=0\b')

    def test_runner_exits_nonzero_on_failure(self):
        runner = REPO / 'scripts' / 'run_tests.py'
        with tempfile.TemporaryDirectory() as base:
            suite = Path(base) / 'suite'
            suite.mkdir()
            (suite / 'test_bad.py').write_text('import unittest\nclass T(unittest.TestCase):\n    def test_x(self): self.fail("no")\n', encoding='utf-8')
            result = subprocess.run([sys.executable, '-B', str(runner), '--start-dir', str(suite)], capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 1)
            self.assertRegex(result.stdout, r'failures=1\b')


if __name__ == '__main__':
    unittest.main()
