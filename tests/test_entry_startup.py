"""Entry dispatch, startup-smoke lifecycle and spec regression tests.

Standard library only: these run on any Python 3.11+ without Qt, so they also
guard the frozen entry on machines that cannot import PySide6. Real Qt startup
is covered by test_startup_smoke_qt.py (skipped, loudly, when Qt is missing).
"""
import ast
import contextlib
import importlib.abc
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'full-engine'
ENTRY = ENGINE / 'packaging' / 'portable_entry.py'
SPEC = ENGINE / 'packaging' / 'MiniDraconia.spec'

if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))


def load_entry():
    spec = importlib.util.spec_from_file_location('portable_entry_under_test', ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALID_EVIDENCE = {
    'application': {'class': 'DyberPetApp', 'name': 'MiniDraconia', 'platform': 'offscreen'},
    'windows': [{'class': 'PetWidget', 'visible': True, 'width': 120, 'height': 140}],
    'sprite_pixels': 4200,
    'controls': {'menu_actions': ['Settings', 'Quit'], 'settings_panel_opened': True,
                 'control_panel_class': 'ControlMainWindow'},
    'timers': {'event_loop_ticks': 6, 'midnight_timer_active': True, 'midnight_timer_remaining_ms': 3600000},
}


class FakeApp(types.ModuleType):
    """Stands in for run_DyberPet and records what the entry did around it."""

    def __init__(self, behavior=None):
        super().__init__('run_DyberPet')
        self.calls = []
        self.import_env = None
        self.behavior = behavior or (lambda argv, probe: 0)

    def main(self, argv=None, probe=None):
        self.calls.append((list(argv or []), probe))
        return self.behavior(argv, probe)


class ImportRecorder(importlib.abc.MetaPathFinder):
    """Serves the fake run_DyberPet and snapshots the environment at import time."""

    def __init__(self, fake, environ):
        self.fake, self.environ = fake, environ

    def find_spec(self, name, path=None, target=None):
        if name != 'run_DyberPet':
            return None
        self.fake.import_env = dict(self.environ)
        spec = importlib.machinery.ModuleSpec(name, _FakeLoader(self.fake))
        return spec


class _FakeLoader(importlib.abc.Loader):
    def __init__(self, fake):
        self.fake = fake

    def create_module(self, spec):
        return self.fake

    def exec_module(self, module):
        pass


class EntryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.install = self.base / 'install dir'  # spaces on purpose
        self.install.mkdir()
        self.entry = load_entry()
        self.cwd = os.getcwd()
        self.addCleanup(os.chdir, self.cwd)
        sys.modules.pop('run_DyberPet', None)
        self.addCleanup(sys.modules.pop, 'run_DyberPet', None)

    def run_main(self, argv, environ=None, behavior=None, notify=None):
        # Unit tests must never open a real GUI dialog (on Windows MessageBoxW blocks in
        # SSH/session 0). Default to a no-op; pass an explicit collector to test notifications.
        notify = (lambda title, message: None) if notify is None else notify
        environ = {} if environ is None else environ
        fake = FakeApp(behavior)
        recorder = ImportRecorder(fake, environ)
        sys.meta_path.insert(0, recorder)
        self.addCleanup(lambda: recorder in sys.meta_path and sys.meta_path.remove(recorder))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = self.entry.main(argv, environ=environ, root=self.install, notify=notify)
        sys.meta_path.remove(recorder)
        return code, fake, err.getvalue()

    def fresh_profile(self, name='profile'):
        return self.base / name  # does not exist yet: fresh


class NormalDispatch(EntryCase):
    def test_normal_branch_hands_over_to_the_real_app_module(self):
        profile = self.fresh_profile()
        code, fake, _ = self.run_main([], {'MINIDRACONIA_TEST_PROFILE': str(profile)})
        self.assertEqual(code, 0)
        self.assertEqual(len(fake.calls), 1)
        self.assertIsNone(fake.calls[0][1], 'normal start must not carry a smoke probe')
        self.assertTrue(profile.is_dir())

    def test_normal_branch_does_not_force_offscreen_or_mute(self):
        env = {'MINIDRACONIA_TEST_PROFILE': str(self.fresh_profile())}
        self.run_main([], env)
        self.assertNotIn('QT_QPA_PLATFORM', env)
        self.assertNotIn('MINIDRACONIA_MUTE', env)

    def test_normal_default_profile_comes_from_localappdata(self):
        local = self.base / 'local'
        env = {'LOCALAPPDATA': str(local)}
        code, _, _ = self.run_main([], env)
        self.assertEqual(code, 0)
        self.assertEqual(Path(env['MINIDRACONIA_TEST_PROFILE']), local / 'MiniDraconia-Scripted')

    def test_relative_profile_is_a_usage_error_not_a_crash(self):
        code, fake, err = self.run_main([], {'MINIDRACONIA_TEST_PROFILE': 'relative/profile'})
        self.assertEqual(code, 2)
        self.assertFalse(fake.calls)
        self.assertIn('absolute', err.lower())

    def test_normal_failure_is_nonzero_leaves_diagnostic_and_notifies(self):
        profile = self.fresh_profile()
        shown = []
        def boom(argv, probe):
            raise RuntimeError('construction failed')
        env = {'MINIDRACONIA_TEST_PROFILE': str(profile), 'SOME_API_KEY': 'sk-should-never-be-logged'}
        code, _, _ = self.run_main([], env, behavior=boom, notify=lambda t, m: shown.append((t, m)))
        self.assertEqual(code, 1)
        diagnostic = (profile / 'startup-diagnostic.txt').read_text(encoding='utf-8')
        self.assertIn('RuntimeError: construction failed', diagnostic)
        self.assertNotIn('sk-should-never-be-logged', diagnostic)
        self.assertEqual(len(shown), 1)
        self.assertIn('startup-diagnostic.txt', shown[0][1])
        self.assertNotIn('sk-should-never-be-logged', shown[0][1])

    def test_system_exit_from_the_app_is_not_swallowed(self):
        def quits(argv, probe):
            raise SystemExit(0)
        with self.assertRaises(SystemExit):
            self.run_main([], {'MINIDRACONIA_TEST_PROFILE': str(self.fresh_profile())}, behavior=quits)

    def test_module_name_matches_what_the_frozen_build_must_collect(self):
        self.assertEqual(self.entry.NORMAL_MODULE, 'run_DyberPet')


class SmokeDispatch(EntryCase):
    def smoke_args(self, report=None):
        report = report or self.base / 'out' / 'smoke.json'
        report.parent.mkdir(exist_ok=True)
        return ['--startup-smoke', '--report', str(report)], report

    def env(self, **extra):
        return dict({'MINIDRACONIA_TEST_PROFILE': str(self.fresh_profile())}, **extra)

    def test_mute_and_offscreen_are_set_before_the_app_module_is_imported(self):
        args, _ = self.smoke_args()
        env = self.env()
        _, fake, _ = self.run_main(args, env, behavior=lambda a, p: 0)
        self.assertIsNotNone(fake.import_env, 'smoke must import the same module as the normal path')
        self.assertEqual(fake.import_env.get('QT_QPA_PLATFORM'), 'offscreen')
        self.assertEqual(fake.import_env.get('MINIDRACONIA_MUTE'), '1')

    def test_smoke_follows_normal_branch_with_a_probe_not_selftest(self):
        args, _ = self.smoke_args()
        _, fake, _ = self.run_main(args, self.env(), behavior=lambda a, p: 0)
        self.assertEqual(len(fake.calls), 1)
        probe = fake.calls[0][1]
        self.assertIsNotNone(probe)
        self.assertTrue(callable(getattr(probe, 'attach', None)))

    def test_clean_run_with_real_evidence_writes_ok_report_and_exits_zero(self):
        args, report = self.smoke_args()
        def app(argv, probe):
            probe.record(json.loads(json.dumps(VALID_EVIDENCE)))
            return 0
        code, _, _ = self.run_main(args, self.env(), behavior=app)
        data = json.loads(report.read_text(encoding='utf-8'))
        self.assertEqual(code, 0, data)
        self.assertTrue(data['ok'])
        self.assertEqual(data['exit_code'], 0)
        self.assertEqual(data['mode'], 'startup-smoke')
        self.assertEqual(data['evidence']['application']['class'], 'DyberPetApp')

    def test_zero_exit_without_evidence_is_a_failure_not_a_pass(self):
        args, report = self.smoke_args()
        code, _, _ = self.run_main(args, self.env(), behavior=lambda a, p: 0)
        self.assertEqual(code, 1)
        data = json.loads(report.read_text(encoding='utf-8'))
        self.assertFalse(data['ok'])
        self.assertTrue(data['failures'])

    def test_nonzero_app_exit_is_a_failure_even_with_evidence(self):
        args, report = self.smoke_args()
        def app(argv, probe):
            probe.record(json.loads(json.dumps(VALID_EVIDENCE)))
            return 3
        code, _, _ = self.run_main(args, self.env(), behavior=app)
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(report.read_text(encoding='utf-8'))['ok'])

    def test_construction_failure_gives_nonzero_trace_and_failure_report_without_dialog(self):
        args, report = self.smoke_args()
        env = self.env(MINIDRACONIA_FAKE_TOKEN='token-should-not-leak')
        shown = []
        def boom(argv, probe):
            raise ValueError('pet could not be built')
        code, _, _ = self.run_main(args, env, behavior=boom, notify=lambda t, m: shown.append(m))
        self.assertEqual(code, 1)
        profile = Path(env['MINIDRACONIA_TEST_PROFILE'])
        trace = (profile / 'startup-diagnostic.txt').read_text(encoding='utf-8')
        self.assertIn('ValueError: pet could not be built', trace)
        self.assertNotIn('token-should-not-leak', trace)
        data = json.loads(report.read_text(encoding='utf-8'))
        self.assertFalse(data['ok'])
        self.assertIn('ValueError', data['error'])
        self.assertNotIn('token-should-not-leak', json.dumps(data))
        self.assertEqual(shown, [], 'automation must never block on a dialog')

    def test_callback_exception_reported_by_the_hook_fails_the_smoke_and_restores_the_hook(self):
        args, report = self.smoke_args()
        original = sys.excepthook
        def app(argv, probe):
            probe.record(json.loads(json.dumps(VALID_EVIDENCE)))
            sys.excepthook(KeyError, KeyError('timer callback failed'), None)  # what Qt does for a raising slot
            return 0
        code, _, err = self.run_main(args, self.env(), behavior=app)
        self.assertEqual(code, 1, 'app.exec returned 0 but a callback raised: must be nonzero')
        data = json.loads(report.read_text(encoding='utf-8'))
        self.assertFalse(data['ok'])
        self.assertEqual(data['callback_exceptions']['count'], 1)
        self.assertIn('KeyError', err, 'traceback keeps flowing to the previous hook')
        self.assertIs(sys.excepthook, original)

    def test_hook_is_restored_when_the_app_raises_and_not_touched_in_normal_mode(self):
        args, _ = self.smoke_args()
        original = sys.excepthook
        def boom(argv, probe):
            raise ValueError('construction failed')
        self.run_main(args, self.env(), behavior=boom)
        self.assertIs(sys.excepthook, original)
        sys.modules.pop('run_DyberPet', None)  # the first fake is cached; the second call needs its own
        seen = []
        def normal(argv, probe):
            seen.append(sys.excepthook)
            return 0
        self.run_main([], {'MINIDRACONIA_TEST_PROFILE': str(self.fresh_profile('normal'))}, behavior=normal)
        self.assertEqual(seen, [original], 'normal-user mode must not install a hook')

    def test_selftest_stays_a_separate_branch(self):
        report = self.base / 'selftest.json'
        fake_brain = types.ModuleType('DyberPet.brain.selftest')
        fake_brain.exercise_product = lambda: {'quit_code': 0}
        saved = {k: sys.modules.get(k) for k in ('DyberPet.brain.selftest',)}
        sys.modules['DyberPet.brain.selftest'] = fake_brain
        self.addCleanup(lambda: sys.modules.pop('DyberPet.brain.selftest', None) if saved['DyberPet.brain.selftest'] is None
                        else sys.modules.__setitem__('DyberPet.brain.selftest', saved['DyberPet.brain.selftest']))
        env = {'MINIDRACONIA_TEST_PROFILE': str(self.fresh_profile())}
        code, fake, _ = self.run_main(['--selftest-scripted', '--report', str(report)], env)
        self.assertEqual(code, 0)
        self.assertFalse(fake.calls, 'selftest must not start the application')
        self.assertEqual(env.get('QT_QPA_PLATFORM'), 'offscreen')
        self.assertEqual(json.loads(report.read_text(encoding='utf-8')), {'quit_code': 0})


class InvalidArguments(EntryCase):
    def test_helper_default_notify_is_a_noop_never_the_real_dialog(self):
        # Guard for the Windows hang: the helper must not fall through to show_error_dialog.
        called = []
        original = self.entry.show_error_dialog
        self.entry.show_error_dialog = lambda t, m: called.append(m)
        self.addCleanup(setattr, self.entry, 'show_error_dialog', original)
        code, _, _ = self.run_main(['--bogus-normal', '--report', 'x.json'], {})
        self.assertEqual(code, 2)
        self.assertEqual(called, [], 'run_main default must inject a no-op notify, not the real dialog')

    def test_malformed_automated_argv_never_notifies(self):
        # Root cause of the Windows timeout: parse_args raised before Options existed, so the
        # entry treated an automated invocation as normal and showed a modal MessageBox.
        cases = [
            ['--startup-smoke', '--report', 'relative.json'],
            ['--selftest-scripted', '--report', 'relative.json'],
            ['--startup-smoke', '--report'],
            ['--selftest-scripted', '--report', '--other'],
            ['--startup-smoke'],
            ['--selftest-scripted'],
            ['--startup-smoke', '--selftest-scripted', '--report', str(self.base / 'r.json')],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                shown = []
                code, fake, err = self.run_main(argv, self.ok_env(), notify=lambda t, m: shown.append((t, m)))
                self.assertEqual(code, 2, err)
                self.assertFalse(fake.calls)
                self.assertEqual(shown, [], 'automated mode must never show a modal dialog')
                self.assertIn('minidraconia:', err.lower(), 'the error still reaches stderr')

    def test_automated_usage_errors_after_options_never_notify(self):
        for argv, env in (
            (['--startup-smoke', '--report', str(self.base / 'r.json')], {}),
            (['--selftest-scripted', '--report', str(self.base / 'r.json')], {'MINIDRACONIA_TEST_PROFILE': 'rel'}),
        ):
            with self.subTest(argv=argv):
                shown = []
                code, _, _ = self.run_main(argv, env, notify=lambda t, m: shown.append(m))
                self.assertEqual(code, 2)
                self.assertEqual(shown, [])

    def test_normal_user_errors_still_show_a_useful_dialog(self):
        shown = []
        code, fake, _ = self.run_main(['--report', str(self.base / 'r.json')], self.ok_env(),
                                      notify=lambda t, m: shown.append((t, m)))
        self.assertEqual(code, 2)
        self.assertFalse(fake.calls)
        self.assertEqual(len(shown), 1)
        self.assertEqual(shown[0][0], 'MiniDraconia')
        self.assertIn('could not start', shown[0][1])
        self.assertIn('--report', shown[0][1])
        shown.clear()
        code, _, _ = self.run_main([], {'MINIDRACONIA_TEST_PROFILE': 'relative/profile'},
                                   notify=lambda t, m: shown.append(m))
        self.assertEqual(code, 2)
        self.assertEqual(len(shown), 1)
        self.assertIn('absolute', shown[0])

    def check_usage(self, argv, env, fragment):
        code, fake, err = self.run_main(argv, env)
        self.assertEqual(code, 2, err)
        self.assertFalse(fake.calls, 'the app must not start on invalid arguments')
        self.assertIn(fragment, err.lower())

    def ok_env(self):
        return {'MINIDRACONIA_TEST_PROFILE': str(self.fresh_profile())}

    def test_smoke_requires_report(self):
        self.check_usage(['--startup-smoke'], self.ok_env(), '--report')

    def test_report_without_value(self):
        self.check_usage(['--startup-smoke', '--report'], self.ok_env(), '--report')

    def test_relative_report_rejected(self):
        self.check_usage(['--startup-smoke', '--report', 'smoke.json'], self.ok_env(), 'absolute')

    def test_report_inside_install_rejected(self):
        self.check_usage(['--startup-smoke', '--report', str(self.install / 'smoke.json')], self.ok_env(), 'install')

    def test_report_inside_profile_rejected(self):
        env = self.ok_env()
        report = Path(env['MINIDRACONIA_TEST_PROFILE']) / 'smoke.json'
        self.check_usage(['--startup-smoke', '--report', str(report)], env, 'profile')

    def test_existing_report_not_overwritten(self):
        report = self.base / 'old.json'
        report.write_text('stale', encoding='utf-8')
        self.check_usage(['--startup-smoke', '--report', str(report)], self.ok_env(), 'exists')
        self.assertEqual(report.read_text(encoding='utf-8'), 'stale')

    def test_report_parent_must_exist(self):
        self.check_usage(['--startup-smoke', '--report', str(self.base / 'missing' / 'r.json')], self.ok_env(), 'directory')

    def test_smoke_and_selftest_are_mutually_exclusive(self):
        self.check_usage(['--startup-smoke', '--selftest-scripted', '--report', str(self.base / 'r.json')],
                         self.ok_env(), 'together')

    def test_smoke_requires_explicit_profile(self):
        self.check_usage(['--startup-smoke', '--report', str(self.base / 'r.json')], {}, 'profile')

    def test_smoke_rejects_relative_profile(self):
        self.check_usage(['--startup-smoke', '--report', str(self.base / 'r.json')],
                         {'MINIDRACONIA_TEST_PROFILE': 'rel'}, 'absolute')

    def test_smoke_rejects_used_profile(self):
        used = self.base / 'used'
        used.mkdir()
        (used / 'state.json').write_text('{}', encoding='utf-8')
        self.check_usage(['--startup-smoke', '--report', str(self.base / 'r.json')],
                         {'MINIDRACONIA_TEST_PROFILE': str(used)}, 'fresh')

    def test_smoke_accepts_existing_empty_profile(self):
        empty = self.base / 'empty'
        empty.mkdir()
        code, fake, _ = self.run_main(['--startup-smoke', '--report', str(self.base / 'r.json')],
                                      {'MINIDRACONIA_TEST_PROFILE': str(empty)})
        self.assertEqual(len(fake.calls), 1)

    def test_smoke_rejects_profile_inside_install(self):
        self.check_usage(['--startup-smoke', '--report', str(self.base / 'r.json')],
                         {'MINIDRACONIA_TEST_PROFILE': str(self.install / 'profile')}, 'install')

    def test_selftest_requires_report_and_profile(self):
        self.check_usage(['--selftest-scripted'], self.ok_env(), '--report')
        self.check_usage(['--selftest-scripted', '--report', str(self.base / 'r.json')], {}, 'profile')


class SpecCollectsEveryModuleTheEntryNeeds(unittest.TestCase):
    """Root cause of the frozen exit-1: the spec never collected run_DyberPet."""

    @classmethod
    def evaluate_spec(cls):
        captured = {}
        class Recorder:
            def __init__(self, *args, **kwargs):
                self.args, self.kwargs = args, kwargs
                self.pure, self.scripts, self.binaries, self.datas = [], [], [], []
                captured.setdefault(type(self).__name__, []).append(self)
        def make(name):
            return type(name, (Recorder,), {})
        hooks = types.ModuleType('PyInstaller.utils.hooks')
        hooks.collect_submodules = lambda name: [name, name + '.settings', name + '.brain.local']
        hooks.collect_all = lambda name: ([], [], [name])
        modules = {'PyInstaller': types.ModuleType('PyInstaller'), 'PyInstaller.utils': types.ModuleType('PyInstaller.utils'),
                   'PyInstaller.utils.hooks': hooks}
        scope = {'SPECPATH': str(ENGINE / 'packaging'), '__file__': str(SPEC),
                 'Analysis': make('Analysis'), 'PYZ': make('PYZ'), 'EXE': make('EXE'), 'COLLECT': make('COLLECT')}
        saved = {k: sys.modules.get(k) for k in modules}
        sys.modules.update(modules)
        try:
            exec(compile(SPEC.read_text(encoding='utf-8'), str(SPEC), 'exec'), scope)
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        return captured['Analysis'][0].kwargs, scope

    def test_normal_module_is_collected_and_resolvable(self):
        entry = load_entry()
        kwargs, _ = self.evaluate_spec()
        self.assertIn(entry.NORMAL_MODULE, kwargs['hiddenimports'])
        self.assertTrue(any(Path(p) == ENGINE for p in kwargs['pathex']))
        self.assertTrue((ENGINE / (entry.NORMAL_MODULE + '.py')).is_file())

    def test_run_dyberpet_literal_is_collected_by_the_spec(self):
        # Independent of the entry API: the exact module the baseline entry runs.
        kwargs, _ = self.evaluate_spec()
        self.assertIn('run_DyberPet', kwargs['hiddenimports'])

    def test_smoke_module_is_collected(self):
        kwargs, _ = self.evaluate_spec()
        self.assertIn('DyberPet.startup_smoke', kwargs['hiddenimports'])

    def test_version_file_is_bundled_at_the_resource_root(self):
        kwargs, _ = self.evaluate_spec()
        self.assertIn((str(REPO / 'VERSION'), '.'), [(str(s), d) for s, d in kwargs['datas']])

    def test_inference_stack_stays_excluded(self):
        kwargs, _ = self.evaluate_spec()
        for name in ('DyberPet.brain.local', 'onnxruntime', 'kokoro_onnx', 'scipy'):
            self.assertIn(name, kwargs['excludes'])
        self.assertNotIn('DyberPet.brain.local', kwargs['hiddenimports'])

    def test_frozen_import_would_succeed_only_for_collected_modules(self):
        """Simulated frozen importer: only spec-collected names resolve."""
        entry = load_entry()
        kwargs, _ = self.evaluate_spec()
        collected = set(kwargs['hiddenimports'])
        self.assertIn(entry.NORMAL_MODULE, collected, 'frozen launch would raise ImportError: No module named run_DyberPet')


class OptionalImportsFailSafely(unittest.TestCase):
    FORBIDDEN = {'onnxruntime', 'kokoro_onnx', 'scipy', 'soundfile'}

    def top_level_imports(self, path):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        found = []
        for node in tree.body:
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split('.')[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split('.')[0]]
            elif isinstance(node, (ast.Try, ast.If)):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Import):
                        names += [a.name.split('.')[0] for a in sub.names]
                    elif isinstance(sub, ast.ImportFrom) and sub.module:
                        names.append(sub.module.split('.')[0])
            found += [n for n in names if n in self.FORBIDDEN]
        return found

    def test_no_import_time_use_of_the_retired_inference_stack(self):
        offenders = {}
        for path in list((ENGINE / 'DyberPet').rglob('*.py')) + [ENGINE / 'run_DyberPet.py']:
            hits = self.top_level_imports(path)
            if hits:
                offenders[str(path.relative_to(REPO))] = hits
        self.assertEqual(offenders, {})

    def test_preload_does_not_import_onnxruntime(self):
        source = (ENGINE / 'DyberPet' / '_msvc_preload.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        imported = {a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertNotIn('onnxruntime', imported)

    def test_upstream_update_endpoints_are_unreferenced(self):
        offenders = []
        for path in list((ENGINE / 'DyberPet').rglob('*.py')) + [ENGINE / 'run_DyberPet.py']:
            text = path.read_text(encoding='utf-8')
            for token in ('RELEASE_API', 'RELEASE_URL', 'UPDATE_NEEDED', 'releases/latest'):
                if token in text:
                    offenders.append((str(path.relative_to(REPO)), token))
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main()
