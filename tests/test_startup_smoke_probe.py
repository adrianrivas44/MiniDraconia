"""Smoke probe evaluation rules (stdlib only) and the real Qt startup smoke.

The evaluator must reject empty or inconsistent evidence; the Qt test is the
real thing: it starts the NORMAL branch of the entry and is skipped, with an
explicit reason, only when PySide6/qfluentwidgets are not importable.
"""
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'full-engine'
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from test_entry_startup import VALID_EVIDENCE  # noqa: E402


class EvaluateEvidence(unittest.TestCase):
    def evaluate(self, evidence):
        from DyberPet.startup_smoke import evaluate
        return evaluate(evidence)

    def mutated(self, mutate):
        evidence = copy.deepcopy(VALID_EVIDENCE)
        mutate(evidence)
        return evidence

    def test_real_shaped_evidence_passes(self):
        self.assertEqual(self.evaluate(copy.deepcopy(VALID_EVIDENCE)), [])

    def test_missing_or_empty_evidence_fails(self):
        for value in (None, {}, [], 'ok'):
            self.assertTrue(self.evaluate(value), value)

    def test_each_missing_proof_is_reported(self):
        cases = {
            'no windows': lambda e: e.update(windows=[]),
            'no pet widget': lambda e: e.update(windows=[{'class': 'QWidget', 'visible': True, 'width': 5, 'height': 5}]),
            'hidden pet': lambda e: e['windows'][0].update(visible=False),
            'zero size pet': lambda e: e['windows'][0].update(width=0),
            'blank sprite': lambda e: e.update(sprite_pixels=0),
            'event loop never ticked': lambda e: e['timers'].update(event_loop_ticks=0),
            'one tick only': lambda e: e['timers'].update(event_loop_ticks=1),
            'midnight timer inactive': lambda e: e['timers'].update(midnight_timer_active=False),
            'no controls': lambda e: e['controls'].update(menu_actions=[]),
            'no quit action': lambda e: e['controls'].update(menu_actions=['Settings']),
            'settings never opened': lambda e: e['controls'].update(settings_panel_opened=False),
            'wrong platform': lambda e: e['application'].update(platform='windows'),
            'no application': lambda e: e.pop('application'),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                self.assertTrue(self.evaluate(self.mutated(mutate)), name)

    def test_booleans_do_not_count_as_numbers(self):
        self.assertTrue(self.evaluate(self.mutated(lambda e: e['timers'].update(event_loop_ticks=True))))
        self.assertTrue(self.evaluate(self.mutated(lambda e: e.update(sprite_pixels=True))))


class BuildReport(unittest.TestCase):
    def probe(self):
        from DyberPet.startup_smoke import SmokeProbe
        return SmokeProbe('/tmp/unused-report.json')

    def test_report_fields_are_derived_not_declared(self):
        probe = self.probe()
        probe.record(copy.deepcopy(VALID_EVIDENCE))
        report = probe.build_report(0)
        self.assertTrue(report['ok'])
        self.assertEqual(report['mode'], 'startup-smoke')
        self.assertEqual(report['failures'], [])

    def test_exit_code_and_missing_evidence_fail(self):
        probe = self.probe()
        self.assertFalse(probe.build_report(0)['ok'])
        probe.record(copy.deepcopy(VALID_EVIDENCE))
        self.assertFalse(probe.build_report(1)['ok'])

    def test_error_text_forces_failure(self):
        probe = self.probe()
        probe.record(copy.deepcopy(VALID_EVIDENCE))
        report = probe.build_report(0, error='ValueError: boom')
        self.assertFalse(report['ok'])
        self.assertEqual(report['error'], 'ValueError: boom')


class CallbackFailureCapture(unittest.TestCase):
    """Exceptions Qt only prints from timer/signal callbacks must not leave a green report."""

    def probe(self):
        from types import SimpleNamespace
        from DyberPet.startup_smoke import SmokeProbe
        self.original_calls = []
        self.stand_in = SimpleNamespace(excepthook=lambda t, e, tb: self.original_calls.append((t, str(e))))
        self.original = self.stand_in.excepthook
        probe = SmokeProbe('/tmp/unused-report.json', sys_module=self.stand_in)
        probe.record(copy.deepcopy(VALID_EVIDENCE))
        return probe

    def test_captured_callback_exception_makes_the_report_not_ok(self):
        probe = self.probe()
        probe.install_excepthook()
        self.stand_in.excepthook(AttributeError, AttributeError("'QRect' object has no attribute 'geometry'"), None)
        report = probe.build_report(0)
        self.assertFalse(report['ok'])
        self.assertEqual(report['exit_code'], 0)
        self.assertEqual(report['callback_exceptions']['count'], 1)
        self.assertIn('AttributeError', report['failures'][0])

    def test_traceback_still_reaches_the_previous_hook(self):
        probe = self.probe()
        probe.install_excepthook()
        self.stand_in.excepthook(ValueError, ValueError('boom'), None)
        self.assertEqual(self.original_calls, [(ValueError, 'boom')])

    def test_original_hook_is_restored_and_install_is_idempotent(self):
        probe = self.probe()
        probe.install_excepthook()
        installed = self.stand_in.excepthook
        probe.install_excepthook()
        self.assertIs(self.stand_in.excepthook, installed)
        probe.restore_excepthook()
        self.assertIs(self.stand_in.excepthook, self.original)
        probe.restore_excepthook()
        self.assertIs(self.stand_in.excepthook, self.original)

    def test_no_failures_without_a_captured_exception_and_no_hook_before_install(self):
        probe = self.probe()
        self.assertIs(self.stand_in.excepthook, self.original, 'constructing the probe must not install a hook')
        self.assertTrue(probe.build_report(0)['ok'])

    def test_recorded_failures_are_bounded_but_counted(self):
        probe = self.probe()
        probe.install_excepthook()
        for _ in range(probe.MAX_RECORDED_CALLBACK_FAILURES + 5):
            self.stand_in.excepthook(RuntimeError, RuntimeError('again'), None)
        report = probe.build_report(0)
        self.assertEqual(report['callback_exceptions']['count'], probe.MAX_RECORDED_CALLBACK_FAILURES + 5)
        self.assertEqual(len(report['callback_exceptions']['recorded']), probe.MAX_RECORDED_CALLBACK_FAILURES)


def qt_available():
    try:
        return all(importlib.util.find_spec(name) for name in ('PySide6', 'qfluentwidgets', 'tendo', 'apscheduler', 'pynput'))
    except (ImportError, ValueError):
        return False


@unittest.skipUnless(qt_available(), 'NOT RUN: PySide6/qfluentwidgets/tendo/apscheduler/pynput not importable in this interpreter')
class RealStartupSmoke(unittest.TestCase):
    """Starts the real normal startup branch offscreen and quits via the event loop."""

    def run_entry(self, args, profile, extra_env=None):
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'QT_QPA_PLATFORM', 'MINIDRACONIA_MUTE')}
        env['MINIDRACONIA_TEST_PROFILE'] = str(profile)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env['PYTHONPATH'] = str(ENGINE)
        env.update(extra_env or {})
        entry = ENGINE / 'packaging' / 'portable_entry.py'
        return subprocess.run([sys.executable, '-B', str(entry)] + args, env=env, cwd=str(ENGINE),
                              capture_output=True, text=True, timeout=180)

    def test_normal_startup_reports_real_window_and_exits_cleanly(self):
        with tempfile.TemporaryDirectory(prefix='md smoke ') as base:
            base = Path(base).resolve()
            report = base / 'out' / 'smoke.json'
            report.parent.mkdir()
            result = self.run_entry(['--startup-smoke', '--report', str(report)], base / 'profile')
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            data = json.loads(report.read_text(encoding='utf-8'))
            self.assertTrue(data['ok'], data)
            self.assertEqual(data['exit_code'], 0)
            self.assertEqual(data['evidence']['application']['class'], 'DyberPetApp')
            self.assertGreater(data['evidence']['sprite_pixels'], 0)
            self.assertGreaterEqual(data['evidence']['timers']['event_loop_ticks'], 3)
            self.assertTrue((base / 'profile').is_dir())
            self.assertFalse(list(ENGINE.rglob('startup-diagnostic.txt')))

    NEGATIVE_CONTROL = (
        "import importlib.util, os, sys\n"
        "engine, report = sys.argv[1], sys.argv[2]\n"
        "sys.path.insert(0, engine)\n"
        "original_hook = sys.excepthook\n"
        "def previous(t, e, tb):\n"
        "    sys.stderr.write('PREVIOUS-HOOK-SAW ' + t.__name__ + '\\n')\n"
        "    original_hook(t, e, tb)\n"
        "sys.excepthook = previous\n"
        "from DyberPet.startup_smoke import SmokeProbe\n"
        "from PySide6.QtCore import QTimer\n"
        "real_attach = SmokeProbe.attach\n"
        "def boom():\n"
        "    raise RuntimeError('deliberate callback failure (test fixture)')\n"
        "def attach(self, app):\n"
        "    real_attach(self, app)\n"
        "    QTimer.singleShot(60, boom)\n"
        "SmokeProbe.attach = attach\n"
        "spec = importlib.util.spec_from_file_location('portable_entry_nc', os.path.join(engine, 'packaging', 'portable_entry.py'))\n"
        "entry = importlib.util.module_from_spec(spec); spec.loader.exec_module(entry)\n"
        "code = entry.main(['--startup-smoke', '--report', report])\n"
        "print('RESTORED=' + str(sys.excepthook is previous))\n"
        "sys.exit(code)\n")

    def test_callback_exception_in_a_real_qt_timer_fails_the_smoke(self):
        """Negative control: a deliberately raising QTimer callback (fixture lives only in this test)."""
        with tempfile.TemporaryDirectory(prefix='md nc ') as base:
            base = Path(base).resolve()
            scripts = base / 'scripts'
            scripts.mkdir()
            script = scripts / 'negative_control.py'
            script.write_text(self.NEGATIVE_CONTROL, encoding='utf-8')
            out = base / 'out'
            out.mkdir()
            report = out / 'smoke.json'
            env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'QT_QPA_PLATFORM', 'MINIDRACONIA_MUTE')}
            env.update(MINIDRACONIA_TEST_PROFILE=str(base / 'profile'), PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, '-B', str(script), str(ENGINE), str(report)], env=env,
                                    cwd=str(base), capture_output=True, text=True, timeout=180)
            self.assertNotEqual(result.returncode, 0, result.stdout[-1500:] + result.stderr[-1500:])
            data = json.loads(report.read_text(encoding='utf-8'))
            self.assertFalse(data['ok'], data)
            self.assertGreaterEqual(data['callback_exceptions']['count'], 1)
            self.assertIn('deliberate callback failure', json.dumps(data['callback_exceptions']))
            self.assertIn('deliberate callback failure', result.stderr, 'the traceback must still reach stderr')
            self.assertIn('PREVIOUS-HOOK-SAW', result.stderr)
            self.assertIn('RESTORED=True', result.stdout)

    def test_invalid_report_never_starts_qt(self):
        with tempfile.TemporaryDirectory() as base:
            result = self.run_entry(['--startup-smoke', '--report', 'relative.json'], Path(base).resolve() / 'profile')
            self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main()
