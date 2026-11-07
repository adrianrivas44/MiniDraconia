"""Public-asset hygiene of the DERIVED candidate (standard library only).

Policy (see full-engine/packaging/asset_policy.py): unapproved voice clips and the inherited
third-party pet folder are physically absent from the source tree and rejected by the spec, the
builder and the release scanner if they are ever reintroduced. Nothing here asserts rights over
what remains; the approved clip and the Draconia art still have open provenance gates.
"""
import ast
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'full-engine'
NOTE = ENGINE / 'res' / 'role' / 'Draconia' / 'note'
POLICY_FILE = ENGINE / 'packaging' / 'asset_policy.py'
SPEC = ENGINE / 'packaging' / 'MiniDraconia.spec'
PAIMON = '派蒙'
PENDING = ['head-02', 'head-03', 'cheek-01', 'cheek-02', 'body-01', 'body-02', 'drag-01', 'drag-02', 'fall-01', 'fall-02']


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest():
    return json.loads((NOTE / 'manifest.json').read_text(encoding='utf-8'))


def entries():
    return [e for pool in manifest()['events'].values() for e in pool]


class PhysicalAbsence(unittest.TestCase):
    def test_pending_audio_is_not_in_the_source_tree(self):
        present = sorted(p.name for p in (NOTE / 'voice').glob('*.wav'))
        self.assertEqual(present, ['head-01.wav'], 'only the individually approved clip may be shipped')

    def test_the_inherited_pet_folder_has_no_files(self):
        pet = ENGINE / 'res' / 'pet'
        files = [p for p in pet.rglob('*') if p.is_file()] if pet.exists() else []
        self.assertEqual(files, [])
        self.assertFalse((pet / PAIMON).exists())

    def test_no_file_anywhere_in_the_tree_violates_the_policy(self):
        policy = load_module('asset_policy_check', POLICY_FILE)
        bad = [p.relative_to(REPO).as_posix() for p in REPO.rglob('*')
               if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts
               and 'third_party' not in p.parts and policy.violation(p.relative_to(REPO).as_posix())]
        self.assertEqual(bad, [])

    def test_original_copyright_notices_and_licenses_are_untouched(self):
        self.assertTrue((REPO / 'LICENSE').is_file())
        self.assertTrue((ENGINE / 'LICENSE').is_file())


class ManifestStaysHonest(unittest.TestCase):
    def test_approval_flags_are_not_changed(self):
        flags = {e['id']: e['approved'] for e in entries()}
        self.assertEqual([k for k, v in flags.items() if v], ['head-01'])
        self.assertEqual(sorted(k for k, v in flags.items() if not v), sorted(PENDING))
        for entry in entries():
            self.assertEqual(entry['listening'], 'approved' if entry['approved'] else 'pending', entry['id'])

    def test_approved_clip_is_present_and_hashed(self):
        approved = [e for e in entries() if e['approved']]
        self.assertEqual(len(approved), 1)
        data = (NOTE / approved[0]['audio']).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), approved[0]['sha256'])

    def test_pending_entries_do_not_point_to_audio_that_is_not_shipped(self):
        for entry in entries():
            if entry['approved']:
                continue
            self.assertIsNone(entry.get('audio'), entry['id'])
            self.assertNotIn('sha256', entry, entry['id'])
            self.assertTrue(entry['text'], 'pending text entries stay')
            self.assertIn('not distributed', entry.get('distribution', ''), entry['id'])

    def test_status_text_does_not_imply_shipped_audio(self):
        status = manifest()['status'].lower()
        self.assertIn('withheld', status)
        readme = (NOTE / 'voice' / 'README.md').read_text(encoding='utf-8').lower()
        self.assertIn('not distributed', readme)

    def test_every_audio_path_in_the_manifest_exists(self):
        for entry in entries():
            if entry.get('audio'):
                self.assertTrue((NOTE / entry['audio']).is_file(), entry['id'])

    def test_reactions_still_show_text_without_audio(self):
        reactions = load_module('draconia_reactions_under_test', ENGINE / 'DyberPet' / 'draconia_reactions.py')
        bubbles, played = [], []
        controller = reactions.Reactions(NOTE, bubble=bubbles.append, play=lambda p, v: played.append(p))
        for event in ('cheek', 'body', 'drag', 'fall'):
            controller.last_time = float('-inf')
            controller.react(event, available=('pinch', 'angry', 'touch_body', 'spell'), now=1000.0 + len(bubbles) * 10)
        self.assertEqual(len(bubbles), 4)
        self.assertEqual(played, [], 'no audio exists for pending clips, none may be played')


class PolicyModule(unittest.TestCase):
    def setUp(self):
        self.policy = load_module('asset_policy_under_test', POLICY_FILE)

    def test_pending_audio_and_pet_files_are_violations_in_every_layout(self):
        for prefix in ('', 'full-engine/', 'MiniDraconia/_internal/'):
            for clip in PENDING:
                self.assertEqual(self.policy.violation('%sres/role/Draconia/note/voice/%s.wav' % (prefix, clip)), 'unapproved-audio')
            self.assertEqual(self.policy.violation('%sres/pet/%s/act_conf.json' % (prefix, PAIMON)), 'inherited-pet-asset')
            self.assertEqual(self.policy.violation('%sres/pet/other/a.png' % prefix), 'inherited-pet-asset')
            self.assertIsNone(self.policy.violation('%sres/role/Draconia/note/voice/head-01.wav' % prefix))
            self.assertIsNone(self.policy.violation('%sres/sounds/Notification.wav' % prefix))

    def test_other_audio_formats_and_case_are_not_a_bypass(self):
        for name in ('head-02.mp3', 'x.OGG', 'y.Wav', 'z.flac'):
            self.assertEqual(self.policy.violation('res/role/Draconia/note/voice/' + name), 'unapproved-audio', name)
        self.assertEqual(self.policy.violation('res/role/Other/voice/a.wav'), 'unapproved-audio')
        self.assertEqual(self.policy.violation('some\\res\\pet\\x\\a.png'), 'inherited-pet-asset')

    def test_allow_list_is_exactly_the_one_approved_clip(self):
        self.assertEqual(set(self.policy.APPROVED_AUDIO), {'res/role/Draconia/note/voice/head-01.wav'})
        self.assertEqual({'res/role/Draconia/note/' + e['audio'] for e in entries() if e['approved']}, set(self.policy.APPROVED_AUDIO))


class SpecRejectsReintroduction(unittest.TestCase):
    def evaluate(self, root):
        captured = {}

        class Recorder:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs
                self.pure, self.scripts, self.binaries, self.datas = [], [], [], []
                captured.setdefault(type(self).__name__, []).append(self)
        hooks = types.ModuleType('PyInstaller.utils.hooks')
        hooks.collect_submodules = lambda name: [name]
        hooks.collect_all = lambda name: ([], [], [name])
        modules = {'PyInstaller': types.ModuleType('PyInstaller'), 'PyInstaller.utils': types.ModuleType('PyInstaller.utils'),
                   'PyInstaller.utils.hooks': hooks}
        scope = {'SPECPATH': str(root / 'packaging'), '__file__': str(root / 'packaging' / 'MiniDraconia.spec')}
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
        return captured['Analysis'][0].kwargs['datas']

    def mini_engine(self, extra=()):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, True)
        root = base / 'full-engine'
        (root / 'packaging').mkdir(parents=True)
        shutil.copyfile(POLICY_FILE, root / 'packaging' / 'asset_policy.py')
        # D2.1: the spec also loads its version-info helper and needs the app icon.
        shutil.copyfile(POLICY_FILE.with_name('version_info.py'), root / 'packaging' / 'version_info.py')
        (root / 'DyberPet' / 'brain').mkdir(parents=True)
        (base / 'VERSION').write_text('0.0.0\n', encoding='utf-8')
        (root / 'LICENSE').write_text('x', encoding='utf-8')
        for relative in ('res/role/Draconia/note/voice/head-01.wav', 'res/role/Draconia/a.png',
                         'res/icons/app.ico') + tuple(extra):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'x')
        return root

    def test_clean_tree_is_collected_and_an_absent_pet_folder_is_fine(self):
        datas = self.evaluate(self.mini_engine())
        names = [Path(src).name for src, _ in datas]
        self.assertIn('head-01.wav', names)
        self.assertIn('a.png', names)

    def test_reintroduced_pending_audio_fails_the_spec(self):
        root = self.mini_engine(['res/role/Draconia/note/voice/head-02.wav'])
        with self.assertRaisesRegex(Exception, 'asset policy.*unapproved-audio'):
            self.evaluate(root)

    def test_reintroduced_pet_folder_fails_the_spec(self):
        root = self.mini_engine(['res/pet/%s/act_conf.json' % PAIMON])
        with self.assertRaisesRegex(Exception, 'asset policy.*inherited-pet-asset'):
            self.evaluate(root)

    def test_real_tree_spec_collects_no_violation(self):
        policy = load_module('asset_policy_spec_real', POLICY_FILE)
        datas = self.evaluate(ENGINE)
        for src, dest in datas:
            relative = (Path(dest) / Path(src).name).as_posix()
            self.assertIsNone(policy.violation(relative), relative)
            self.assertIsNone(policy.violation(Path(src).as_posix().split('full-engine/')[-1]))

    def test_obsolete_qwen_license_data_is_no_longer_bundled(self):
        datas = self.evaluate(ENGINE)
        for src, dest in datas:
            self.assertNotIn('licenses', Path(dest).parts[:1], (src, dest))
            self.assertNotIn('qwen', Path(src).as_posix().lower(), (src, dest))


class BuilderRejects(unittest.TestCase):
    def test_forbidden_artifact_rejects_policy_violations(self):
        pkg = load_module('package_scripted_assets', REPO / 'package_scripted.py')
        for name in ('MiniDraconia/_internal/res/role/Draconia/note/voice/cheek-01.wav',
                     '_internal/res/pet/%s/pm_0.png' % PAIMON):
            self.assertTrue(pkg.forbidden_artifact(name), name)
        self.assertFalse(pkg.forbidden_artifact('_internal/res/role/Draconia/note/voice/head-01.wav'))

    def test_hash_tree_refuses_a_tree_with_pending_audio(self):
        pkg = load_module('package_scripted_assets2', REPO / 'package_scripted.py')
        with tempfile.TemporaryDirectory() as base:
            clip = Path(base) / '_internal' / 'res' / 'role' / 'Draconia' / 'note' / 'voice' / 'fall-02.wav'
            clip.parent.mkdir(parents=True)
            clip.write_bytes(b'x')
            with self.assertRaisesRegex(RuntimeError, 'Forbidden'):
                pkg.hash_tree(base, qt_inventory={})


class ScannerRejects(unittest.TestCase):
    def setUp(self):
        self.scan = load_module('scan_release_assets', REPO / 'scripts' / 'scan_release.py')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x')

    def rules(self, report):
        return {(f['rule'], f['path']) for f in report['findings']}

    def test_tree_scan_flags_pending_audio_and_pet_files(self):
        self.put('full-engine/res/role/Draconia/note/voice/head-01.wav')
        self.put('full-engine/res/role/Draconia/note/voice/body-02.wav')
        self.put('full-engine/res/pet/%s/pet_conf.json' % PAIMON)
        found = self.rules(self.scan.scan_tree(self.root))
        self.assertIn(('unapproved-audio', 'full-engine/res/role/Draconia/note/voice/body-02.wav'), found)
        self.assertIn(('inherited-pet-asset', 'full-engine/res/pet/%s/pet_conf.json' % PAIMON), found)
        self.assertNotIn('head-01', json.dumps(sorted(found)))

    def test_archive_scan_flags_the_same_members(self):
        archive = self.root / 'a.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('MiniDraconia/_internal/res/role/Draconia/note/voice/head-01.wav', b'x')
            z.writestr('MiniDraconia/_internal/res/role/Draconia/note/voice/head-03.wav', b'x')
            z.writestr('MiniDraconia/_internal/res/pet/%s/pet_conf.json' % PAIMON, b'x')
        found = self.rules(self.scan.scan_archive(archive))
        self.assertIn(('unapproved-audio', 'MiniDraconia/_internal/res/role/Draconia/note/voice/head-03.wav'), found)
        self.assertIn(('inherited-pet-asset', 'MiniDraconia/_internal/res/pet/%s/pet_conf.json' % PAIMON), found)
        self.assertEqual(len(found), 2)

    def test_the_real_tree_has_no_asset_policy_finding(self):
        report = self.scan.scan_tree(REPO)
        bad = [f for f in report['findings'] if f['rule'] in ('unapproved-audio', 'inherited-pet-asset')]
        self.assertEqual(bad, [])


def _function_source(path, name):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(Path(path).read_text(encoding='utf-8'), node)
    raise AssertionError('%s not found in %s' % (name, path))


class AbsentPetFolderEnumeratesSafely(unittest.TestCase):
    """utils.py / PetCardUI.py need Qt to import, so the pure helper is exercised from source."""

    def helper(self, path):
        scope = {'os': __import__('os')}
        exec(_function_source(path, 'get_child_folder'), scope)
        return scope['get_child_folder']

    def test_missing_folder_is_empty_only_when_the_caller_opts_in(self):
        for path in (ENGINE / 'DyberPet' / 'utils.py', ENGINE / 'DyberPet' / 'DyberSettings' / 'PetCardUI.py'):
            func = self.helper(path)
            with tempfile.TemporaryDirectory() as base:
                missing = str(Path(base) / 'absent')
                self.assertEqual(func(missing, relative=False, missing_ok=True), [], path.name)
                with self.assertRaises(FileNotFoundError):
                    func(missing, relative=False)
                (Path(base) / 'dir1').mkdir()
                (Path(base) / 'f.txt').write_text('x')
                self.assertEqual(func(base, relative=True, missing_ok=True), ['dir1'])

    def test_res_pet_callers_opt_in(self):
        for path in (ENGINE / 'DyberPet' / 'conf.py', ENGINE / 'DyberPet' / 'DyberSettings' / 'PetCardUI.py'):
            source = path.read_text(encoding='utf-8')
            calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)
                     and getattr(n.func, 'id', '') == 'get_child_folder' and 'res/pet' in ast.get_source_segment(source, n)]
            self.assertTrue(calls, path.name)
            for call in calls:
                self.assertTrue(any(k.arg == 'missing_ok' and getattr(k.value, 'value', None) is True for k in call.keywords), path.name)

    def test_other_callers_keep_strict_errors(self):
        source = (ENGINE / 'DyberPet' / 'conf.py').read_text(encoding='utf-8')
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'get_child_folder' \
                    and 'res/items' in ast.get_source_segment(source, node):
                self.assertFalse(node.keywords and any(k.arg == 'missing_ok' for k in node.keywords))


class BrainConfigIsNotAdvertisedAsWorking(unittest.TestCase):
    """config/brain.json was an old builtin_local config that the current Brain never reads."""

    def load(self):
        return json.loads((ENGINE / 'config' / 'brain.json').read_text(encoding='utf-8'))

    def effective_defaults(self):
        # Read the module's literal DEFAULT_CONFIG (what load_config() returns for a new profile)
        # without importing the package on every host.
        source = (ENGINE / 'DyberPet' / 'brain' / '__init__.py').read_text(encoding='utf-8')
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'DEFAULT_CONFIG' for t in node.targets):
                return ast.literal_eval(node.value)
        raise AssertionError('DEFAULT_CONFIG not found')

    def test_file_matches_the_effective_offline_defaults(self):
        data = self.load()
        status = data.pop('_status')
        self.assertIn('NOT READ', status)
        self.assertEqual(data, self.effective_defaults())

    def test_no_retired_provider_runtime_or_model_names_remain(self):
        text = (ENGINE / 'config' / 'brain.json').read_text(encoding='utf-8').lower()
        for word in ('builtin_local', 'qwen', 'gguf', 'llama', 'api_key', 'openai', 'runtime/', 'models/', 'model_path'):
            self.assertNotIn(word, text, word)

    def test_nothing_in_the_engine_reads_the_file(self):
        for path in ENGINE.rglob('*.py'):
            if '__pycache__' in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertNotEqual(node.value, 'brain.json', path)
                    self.assertNotIn('config/brain.json', node.value, path)


if __name__ == '__main__':
    unittest.main()
