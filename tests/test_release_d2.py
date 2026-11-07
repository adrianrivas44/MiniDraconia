"""D2 release gates: no relay seed or key file ships, no other product's input reaches the build,
and the soul is bundled for the own-key mode."""
import importlib.util
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'full-engine'
POLICY_FILE = ENGINE / 'packaging' / 'asset_policy.py'
SPEC = ENGINE / 'packaging' / 'MiniDraconia.spec'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PolicyRefusesSeedsKeysAndOtherProducts(unittest.TestCase):
    def setUp(self):
        self.policy = load('asset_policy_d2', POLICY_FILE)
        # The real names live in the git-ignored markers file; tests use an invented one.
        self.other = 'zzotherpet'
        self.policy.OTHER_PRODUCT_NAMES = (self.other,)

    def test_a_relay_seed_or_key_file_is_a_violation_in_every_layout(self):
        for prefix in ('', 'full-engine/', 'full-engine/data/', 'MiniDraconia/', 'MiniDraconia/_internal/data/'):
            self.assertEqual(self.policy.violation(prefix + 'minidraconia_relay.json'), 'relay-seed', prefix)
            self.assertEqual(self.policy.violation(prefix + 'MiniDraconia_Relay.JSON'), 'relay-seed', prefix)
            self.assertEqual(self.policy.violation(prefix + 'own_key.dpapi'), 'own-key-file', prefix)

    def test_any_path_naming_the_other_product_is_a_violation(self):
        for name in ('res/role/%s/a.png' % self.other.title(), 'DyberPet/%s_pet.py' % self.other,
                     'packaging/e%s.spec' % self.other.title(), 'data/%s_lines_en.json' % self.other):
            self.assertEqual(self.policy.violation(name), 'other-product-input', name)

    def test_her_own_files_are_fine(self):
        for name in ('data/draconia_lines_en.json', 'data/draconia_desktop_prompt_en.txt',
                     'docs/identity/SOUL.en.md', 'DyberPet/brain_client.py', 'res/role/Draconia/action/tea_0.png'):
            self.assertIsNone(self.policy.violation(name), name)


class BuilderPreflight(unittest.TestCase):
    def setUp(self):
        self.pkg = load('package_scripted_d2', REPO / 'package_scripted.py')
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        (self.base / 'full-engine' / 'DyberPet').mkdir(parents=True)
        (self.base / 'full-engine' / 'DyberPet' / 'ok.py').write_text('x = 1\n', encoding='utf-8')
        # The real names live in the git-ignored markers file; tests use an invented one.
        self.other = 'zzotherpet'
        self.real_asset_policy = self.pkg.asset_policy
        policy = self.pkg.asset_policy()
        policy.OTHER_PRODUCT_NAMES = (self.other,)
        self.pkg.asset_policy = lambda: policy

    def test_clean_inputs_pass(self):
        self.assertEqual(self.pkg.other_product_inputs(self.base), [])

    def test_a_leftover_path_or_text_of_the_other_product_fails(self):
        (self.base / 'full-engine' / 'DyberPet' / ('%s_talk.py' % self.other)).write_text('x = 1\n', encoding='utf-8')
        (self.base / 'full-engine' / 'DyberPet' / 'notes.md').write_text('Old %s text\n' % self.other.upper(), encoding='utf-8')
        hits = self.pkg.other_product_inputs(self.base)
        self.assertEqual(sorted(hits), sorted(['full-engine/DyberPet/%s_talk.py' % self.other, 'full-engine/DyberPet/notes.md']))

    def test_the_real_tree_has_no_other_product_input_and_no_seed(self):
        # The real tree is checked against the real (private, git-ignored) markers, if present.
        self.pkg.asset_policy = self.real_asset_policy
        self.assertEqual(self.pkg.other_product_inputs(REPO), [])
        policy = self.pkg.asset_policy()
        self.assertEqual([n for n in self.pkg.source_inputs(REPO)
                          if policy.violation(n) in ('relay-seed', 'own-key-file')], [])

    def test_a_seed_in_the_built_folder_is_a_forbidden_artifact(self):
        self.assertTrue(self.pkg.forbidden_artifact('MiniDraconia/minidraconia_relay.json'))
        self.assertTrue(self.pkg.forbidden_artifact('MiniDraconia/_internal/data/minidraconia_relay.json'))
        self.assertTrue(self.pkg.forbidden_artifact('MiniDraconia/own_key.dpapi'))
        self.assertFalse(self.pkg.forbidden_artifact('MiniDraconia/_internal/data/draconia_lines_en.json'))

    def test_manifest_no_longer_claims_byo_is_not_implemented(self):
        source = (REPO / 'package_scripted.py').read_text(encoding='utf-8')
        self.assertNotIn("'byo_cloud': 'not implemented'", source)
        self.assertNotIn('SCRIPTED offline', source)

    def test_scanner_flags_the_other_product_in_text(self):
        scanner = load('scan_release_d2', REPO / 'scripts' / 'scan_release.py')
        scanner._asset_policy = self.pkg.asset_policy
        (self.base / 'README.md').write_text('hello %s\n' % self.other, encoding='utf-8')
        (self.base / 'minidraconia_relay.json').write_text('{}', encoding='utf-8')
        report = scanner.scan_tree(self.base)
        rules = {item['rule'] for item in report['findings']}
        self.assertIn('other-product-input', rules)
        self.assertIn('relay-seed', rules)


class SpecBundlesTheSoulAndRefusesSeeds(unittest.TestCase):
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

    def test_real_spec_bundles_soul_and_desktop_prompt(self):
        datas = [(Path(src), dest) for src, dest in self.evaluate(ENGINE)]
        self.assertIn((REPO / 'docs' / 'identity' / 'SOUL.en.md', 'docs/identity'), datas)
        self.assertIn((ENGINE / 'data', 'data'), datas)
        self.assertTrue((ENGINE / 'data' / 'draconia_desktop_prompt_en.txt').is_file())

    def test_a_seed_dropped_in_data_fails_the_spec(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, True)
        root = base / 'full-engine'
        (root / 'packaging').mkdir(parents=True)
        shutil.copyfile(POLICY_FILE, root / 'packaging' / 'asset_policy.py')
        (root / 'data').mkdir()
        (root / 'data' / 'minidraconia_relay.json').write_text('{}', encoding='utf-8')
        (root / 'res').mkdir()
        with self.assertRaisesRegex(Exception, 'asset policy.*relay-seed'):
            self.evaluate(root)


if __name__ == '__main__':
    unittest.main()
