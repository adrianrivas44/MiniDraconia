"""D2.6: no earlier project's character name in the public tree, and a guard that keeps it out.

  1. A markers-file line `word:<name>` is a whole-token match: a token is bounded by any
     non-letter (`_`, digits and punctuation count as boundaries), so a longer word that only
     contains the name does not match. A plain line keeps the substring match. One parser and
     one matcher live in full-engine/packaging/asset_policy.py; the release scanner, the build
     preflight and the private-word scan of the public docs test all use them. Tests use an
     invented name, never a real one.
  2. The per-character profile resolver and satiety keep their behaviour for Draconia, Kitty and
     ChrisKitty without any check on a pet's name.
"""
import ast
import importlib.util
import shutil
import tempfile
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'full-engine'
POLICY_FILE = ENGINE / 'packaging' / 'asset_policy.py'

NAME = 'zzq'
TOKEN_HITS = ('zzq_chat.py', 'Zzq:', 'see ZZQ.', '2zzq3', 'x-zzq')
TOKEN_MISSES = ('azzqb', 'zzqa', 'azzq', 'familia', 'academia')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MarkerFile(unittest.TestCase):
    def setUp(self):
        self.policy = load('asset_policy_d26', POLICY_FILE)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def markers(self, text):
        path = self.tmp / 'markers.txt'
        path.write_text(text, encoding='utf-8')
        return path

    def test_word_lines_are_kept_as_whole_token_markers(self):
        path = self.markers('# own\n\nword:%s\nWORD: Qqz \nPlainOne\nword:%s\nword:\n' % (NAME.upper(), NAME))
        self.assertEqual(self.policy.load_other_product_names(path), ('word:zzq', 'word:qqz', 'plainone'))

    def test_a_word_marker_matches_only_the_whole_token(self):
        names = ('word:' + NAME,)
        for text in TOKEN_HITS:
            self.assertGreaterEqual(self.policy.find_name(text, names), 0, text)
        for text in TOKEN_MISSES:
            self.assertEqual(self.policy.find_name(text, names), -1, text)

    def test_a_plain_marker_keeps_the_substring_match(self):
        for text in TOKEN_HITS + ('azzqb', 'zzqa', 'azzq'):
            self.assertGreaterEqual(self.policy.find_name(text, (NAME,)), 0, text)
        self.assertEqual(self.policy.find_name('familia', (NAME,)), -1)

    def test_a_non_ascii_letter_is_not_a_boundary(self):
        names = ('word:zíq',)
        self.assertGreaterEqual(self.policy.find_name('ZÍQ: hi', names), 0)
        self.assertEqual(self.policy.find_name('ñzíq', names), -1)
        self.assertEqual(self.policy.find_name('zíqá', names), -1)

    def test_the_path_rule_uses_the_same_match(self):
        self.policy.OTHER_PRODUCT_NAMES = ('word:' + NAME,)
        self.assertEqual(self.policy.violation('full-engine/DyberPet/zzq_chat.py'), 'other-product-input')
        self.assertEqual(self.policy.violation('res/role/Zzq/a.png'), 'other-product-input')
        self.assertIsNone(self.policy.violation('full-engine/DyberPet/azzqb.py'))
        self.assertIsNone(self.policy.violation('docs/zzqa.md'))


class ScannerAndPreflight(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / 'tree'
        self.root.mkdir()
        self.markers = self.tmp / 'markers.txt'
        self.markers.write_text('word:%s\n' % NAME, encoding='utf-8')
        self.policy = load('asset_policy_d26_scan', POLICY_FILE)
        self.policy.OTHER_PRODUCT_NAMES = self.policy.load_other_product_names(self.markers)
        self.scan = load('scan_release_d26', REPO / 'scripts' / 'scan_release.py')
        self.scan._asset_policy = lambda: self.policy

    def put(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_the_scanner_flags_tokens_and_never_longer_words(self):
        self.put('a/zzq_chat.py', 'x = 1\n')
        self.put('b.md', 'one\nZzq: hello\n')
        self.put('c.md', 'azzqb and zzqa\n')
        report = self.scan.scan_tree(self.root, markers=self.scan.load_private_markers(self.markers))
        found = {(i['rule'], i['path'], i.get('line')) for i in report['findings']}
        self.assertEqual(found, {('other-product-input', 'a/zzq_chat.py', None),
                                 ('other-product-input', 'b.md', 2), ('private-marker', 'b.md', 2)})

    def test_the_scanner_keeps_plain_markers_as_substrings(self):
        self.markers.write_text('%s\n' % NAME, encoding='utf-8')
        self.put('c.md', 'x\nazzqb\n')
        report = self.scan.scan_tree(self.root, markers=self.scan.load_private_markers(self.markers))
        self.assertIn(('private-marker', 'c.md', 2), {(i['rule'], i['path'], i.get('line')) for i in report['findings']})

    def test_the_build_preflight_uses_the_same_match(self):
        pkg = load('package_scripted_d26', REPO / 'package_scripted.py')
        pkg.asset_policy = lambda: self.policy
        engine = self.tmp / 'full-engine' / 'DyberPet'
        engine.mkdir(parents=True)
        (engine / 'ok.py').write_text('academia = familia = "azzqb zzqa"\n', encoding='utf-8')
        self.assertEqual(pkg.other_product_inputs(self.tmp), [])
        (engine / 'zzq_chat.py').write_text('x = 1\n', encoding='utf-8')
        (engine / 'notes.md').write_text('said Zzq: hi\n', encoding='utf-8')
        self.assertEqual(sorted(pkg.other_product_inputs(self.tmp)),
                         ['full-engine/DyberPet/notes.md', 'full-engine/DyberPet/zzq_chat.py'])

    def test_the_public_docs_word_scan_uses_the_markers(self):
        import test_d24_public_docs as docs
        names = ('word:' + NAME,)
        self.assertEqual(docs.marker_hits('a/zzq_chat.py', 'x = 1\n', names), ['a/zzq_chat.py'])
        self.assertEqual(docs.marker_hits('b.md', 'one\nZzq: hi\n', names), ['b.md:2'])
        self.assertEqual(docs.marker_hits('c.md', 'azzqb zzqa\n', names), [])


class ProfilesWithoutANameCheck(unittest.TestCase):
    def setUp(self):
        from DyberPet import char_profile
        self.cp = char_profile
        self.data = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.data, True)
        (self.data / 'draconia_brain.json').write_text('{}', encoding='utf-8')
        (self.data / 'draconia_lines.json').write_text('{}', encoding='utf-8')

    def test_draconia_reads_her_own_files(self):
        self.assertTrue(self.cp.has_own_profile(self.data, 'Draconia'))
        self.assertEqual(self.cp.brain_path(self.data, 'Draconia'), self.data / 'draconia_brain.json')
        self.assertEqual(self.cp.lines_path(self.data, 'Draconia'), self.data / 'draconia_lines.json')
        # her own mood file even before it exists (created on save)
        self.assertEqual(self.cp.mood_path(self.data, 'Draconia'), self.data / 'draconia_mood.json')

    def test_kitty_and_chriskitty_share_the_generic_default(self):
        for pet in ('Kitty', 'ChrisKitty'):
            self.assertFalse(self.cp.has_own_profile(self.data, pet))
            for kind in self.cp.KINDS:
                self.assertEqual(self.cp.profile_path(self.data, pet, kind), self.cp.generic_path(self.data, kind))

    def test_a_pet_whose_own_file_is_the_generic_one_has_no_own_profile(self):
        generic = self.cp.generic_path(self.data, 'brain')
        generic.write_text('{}', encoding='utf-8')
        pet = self.cp.GENERIC_PROFILE_NAME.title()
        self.assertEqual(self.cp.brain_path(self.data, pet), generic)
        self.assertFalse(self.cp.has_own_profile(self.data, pet))
        self.assertEqual(self.cp.mood_path(self.data, pet), self.cp.generic_path(self.data, 'mood'))
        self.assertTrue(self.cp.has_own_profile(self.data, 'Draconia'))

    def test_no_pet_name_other_than_draconia_is_special_cased(self):
        for path in (ENGINE / 'DyberPet' / 'DyberPet.py', ENGINE / 'DyberPet' / 'char_profile.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
                    parts = [node.left] + list(node.comparators)
                    if any('petname' in ast.unparse(p) for p in parts):
                        consts = [p.value for p in parts if isinstance(p, ast.Constant)]
                        self.assertTrue(all(c == 'Draconia' for c in consts), (path.name, ast.unparse(node)))


class SatietyStaysInert(unittest.TestCase):
    """DP_HpBar.updateValue never lowers satiety for any pet, with or without HP_stop."""

    def method(self, settings):
        source = (ENGINE / 'DyberPet' / 'DyberPet.py').read_text(encoding='utf-8')
        cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'DP_HpBar')
        func = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'updateValue')
        namespace = {'settings': settings, 'math': __import__('math')}
        exec(compile(ast.Module(body=[func], type_ignores=[]), 'updateValue', 'exec'), namespace)
        return namespace['updateValue']

    def test_the_scheduler_never_lowers_satiety_for_any_pet(self):
        for pet in ('Draconia', 'Kitty', 'ChrisKitty'):
            for hp_stop in (False, True):
                settings = types.SimpleNamespace(petname=pet, HP_stop=hp_stop, pet_data=None)
                bar = types.SimpleNamespace(hp_inner=500, hp_max=500, interval=5, hp_perct=100)
                self.assertEqual(self.method(settings)(bar, -5, 'Scheduler'), 0, pet)
                self.assertEqual(bar.hp_inner, 500, pet)


class ReplyPrefixes(unittest.TestCase):
    def test_only_generic_and_draconia_role_prefixes_are_stripped(self):
        from DyberPet.companion_director import clean_reply
        from DyberPet.brain_client import parse_reply
        self.assertEqual(clean_reply('"Zzq: hello there"'), 'Zzq: hello there')
        for raw in ('Draconia: [happy] Fine.', 'assistant: [happy] Fine.'):
            self.assertEqual(parse_reply(raw)[1], 'Fine.', raw)


if __name__ == '__main__':
    unittest.main()
