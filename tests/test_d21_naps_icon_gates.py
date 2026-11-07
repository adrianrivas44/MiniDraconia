"""D2.1 behaviour contracts: no early naps, the director log, the app icon and version info, and
the release gates for a voice pack.

Owner: "se quedó dormida a los segundos" (she fell asleep within seconds) and "igual un símbolo de
su .exe" (and an icon for her .exe). Standard library unittest + PySide6, no network. The director
runs on an injected clock and seeded random numbers; the PyInstaller spec is evaluated with
recording stand-ins. No test reads source text.
"""
import hashlib
import importlib.util
import json
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'full-engine'
BRAIN = ENGINE / 'data' / 'draconia_brain.json'
SPEC = ENGINE / 'packaging' / 'MiniDraconia.spec'
POOL = {'tea': 3.0, 'read': 2.0, 'spell': 2.5, 'think': 2.0}
POSES = set(POOL) | {'left_walk', 'right_walk', 'follow_cursor', 'wake', 'doze', 'sleep'}
LOG_LINE = re.compile(r'^(act [a-z_]+|walk (left|right)|follow|nap \d+|away sleep|wake)( \(\+\d+ dropped\))?$')


def qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Clock:
    def __init__(self, t=10_000.0):
        self.t = t

    def __call__(self):
        return self.t


def her_config():
    from DyberPet.mia_director import load_director_config
    data = json.loads(BRAIN.read_text(encoding='utf-8'))
    return load_director_config(BRAIN)['weights'], tuple(data['director_tick_s'])


def make_director(clock, weights=None, seed=1, tick=(5.0, 8.0), log=None, system_idle=lambda: 1.0, **kwargs):
    """Her director with the role's idle pool. `system_idle` 1 s: someone is using the PC, so the
    away sleep stays out of the way unless a test asks for it."""
    qt_app()
    from DyberPet.mia_director import MiaDirector
    played = []
    director = MiaDirector(get_available_poses=lambda: set(POSES), play_action=played.append,
                           is_busy=lambda: False, weights=weights or her_config()[0], rng=random.Random(seed),
                           system_idle_fn=system_idle, now_fn=clock, tick_range_s=tick, idle_pool=dict(POOL),
                           on_log=log, **kwargs)
    director.played = played
    return director


def run_ticks(director, clock, seconds, tick, rng):
    """Advance the clock tick by tick for `seconds`; returns (nap start times, awake seconds)."""
    naps, awake, end = [], 0.0, clock.t + seconds
    while clock.t < end:
        step = rng.uniform(*tick)
        if not director.state.sleeping:
            awake += step
        clock.t += step
        was_napping = director.state.sleeping
        director._tick_once()
        if director.state.sleeping and not was_napping and director.state.sleep_kind == 'nap':
            naps.append(clock.t)
    return naps, awake


# --------------------------------------------------------------------------------------------
# Item 3: no early naps
# --------------------------------------------------------------------------------------------

class NoEarlyNaps(unittest.TestCase):
    SLEEPY = {'idle': 0.1, 'walk': 0.0, 'follow_cursor': 0.0, 'sleep': 5.0}   # naps whenever allowed

    def test_her_sleep_weight_is_0_015(self):
        weights, tick = her_config()
        self.assertEqual(weights['sleep'], 0.015)
        self.assertEqual(tick, (5.0, 8.0))

    def test_no_random_nap_in_the_first_10_minutes(self):
        for seed in range(40):
            clock = Clock()
            director = make_director(clock, self.SLEEPY, seed=seed)
            naps, _ = run_ticks(director, clock, 599.0, (5.0, 8.0), random.Random(seed))
            self.assertEqual(naps, [], seed)
        # Positive control: right after the warm-up, the same director naps.
        clock = Clock()
        director = make_director(clock, self.SLEEPY, seed=3)
        naps, _ = run_ticks(director, clock, 3600.0, (5.0, 8.0), random.Random(3))
        self.assertTrue(naps and naps[0] >= 10_000.0 + 600.0, naps[:1])

    def test_no_random_nap_within_3_minutes_of_an_interaction_a_typed_message_or_a_line(self):
        for note in ('note_interaction', 'note_activity'):
            first = []
            for seed in range(40):
                clock = Clock()
                director = make_director(clock, self.SLEEPY, seed=seed)
                clock.t += 900.0                       # past the warm-up
                getattr(director, note)()
                quiet_from = clock.t
                naps, _ = run_ticks(director, clock, 1200.0, (5.0, 8.0), random.Random(seed))
                with self.subTest(note=note, seed=seed):
                    self.assertTrue(all(t - quiet_from >= 180.0 for t in naps), naps[:1])
                first += naps[:1]
            self.assertTrue(first, 'after the quiet period she does nap')

    def test_naps_average_at_least_10_minutes_apart_for_any_tick(self):
        weights, tick = her_config()
        cases = (('her config', weights, tick),
                 ('an older profile with sleep 0.05', dict(weights, sleep=0.05), tick),
                 ('a 1-2 s tick and a heavy weight', dict(weights, sleep=0.5), (1.0, 2.0)))
        for name, case_weights, case_tick in cases:
            clock = Clock()
            director = make_director(clock, case_weights, seed=7, tick=case_tick)
            clock.t += 900.0
            naps, awake = run_ticks(director, clock, 300 * 700.0, case_tick, random.Random(7))
            mean = awake / len(naps)
            with self.subTest(case=name):
                self.assertGreater(len(naps), 150)
                self.assertGreater(mean, 0.85 * 600.0, 'about one nap per 10 minutes at most')
                self.assertLess(mean, 1.2 * 600.0, 'the cap is the binding limit here')

    def test_the_documented_expected_interval(self):
        from DyberPet.mia_director import cap_nap_weight, expected_nap_interval_s, mood_weighted_choice
        weights, tick = her_config()
        self.assertAlmostEqual(expected_nap_interval_s(weights, tick), 600.0, places=3)
        # Without the cap her weight alone would mean a nap every ~6.6 minutes of 5-8 s ticks.
        total = sum(weights.values())
        self.assertAlmostEqual(6.5 / (weights['sleep'] / total), 396.5, places=0)
        # Mood can double the weight ("sleepy"), never the rate.
        table = json.loads(BRAIN.read_text(encoding='utf-8'))['mood']
        sleepy = mood_weighted_choice(weights, 'sleepy', table)
        self.assertAlmostEqual(expected_nap_interval_s(sleepy, tick), 600.0, places=3)
        # Slower 8-20 s ticks: her weight is already rarer than the cap.
        self.assertAlmostEqual(expected_nap_interval_s(weights, (8.0, 20.0)), 854.0, places=0)
        self.assertEqual(cap_nap_weight({'sleep': 1.0}, 6.5)['sleep'], 0.0, 'naps-only config: no random naps')

    def test_away_sleep_is_unchanged_even_during_the_warm_up(self):
        log = []
        idle = [400.0]
        clock = Clock()
        director = make_director(clock, self.SLEEPY, log=log.append, system_idle=lambda: idle[0],
                                 sleep_after_s=300.0)
        clock.t += 310.0
        director._tick_once()
        self.assertEqual((director.state.sleeping, director.state.sleep_kind), (True, 'away'))
        idle[0] = 5.0
        clock.t += 6.0
        director._tick_once()
        self.assertFalse(director.state.sleeping)
        self.assertEqual(log, ['away sleep', 'wake'])
        self.assertEqual(director.played, ['wake'])

    def test_a_nap_still_ends_by_itself(self):
        clock = Clock()
        director = make_director(clock, self.SLEEPY, seed=2)
        clock.t += 900.0
        naps, _ = run_ticks(director, clock, 2000.0, (5.0, 8.0), random.Random(2))
        self.assertTrue(naps)
        self.assertFalse(director.state.sleeping and clock.t - naps[-1] > 130.0)


# --------------------------------------------------------------------------------------------
# Item 4: the director log
# --------------------------------------------------------------------------------------------

class DirectorLog(unittest.TestCase):
    def test_one_line_per_decision_in_the_documented_words(self):
        log = []
        clock = Clock()
        weights = dict(her_config()[0], sleep=0.3)
        director = make_director(clock, weights, seed=5, log=log.append)
        clock.t += 900.0
        rng = random.Random(5)
        decisions = 0
        for _ in range(2000):
            clock.t += rng.uniform(5.0, 8.0)
            before = (len(director.played), director.state.sleeping)
            director._tick_once()
            decisions += (len(director.played), director.state.sleeping) != before
        self.assertEqual(len(log), decisions, 'one line per decision, none for a no-op tick')
        for line in log:
            self.assertRegex(line, LOG_LINE)
        kinds = {line.split()[0] for line in log}
        self.assertEqual(kinds, {'act', 'walk', 'follow', 'nap', 'wake'})
        nap_seconds = [int(line.split()[1]) for line in log if line.startswith('nap ')]
        self.assertTrue(all(45 <= s <= 120 for s in nap_seconds))

    def test_rate_safe_even_with_fast_ticks(self):
        from DyberPet.mia_director import RateLimitedLog
        sink, clock = [], Clock(0.0)
        limited = RateLimitedLog(sink.append, clock, max_lines=20, window_s=60.0)
        for _ in range(100):
            limited('act tea')
        self.assertEqual(len(sink), 20)
        clock.t += 60.0
        limited('wake')
        self.assertEqual(sink[-1], 'wake (+80 dropped)')
        # A director ticking every 0.1 s writes at most 20 lines a minute.
        log = []
        dclock = Clock()
        director = make_director(dclock, {'idle': 1.0, 'walk': 1.0, 'follow_cursor': 1.0, 'sleep': 0.0}, log=log.append)
        for _ in range(600):
            dclock.t += 0.1
            director._tick_once()
        self.assertEqual(len(log), 20)

    def test_talk_log_lines_are_timestamped_and_the_log_rolls_over(self):
        from DyberPet.mia_director import append_talk_log
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        path = folder / 'mia_talk.log'
        append_talk_log(path, 'director', 'nap 73')
        self.assertRegex(path.read_text(encoding='utf-8'), r'^\d\d:\d\d:\d\d director nap 73\n$')
        for _ in range(50):
            append_talk_log(path, 'director', 'act tea', max_bytes=200)
        self.assertLessEqual(path.stat().st_size, 200 + 40)
        self.assertTrue((folder / 'mia_talk.log.1').is_file())
        append_talk_log(folder / 'missing' / 'deep' / 'x.log', 'director', 'wake')   # never raises

    def test_the_pet_writes_director_lines_to_its_talk_log(self):
        code = r'''
import os, sys, types, json, tempfile
pyn, mouse = types.ModuleType('pynput'), types.ModuleType('pynput.mouse')
class _L:
    def __init__(self, *a, **k): pass
    def start(self): pass
    def stop(self): pass
mouse.Listener = mouse.Controller = _L
mouse.Button = types.SimpleNamespace(left=1, right=2, middle=3)
pyn.mouse = mouse
sys.modules['pynput'], sys.modules['pynput.mouse'] = pyn, mouse
from PySide6.QtWidgets import QApplication
app = QApplication([])
from DyberPet import settings
from DyberPet.DyberPet import PetWidget
base = tempfile.mkdtemp()
os.makedirs(os.path.join(base, 'data'))
settings.CONFIGDIR = base
class Pet:
    _mia_log = PetWidget._mia_log
Pet()._mia_log('director', 'walk left')
print(json.dumps({'log': open(os.path.join(base, 'data', 'mia_talk.log'), encoding='utf-8').read()}))
'''
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen',
                   PYTHONPATH=str(ENGINE) + os.pathsep + os.environ.get('PYTHONPATH', ''))
        proc = subprocess.run([sys.executable, '-c', code], env=env, cwd=str(ENGINE), capture_output=True,
                              text=True, encoding='utf-8', errors='replace', timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
        out = json.loads([l for l in proc.stdout.splitlines() if l.startswith('{')][-1])
        self.assertRegex(out['log'], r'^\d\d:\d\d:\d\d director walk left\n$')


# --------------------------------------------------------------------------------------------
# Item 5: app icon and Windows version info
# --------------------------------------------------------------------------------------------

def evaluate_spec(root, workpath):
    """Run the spec with recording stand-ins for PyInstaller; returns {class name: [kwargs]}."""
    captured = {}

    class Recorder:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs
            self.pure, self.scripts, self.binaries, self.datas = [], [], [], []
            captured.setdefault(type(self).__name__, []).append(kwargs)
    hooks = types.ModuleType('PyInstaller.utils.hooks')
    hooks.collect_submodules = lambda name: [name]
    hooks.collect_all = lambda name: ([], [], [name])
    modules = {'PyInstaller': types.ModuleType('PyInstaller'), 'PyInstaller.utils': types.ModuleType('PyInstaller.utils'),
               'PyInstaller.utils.hooks': hooks}
    scope = {'SPECPATH': str(root / 'packaging'), '__file__': str(root / 'packaging' / 'MiniDraconia.spec'),
             'workpath': str(workpath)}
    for name in ('Analysis', 'PYZ', 'EXE', 'COLLECT'):
        scope[name] = type(name, (Recorder,), {})
    saved = {k: sys.modules.get(k) for k in modules}
    sys.modules.update(modules)
    try:
        exec(compile(SPEC.read_text(encoding='utf-8'), str(SPEC), 'exec'), scope)
    finally:
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value
    return captured


def read_version_file(path):
    """Evaluate a PyInstaller version file with stand-ins: (filevers, prodvers, {string fields})."""
    found = {}

    def record(kind):
        def make(*args, **kwargs):
            found.setdefault(kind, []).append((args, kwargs))
            return (kind, args, kwargs)
        return make
    names = ('VSVersionInfo', 'FixedFileInfo', 'StringFileInfo', 'StringTable', 'StringStruct', 'VarFileInfo', 'VarStruct')
    eval(compile(Path(path).read_text(encoding='utf-8'), str(path), 'eval'), {n: record(n) for n in names})
    fixed = found['FixedFileInfo'][0][1]
    strings = dict(args for args, _ in found['StringStruct'])
    return fixed['filevers'], fixed['prodvers'], strings


def ico_sizes(path):
    data = Path(path).read_bytes()
    reserved, kind, count = struct.unpack('<HHH', data[:6])
    if reserved != 0 or kind != 1:
        return []
    return sorted((data[6 + 16 * i] or 256) for i in range(count))


def exe_gate_problems(exe_kwargs, version):
    """The package gate: the exe must carry the app icon and MiniDraconia's version info."""
    problems = []
    icon = exe_kwargs.get('icon')
    if not icon or not Path(icon).is_file() or not {16, 32, 48, 256} <= set(ico_sizes(icon)):
        problems.append('exe icon missing or not a multi-size .ico')
    info = exe_kwargs.get('version')
    if not info or not Path(info).is_file():
        problems.append('exe version info missing')
        return problems
    filevers, prodvers, strings = read_version_file(info)
    expected = {'ProductName': 'MiniDraconia', 'FileDescription': 'MiniDraconia desktop companion',
                'FileVersion': version, 'ProductVersion': version}
    if any(strings.get(k) != v for k, v in expected.items()):
        problems.append('exe version strings wrong: %r' % strings)
    return problems


class AppIconAndVersionInfo(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.work, True)
        self.version = (REPO / 'VERSION').read_text(encoding='utf-8').strip()

    def test_the_real_spec_gives_the_exe_the_icon_and_version_info(self):
        exe = evaluate_spec(ENGINE, self.work)['EXE'][0]
        self.assertEqual(exe_gate_problems(exe, self.version), [])
        self.assertEqual(Path(exe['icon']), ENGINE / 'res' / 'icons' / 'app.ico')
        self.assertTrue(Path(exe['version']).is_relative_to(self.work), 'written to the build folder, not the tree')
        filevers, prodvers, strings = read_version_file(exe['version'])
        self.assertEqual(filevers, (1, 0, 0, 2))
        self.assertEqual(prodvers, (1, 0, 0, 2))
        self.assertEqual(strings['OriginalFilename'], 'MiniDraconia.exe')

    def test_the_gate_fails_without_icon_or_version_info(self):
        exe = evaluate_spec(ENGINE, self.work)['EXE'][0]
        self.assertTrue(exe_gate_problems(dict(exe, icon=None), self.version))
        self.assertTrue(exe_gate_problems(dict(exe, version=None), self.version))
        bad = self.work / 'bad.ico'
        bad.write_bytes(b'\x89PNG not an ico')
        self.assertTrue(exe_gate_problems(dict(exe, icon=str(bad)), self.version))
        self.assertTrue(exe_gate_problems(exe, '9.9.9'), 'version strings must follow VERSION')

    def test_a_missing_icon_file_fails_the_spec(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, True)
        root = base / 'full-engine'
        (root / 'packaging').mkdir(parents=True)
        for name in ('asset_policy.py', 'version_info.py'):
            shutil.copyfile(ENGINE / 'packaging' / name, root / 'packaging' / name)
        (root / 'data').mkdir()
        (root / 'res').mkdir()
        (base / 'VERSION').write_text('1.0.0-rc.2\n', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'application icon is missing'):
            evaluate_spec(root, self.work)

    def test_version_numbers(self):
        version_info = load('version_info_d21', ENGINE / 'packaging' / 'version_info.py')
        self.assertEqual(version_info.numeric_version('1.0.0-rc.2'), (1, 0, 0, 2))
        self.assertEqual(version_info.numeric_version('1.2.3'), (1, 2, 3, 0))
        for bad in ('1.0', 'v1.0.0', '1.0.0-beta', '70000.0.0'):
            with self.assertRaises(ValueError):
                version_info.numeric_version(bad)

    def test_icon_files_are_a_1024_png_and_a_multi_size_ico(self):
        png = (ENGINE / 'res' / 'icons' / 'app.png').read_bytes()
        self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
        width, height, depth, colour = struct.unpack('>IIBB', png[16:26])
        self.assertEqual((width, height, depth, colour), (1024, 1024, 8, 6), '1024 px RGBA')
        self.assertEqual(ico_sizes(ENGINE / 'res' / 'icons' / 'app.ico'), [16, 24, 32, 48, 64, 128, 256])
        # The inherited icon stays: the notification system still uses it.
        self.assertTrue((ENGINE / 'res' / 'icons' / 'icon.png').is_file())
        notes = json.loads((ENGINE / 'res' / 'icons' / 'note_icon.json').read_text(encoding='utf-8'))
        self.assertIn('icon.png', json.dumps(notes))

    def test_the_spec_bundles_the_icon_files(self):
        datas = evaluate_spec(ENGINE, self.work)['Analysis'][0]['datas']
        # Destinations are host paths: 'res\\icons' on Windows, 'res/icons' elsewhere.
        bundled = {(Path(src), Path(dest)) for src, dest in datas}
        self.assertIn((ENGINE / 'res' / 'icons' / 'app.png', Path('res', 'icons')), bundled)
        self.assertIn((ENGINE / 'res' / 'icons' / 'app.ico', Path('res', 'icons')), bundled)

    def test_app_icon_has_every_size(self):
        qt_app()
        from DyberPet.app_icon import app_icon, app_icon_files
        self.assertEqual([Path(p).name for p in app_icon_files(str(ENGINE))], ['app.ico', 'app.png'])
        icon = app_icon(str(ENGINE))
        sizes = {s.width() for s in icon.availableSizes()}
        self.assertTrue({16, 32, 48, 256, 1024} <= sizes, sizes)
        self.assertTrue(app_icon(str(self.work)).isNull(), 'no files: an empty icon, never an error')

    def test_settings_window_and_tray_show_the_app_icon(self):
        code = r'''
import os, sys, types, json
pyn, mouse = types.ModuleType('pynput'), types.ModuleType('pynput.mouse')
class _L:
    def __init__(self, *a, **k): pass
    def start(self): pass
    def stop(self): pass
mouse.Listener = mouse.Controller = _L
mouse.Button = types.SimpleNamespace(left=1, right=2, middle=3)
pyn.mouse = mouse
sys.modules['pynput'], sys.modules['pynput.mouse'] = pyn, mouse
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication([])
from DyberPet import settings
from DyberPet.DyberPet import PetWidget
from DyberPet.app_icon import app_icon
from DyberPet.custom_roundmenu import RoundMenu
def same(a, b):
    return all(a.pixmap(s, s).toImage() == b.pixmap(s, s).toImage() for s in (16, 32, 256))
want = app_icon(settings.BASEDIR)
class Tray(QWidget):
    _set_tray = PetWidget._set_tray
    def __init__(self):
        super().__init__()
        self.audit_mode, self.tray, self.StatMenu = False, None, RoundMenu(parent=self)
tray = Tray(); tray._set_tray()
from DyberPet.DyberSettings.DyberControlPanel import ControlMainWindow
panel = ControlMainWindow()
print(json.dumps({'tray': same(tray.tray.icon(), want), 'settings': same(panel.windowIcon(), want),
                  'not_null': not want.isNull()}))
'''
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen',
                   PYTHONPATH=str(ENGINE) + os.pathsep + os.environ.get('PYTHONPATH', ''))
        proc = subprocess.run([sys.executable, '-c', code], env=env, cwd=str(ENGINE), capture_output=True,
                              text=True, encoding='utf-8', errors='replace', timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
        out = json.loads([l for l in proc.stdout.splitlines() if l.startswith('{')][-1])
        self.assertEqual(out, {'tray': True, 'settings': True, 'not_null': True})


# --------------------------------------------------------------------------------------------
# Item 2 gates: a voice pack never reaches the public build
# --------------------------------------------------------------------------------------------

class VoicePackNeverShips(unittest.TestCase):
    def setUp(self):
        self.policy = load('asset_policy_d21', ENGINE / 'packaging' / 'asset_policy.py')
        self.pkg = load('package_scripted_d21', REPO / 'package_scripted.py')
        self.scanner = load('scan_release_d21', REPO / 'scripts' / 'scan_release.py')
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)

    def test_the_policy_refuses_a_voice_pack_in_every_layout(self):
        for name in ('voice_pack/manifest.json', 'full-engine/voice_pack/greet_0.wav',
                     'MiniDraconia/voice_pack/manifest.json', 'MiniDraconia/_internal/voice_pack/a.wav',
                     'MiniDraconia/Voice_Pack/a.wav', 'full-engine/data/voice_pack/manifest.json'):
            self.assertEqual(self.policy.violation(name), 'voice-pack', name)
        self.assertIsNone(self.policy.violation('full-engine/DyberPet/voice_pack.py'), 'the loader module is code')

    def test_the_builder_refuses_one_in_its_inputs_and_its_output(self):
        pack = self.base / 'full-engine' / 'voice_pack'
        pack.mkdir(parents=True)
        (pack / 'manifest.json').write_text('{}', encoding='utf-8')
        found = [n for n in self.pkg.source_inputs(self.base) if self.policy.violation(n) in self.pkg.PRIVATE_INPUT_RULES]
        self.assertEqual(found, ['full-engine/voice_pack/manifest.json'])
        self.assertTrue(self.pkg.forbidden_artifact('MiniDraconia/voice_pack/manifest.json'))
        built = self.base / 'MiniDraconia'
        (built / 'voice_pack').mkdir(parents=True)
        (built / 'voice_pack' / 'a.wav').write_bytes(b'RIFF')
        with self.assertRaisesRegex(RuntimeError, 'voice_pack'):
            self.pkg.hash_tree(built)

    def test_the_scanner_flags_one_in_a_tree_and_in_a_zip(self):
        (self.base / 'voice_pack').mkdir()
        (self.base / 'voice_pack' / 'manifest.json').write_text('{}', encoding='utf-8')
        rules = {item['rule'] for item in self.scanner.scan_tree(self.base)['findings']}
        self.assertIn('voice-pack', rules)
        archive = self.base / 'MiniDraconia.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('MiniDraconia/MiniDraconia.exe', b'MZ')
            z.writestr('MiniDraconia/voice_pack/manifest.json', b'{}')
        rules = {item['rule'] for item in self.scanner.scan_archive(archive)['findings']}
        self.assertIn('voice-pack', rules)

    def test_a_voice_pack_dropped_in_data_fails_the_spec(self):
        root = self.base / 'full-engine'
        (root / 'packaging').mkdir(parents=True)
        for name in ('asset_policy.py', 'version_info.py'):
            shutil.copyfile(ENGINE / 'packaging' / name, root / 'packaging' / name)
        (root / 'data' / 'voice_pack').mkdir(parents=True)
        (root / 'data' / 'voice_pack' / 'manifest.json').write_text('{}', encoding='utf-8')
        (root / 'res').mkdir()
        with self.assertRaisesRegex(RuntimeError, 'asset policy.*voice-pack'):
            evaluate_spec(root, self.base / 'work')

    def test_git_ignores_a_voice_pack(self):
        inside = subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'], cwd=str(REPO),
                                capture_output=True, text=True)
        if inside.returncode != 0:
            self.skipTest('source export without a git work tree (the Windows build tree)')
        for name in ('full-engine/voice_pack/manifest.json', 'voice_pack/a.wav'):
            ignored = subprocess.run(['git', 'check-ignore', '-q', name], cwd=str(REPO))
            self.assertEqual(ignored.returncode, 0, name)


# --------------------------------------------------------------------------------------------
# Item 6: docs
# --------------------------------------------------------------------------------------------

class Docs(unittest.TestCase):
    def read(self, name):
        return (REPO / name).read_text(encoding='utf-8')

    def test_privacy_events_never_leave_the_device(self):
        privacy = self.read('docs/PRIVACY.md').lower()
        self.assertIn('pet events never leave your device, in every mode', privacy)
        self.assertIn('only a message you type', privacy)
        self.assertNotIn('short descriptions of desktop events', privacy)
        self.assertIn('voice pack', privacy)

    def test_readmes_say_what_spends_what(self):
        en, es = self.read('README.md'), self.read('README.es.md')
        self.assertIn('**What spends what.**', en)
        self.assertIn('**Qué gasta qué.**', es)
        self.assertNotIn('they patted your head', en)
        self.assertNotIn('te acarició la cabeza', es)

    def test_changelog_and_rights_review(self):
        changelog = self.read('CHANGELOG.md')
        for needle in ('never send a request', 'voice_pack/manifest.json', 'first 10 minutes', 'director act',
                       'App icon (provisional)'):
            self.assertIn(needle, changelog)
        rights = self.read('docs/RIGHTS-REVIEW.md')
        self.assertIn('stand_0', rights)
        self.assertIn('app.ico', rights)


if __name__ == '__main__':
    unittest.main()
